#!/usr/bin/env python3
"""自动获取 Live 页面分数并交互计算 F1 Fantasy 阵容本站得分。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import f1f_common
from f1f_common import (
    Asset,
    decimal_value,
    initials_for,
    load_code_overrides,
    normalize_name,
    prompt_loop,
    read_csv,
    site_code,
)
from f1f_common import split_ids as split_selection


SOURCE_URL = "https://f1fantasytools.com/live"
LIVE_API_URL = "https://f1fantasytools.com/api/live-scoring"
CACHE_COLUMNS = [
    "asset_id",
    "type",
    "name",
    "code",
    "score",
    "status",
    "source",
    "recorded_at",
    "race_name",
    "round_number",
]
CONSTRUCTOR_CODES = f1f_common.DEFAULT_CONSTRUCTOR_CODES


@dataclass(frozen=True)
class LiveSnapshot:
    assets: tuple[Asset, ...]
    status: str
    source: str
    recorded_at: str
    race_name: str = ""
    round_number: str = ""


@dataclass(frozen=True)
class LineupScore:
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    two_x_driver: Asset
    base_score: Decimal
    two_x_bonus: Decimal
    final_score: Decimal


def fmt_decimal(value: Decimal) -> str:
    """把 Decimal 格式化成紧凑文本，保留原始精度。"""
    return f1f_common.fmt_decimal(value, places=None)


def load_catalog(official_dir: Path) -> list[Asset]:
    """从官方快照读取有效资产目录，分数暂置零。"""
    rows = read_csv(official_dir / "official_asset_metrics.csv")
    overrides = load_code_overrides(official_dir)
    assets: list[Asset] = []
    for index, row in enumerate(rows, start=2):
        if row.get("is_active") != "1":
            continue
        asset_type = row.get("type", "").lower()
        asset_id = row.get("asset_id", "")
        name = row.get("name", "")
        if asset_type not in {"driver", "constructor"} or not asset_id or not name:
            raise ValueError(f"official_asset_metrics.csv row {index}: invalid asset")
        assets.append(
            Asset(
                asset_id=asset_id,
                type=asset_type,
                name=name,
                code=site_code(asset_type, name, asset_id, overrides),
            )
        )
    return assets


def split_live_cells(line: str) -> list[str]:
    """把网页表格行拆成单元格。"""
    cleaned = line.strip().strip("|")
    if "|" in cleaned:
        return [cell.strip() for cell in cleaned.split("|") if cell.strip()]
    if "\t" in cleaned:
        return [cell.strip() for cell in cleaned.split("\t") if cell.strip()]
    if "," in cleaned:
        return [cell.strip() for cell in next(csv.reader([cleaned])) if cell.strip()]
    if "=" in cleaned:
        return [cell.strip() for cell in cleaned.split("=", 1) if cell.strip()]
    return cleaned.split()


def score_from_cells(cells: list[str], asset: Asset) -> Decimal | None:
    """从已匹配资产的表格单元格中提取 TOT 分数。"""
    code = asset.code.lower()
    name = normalize_name(asset.name)
    first = normalize_name(cells[0]) if cells else ""
    start = 1
    if first == code or first == name or first == asset.asset_id.lower():
        pass
    elif len(cells) >= 2 and normalize_name(" ".join(cells[:2])) == name:
        start = 2
    else:
        return None
    if len(cells) <= start:
        return None
    try:
        return decimal_value(cells[start], f"{asset.code} score")
    except ValueError:
        return None


def detect_status(text: str, requested_status: str) -> str:
    """从粘贴内容检测 finalized 状态，或采用命令行指定值。"""
    if requested_status != "auto":
        return requested_status
    upper = text.upper()
    if "FINALIZED" in upper:
        return "finalized"
    return "provisional"


def parse_live_text(text: str, catalog: list[Asset], status: str = "auto") -> LiveSnapshot:
    """解析从 Live 页面复制的车手和车队分数。"""
    by_code = {asset.code.lower(): asset for asset in catalog}
    by_id = {asset.asset_id.lower(): asset for asset in catalog}
    parsed: dict[str, Asset] = {}
    for line in text.splitlines():
        cells = split_live_cells(line)
        if len(cells) < 2 or re.fullmatch(r"[-: ]+", "".join(cells)):
            continue
        first = normalize_name(cells[0])
        candidate = by_code.get(first) or by_id.get(first)
        candidates = [candidate] if candidate else catalog
        for asset in candidates:
            if asset is None:
                continue
            score = score_from_cells(cells, asset)
            if score is None:
                continue
            previous = parsed.get(asset.asset_id)
            if previous and previous.score != score:
                raise ValueError(
                    f"Conflicting scores for {asset.code}: "
                    f"{fmt_decimal(previous.score)} and {fmt_decimal(score)}"
                )
            parsed[asset.asset_id] = Asset(
                asset_id=asset.asset_id,
                type=asset.type,
                name=asset.name,
                code=asset.code,
                score=score,
            )
            break

    drivers = [asset for asset in parsed.values() if asset.type == "driver"]
    constructors = [asset for asset in parsed.values() if asset.type == "constructor"]
    if len(drivers) < 5 or len(constructors) < 2:
        raise ValueError(
            "Live text must contain at least 5 drivers and 2 constructors; "
            f"parsed {len(drivers)} drivers and {len(constructors)} constructors"
        )
    ordered = tuple(parsed[asset.asset_id] for asset in catalog if asset.asset_id in parsed)
    return LiveSnapshot(
        assets=ordered,
        status=detect_status(text, status),
        source=SOURCE_URL,
        recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def extract_rsc_stream(html: str) -> str:
    """从 Next.js HTML 中拼接 React Server Components 数据流。"""
    chunks: list[str] = []
    pattern = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)
    for match in pattern.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, list)
            and len(payload) >= 2
            and payload[0] == 1
            and isinstance(payload[1], str)
        ):
            chunks.append(payload[1])
    if not chunks:
        raise ValueError("No Next.js RSC data found on the Live page")
    return "".join(chunks)


def extract_rsc_value(stream: str, key: str) -> object:
    """从 RSC 数据流中解码指定 JSON 字段。"""
    marker = f'"{key}":'
    start = stream.find(marker)
    if start < 0:
        raise ValueError(f"Live page is missing {key}")
    try:
        value, _ = json.JSONDecoder().raw_decode(stream, start + len(marker))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to decode {key} from Live page") from exc
    return value


def status_from_race(race: dict[str, object], requested_status: str) -> str:
    """根据本站正赛状态判断快照是 provisional 还是 finalized。"""
    if requested_status != "auto":
        return requested_status
    sessions = race.get("status", {})
    race_status = sessions.get("race", {}) if isinstance(sessions, dict) else {}
    if isinstance(race_status, dict) and race_status.get("finalized") is True:
        return "finalized"
    return "provisional"


def snapshot_from_site_data(
    drivers: object,
    constructors: object,
    race: object,
    catalog: list[Asset],
    requested_status: str = "auto",
    source: str = SOURCE_URL,
) -> LiveSnapshot:
    """把站点数据转换成本地 Live 快照。"""
    if not isinstance(drivers, list) or not isinstance(constructors, list):
        raise ValueError("Live page asset data has an unexpected shape")
    if not isinstance(race, dict):
        raise ValueError("Live page race data has an unexpected shape")

    catalog_by_code = {(asset.type, asset.code): asset for asset in catalog}
    assets: list[Asset] = []
    missing: list[str] = []
    for asset_type, rows in (("driver", drivers), ("constructor", constructors)):
        for row in rows:
            if not isinstance(row, dict) or row.get("isActive") is False:
                continue
            code = str(row.get("abbreviation", "")).strip().upper()
            catalog_asset = catalog_by_code.get((asset_type, code))
            if catalog_asset is None:
                if code:
                    missing.append(f"{asset_type}:{code}")
                continue
            assets.append(
                Asset(
                    asset_id=catalog_asset.asset_id,
                    type=asset_type,
                    name=catalog_asset.name,
                    code=code,
                    score=decimal_value(row.get("totalPoints"), f"{code} totalPoints"),
                )
            )
    if missing:
        raise ValueError("Live assets missing from official catalog: " + ", ".join(missing))
    if len([asset for asset in assets if asset.type == "driver"]) < 5:
        raise ValueError("Live page returned fewer than 5 active drivers")
    if len([asset for asset in assets if asset.type == "constructor"]) < 2:
        raise ValueError("Live page returned fewer than 2 active constructors")

    order = {(asset.type, asset.code): index for index, asset in enumerate(catalog)}
    assets.sort(key=lambda asset: order[(asset.type, asset.code)])
    return LiveSnapshot(
        assets=tuple(assets),
        status=status_from_race(race, requested_status),
        source=source,
        recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        race_name=str(race.get("name", "")),
        round_number=str(race.get("roundNumber", "")),
    )


def parse_live_html(
    html: str, catalog: list[Asset], status: str = "auto"
) -> LiveSnapshot:
    """解析 Live 页面 HTML 中嵌入的最新资产总分。"""
    stream = extract_rsc_stream(html)
    return snapshot_from_site_data(
        extract_rsc_value(stream, "initialDrivers"),
        extract_rsc_value(stream, "initialConstructors"),
        extract_rsc_value(stream, "initialRace"),
        catalog,
        status,
    )


def parse_live_api(
    payload: object, catalog: list[Asset], status: str = "auto"
) -> LiveSnapshot:
    """解析网页水合后实际请求的 Live scoring API 数据。"""
    if not isinstance(payload, dict):
        raise ValueError("Live scoring API returned an unexpected shape")
    return snapshot_from_site_data(
        payload.get("drivers"),
        payload.get("constructors"),
        payload.get("race"),
        catalog,
        status,
        LIVE_API_URL,
    )


def fetch_live_html(timeout: float = 30.0) -> str:
    """通过单次 HTTP GET 获取获授权的 Live 页面 HTML。"""
    request = Request(
        SOURCE_URL,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "User-Agent": "F1FantasyAdvisor/1.0 (authorized live-score fetcher)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise ValueError(f"Live page returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Unable to fetch Live page: {exc.reason}") from exc
    except OSError as exc:
        raise ValueError(f"Unable to fetch Live page: {exc}") from exc


def fetch_live_api(timeout: float = 30.0) -> object:
    """通过单次 HTTP GET 获取页面自身使用的 Live scoring JSON。"""
    request = Request(
        LIVE_API_URL,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Referer": SOURCE_URL,
            "User-Agent": "F1FantasyAdvisor/1.0 (authorized live-score fetcher)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise ValueError(f"Live scoring API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"Unable to fetch Live scoring API: {exc.reason}") from exc
    except OSError as exc:
        raise ValueError(f"Unable to fetch Live scoring API: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Live scoring API returned invalid JSON") from exc


def save_snapshot(snapshot: LiveSnapshot, path: Path) -> None:
    """把 Live 分数快照保存成可复用 CSV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CACHE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for asset in snapshot.assets:
            writer.writerow(
                {
                    "asset_id": asset.asset_id,
                    "type": asset.type,
                    "name": asset.name,
                    "code": asset.code,
                    "score": fmt_decimal(asset.score),
                    "status": snapshot.status,
                    "source": snapshot.source,
                    "recorded_at": snapshot.recorded_at,
                    "race_name": snapshot.race_name,
                    "round_number": snapshot.round_number,
                }
            )


def load_snapshot(path: Path) -> LiveSnapshot:
    """从缓存 CSV 读取 Live 分数快照。"""
    rows = read_csv(path, required=("asset_id", "type", "name", "code", "score"))
    if not rows:
        raise ValueError(f"Live score cache is empty: {path}")
    assets = tuple(
        Asset(
            asset_id=row["asset_id"],
            type=row["type"],
            name=row["name"],
            code=row["code"],
            score=decimal_value(row["score"], "score"),
        )
        for row in rows
    )
    return LiveSnapshot(
        assets=assets,
        status=rows[0].get("status", "provisional") or "provisional",
        source=rows[0].get("source", SOURCE_URL) or SOURCE_URL,
        recorded_at=rows[0].get("recorded_at", ""),
        race_name=rows[0].get("race_name", ""),
        round_number=rows[0].get("round_number", ""),
    )


def windows_clipboard_available() -> bool:
    """检查当前环境能否通过 PowerShell 读取 Windows 剪贴板。"""
    return shutil.which("powershell.exe") is not None


def read_windows_clipboard() -> str:
    """通过 PowerShell 读取 Windows 剪贴板中的网页文本。"""
    if not windows_clipboard_available():
        raise ValueError("powershell.exe is unavailable; use manual paste instead")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown PowerShell error"
        raise ValueError(f"Unable to read Windows clipboard: {detail}")
    if not result.stdout.strip():
        raise ValueError("Windows clipboard is empty")
    return result.stdout


def match_asset(token: str, candidates: list[Asset], prefix: str) -> Asset:
    """用列表编号、代码、asset id、名称或缩写匹配资产。"""
    cleaned = token.strip()
    lowered = normalize_name(cleaned)
    index_text = lowered[1:] if lowered.startswith(prefix) else lowered
    if index_text.isdigit():
        index = int(index_text)
        if 1 <= index <= len(candidates):
            return candidates[index - 1]
    exact = [
        asset
        for asset in candidates
        if lowered in {asset.asset_id.lower(), asset.code.lower(), normalize_name(asset.name)}
    ]
    if len(exact) == 1:
        return exact[0]
    fuzzy = [
        asset
        for asset in candidates
        if lowered == initials_for(asset.name)
        or lowered in normalize_name(asset.name)
        or any(part.startswith(lowered) for part in normalize_name(asset.name).split())
    ]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if not fuzzy:
        raise ValueError(f"No asset matched {token!r}")
    raise ValueError(
        f"Asset selection {token!r} is ambiguous: " + ", ".join(asset.name for asset in fuzzy)
    )


def parse_selection(
    value: str, candidates: list[Asset], expected_count: int, prefix: str
) -> tuple[Asset, ...]:
    """解析固定数量且不重复的资产选择。"""
    tokens = split_selection(value)
    if len(tokens) != expected_count:
        raise ValueError(f"Select exactly {expected_count} assets")
    selected = tuple(match_asset(token, candidates, prefix) for token in tokens)
    if len({asset.asset_id for asset in selected}) != len(selected):
        raise ValueError("Duplicate assets are not allowed")
    return selected


def print_choices(title: str, assets: list[Asset], prefix: str) -> None:
    """打印带编号的实时分数资产列表。"""
    print(title)
    for index, asset in enumerate(assets, start=1):
        print(
            f"  {prefix}{index:02}  {asset.code:<3}  "
            f"{asset.name:<24} {fmt_decimal(asset.score):>6}"
        )


def prompt_selection(
    prompt: str, candidates: list[Asset], expected_count: int, prefix: str
) -> tuple[Asset, ...]:
    """循环询问资产，直到选择合法。"""
    return prompt_loop(
        prompt,
        lambda raw: parse_selection(raw, candidates, expected_count, prefix),
    )


def prompt_two_x(drivers: tuple[Asset, ...]) -> Asset:
    """询问并校验 2x 车手必须来自已选车手。"""
    return prompt_loop(
        "Select the 2x driver: ",
        lambda raw: match_asset(raw, list(drivers), "d"),
    )


def calculate_lineup(
    drivers: tuple[Asset, ...], constructors: tuple[Asset, ...], two_x_driver: Asset
) -> LineupScore:
    """计算 5 位车手、2 个车队和 2x 加成后的本站总分。"""
    if len(drivers) != 5 or len(constructors) != 2:
        raise ValueError("Lineup must contain 5 drivers and 2 constructors")
    if two_x_driver.asset_id not in {asset.asset_id for asset in drivers}:
        raise ValueError("2x driver must be one of the selected drivers")
    base_score = sum((asset.score for asset in drivers + constructors), Decimal("0"))
    return LineupScore(
        drivers=drivers,
        constructors=constructors,
        two_x_driver=two_x_driver,
        base_score=base_score,
        two_x_bonus=two_x_driver.score,
        final_score=base_score + two_x_driver.score,
    )


def print_report(snapshot: LiveSnapshot, lineup: LineupScore) -> None:
    """打印快照信息、阵容明细和本站总分。"""
    print()
    print("Live score snapshot:")
    if snapshot.race_name:
        round_text = f" (Round {snapshot.round_number})" if snapshot.round_number else ""
        print(f"- race: {snapshot.race_name}{round_text}")
    print(f"- status: {snapshot.status.upper()}")
    print(f"- recorded_at: {snapshot.recorded_at}")
    print(f"- source: {snapshot.source}")
    print("Drivers:")
    for asset in lineup.drivers:
        marker = " (2x)" if asset.asset_id == lineup.two_x_driver.asset_id else ""
        print(f"  - {asset.code} {asset.name}: {fmt_decimal(asset.score)}{marker}")
    print("Constructors:")
    for asset in lineup.constructors:
        print(f"  - {asset.code} {asset.name}: {fmt_decimal(asset.score)}")
    print(f"Raw lineup score: {fmt_decimal(lineup.base_score)}")
    print(f"2x bonus ({lineup.two_x_driver.code}): {fmt_decimal(lineup.two_x_bonus)}")
    print(f"Final lineup score: {fmt_decimal(lineup.final_score)}")


def print_snapshot(snapshot: LiveSnapshot, cache_path: Path) -> None:
    """打印刚获取的 Live 快照摘要。"""
    drivers = [asset for asset in snapshot.assets if asset.type == "driver"]
    constructors = [asset for asset in snapshot.assets if asset.type == "constructor"]
    print(f"Saved {len(snapshot.assets)} live scores to {cache_path}")
    if snapshot.race_name:
        round_text = f" (Round {snapshot.round_number})" if snapshot.round_number else ""
        print(f"Race: {snapshot.race_name}{round_text}")
    print(f"Status: {snapshot.status.upper()}")
    print(f"Recorded at: {snapshot.recorded_at}")
    print_choices("Drivers:", drivers, "d")
    print_choices("Constructors:", constructors, "c")


def interactive_lineup(snapshot: LiveSnapshot) -> LineupScore:
    """交互选择阵容和 2x 车手并返回计分结果。"""
    drivers = [asset for asset in snapshot.assets if asset.type == "driver"]
    constructors = [asset for asset in snapshot.assets if asset.type == "constructor"]
    print_choices("Drivers:", drivers, "d")
    selected_drivers = prompt_selection(
        "Select 5 drivers (codes/names/d#; comma separated): ", drivers, 5, "d"
    )
    print()
    print_choices("Constructors:", constructors, "c")
    selected_constructors = prompt_selection(
        "Select 2 constructors (codes/names/c#; comma separated): ",
        constructors,
        2,
        "c",
    )
    two_x_driver = prompt_two_x(selected_drivers)
    return calculate_lineup(selected_drivers, selected_constructors, two_x_driver)


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fetch", action="store_true", help="Fetch current Live scores and update cache"
    )
    mode.add_argument(
        "--interactive",
        action="store_true",
        help="Select 5 drivers, 2 constructors, and 2x from cached scores",
    )
    parser.add_argument("--input", type=Path, help="Text file copied from the Live page")
    parser.add_argument(
        "--clipboard",
        action="store_true",
        help="Fallback: read copied Live page text from the Windows clipboard",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/live/live_asset_scores.csv"),
        help="Live score cache CSV",
    )
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=Path("data/official"),
        help="Directory containing official_asset_metrics.csv",
    )
    parser.add_argument(
        "--status",
        choices=("auto", "provisional", "finalized"),
        default="auto",
        help="Override score settlement status",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="HTTP timeout for --fetch"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：获取 Live 分数或从缓存交互计算阵容得分。"""
    args = build_parser().parse_args(argv)
    try:
        if args.interactive:
            if args.input or args.clipboard:
                raise ValueError("--input and --clipboard can only be used with --fetch")
            snapshot = load_snapshot(args.cache)
            lineup = interactive_lineup(snapshot)
            print_report(snapshot, lineup)
            return 0

        catalog = load_catalog(args.official_dir)
        if args.input:
            text = args.input.read_text(encoding="utf-8-sig")
            stripped = text.lstrip()
            if stripped.startswith("{"):
                snapshot = parse_live_api(json.loads(text), catalog, args.status)
            elif "initialDrivers" in text and "self.__next_f.push" in text:
                snapshot = parse_live_html(text, catalog, args.status)
            else:
                snapshot = parse_live_text(text, catalog, args.status)
        elif args.clipboard:
            print(f"Reading copied Live scores from Windows clipboard: {SOURCE_URL}")
            text = read_windows_clipboard()
            snapshot = parse_live_text(text, catalog, args.status)
        else:
            if args.timeout <= 0:
                raise ValueError("--timeout must be positive")
            print(f"Fetching authorized Live scores: {LIVE_API_URL}")
            snapshot = parse_live_api(fetch_live_api(args.timeout), catalog, args.status)
        save_snapshot(snapshot, args.cache)
        print_snapshot(snapshot, args.cache)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
