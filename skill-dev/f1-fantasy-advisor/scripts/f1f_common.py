#!/usr/bin/env python3
"""f1-fantasy-advisor 各脚本共享的工具函数与常量（仅标准库）。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence, TypeVar


ZERO = Decimal("0")
DRIVERS_PER_LINEUP = 5
CONSTRUCTORS_PER_LINEUP = 2
LINEUP_SIZE = DRIVERS_PER_LINEUP + CONSTRUCTORS_PER_LINEUP
DEFAULT_FREE_TRANSFERS = 2
DEFAULT_PENALTY_PER_EXTRA = "10"

T = TypeVar("T")


def decimal_value(raw: object, field: str) -> Decimal:
    """把 CSV、网页或命令行里的数字文本转成 Decimal。"""
    value = "" if raw is None else str(raw).strip()
    value = (
        value.replace("$", "")
        .replace("M", "")
        .replace(",", "")
        .replace("▲", "")
        .replace("▼", "")
        .replace("+", "")
    )
    if value == "":
        raise ValueError(f"Missing numeric value for {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {raw!r}") from exc


def fmt_decimal(value: Decimal, places: str | None = "0.1") -> str:
    """按网页价格/分数习惯格式化 Decimal；places=None 时保留原始精度。"""
    if places is None:
        quantized = value
    else:
        quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == ZERO:
        return "0"
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def normalize_name(value: str) -> str:
    """把名称转成适合模糊匹配的小写单空格文本。"""
    return " ".join(value.lower().replace(".", "").split())


def initials_for(value: str) -> str:
    """生成名称首字母缩写，例如 Lewis Hamilton -> lh。"""
    return "".join(part[0] for part in normalize_name(value).split() if part)


def split_ids(value: str) -> list[str]:
    """把逗号、分号、竖线或斜杠分隔的文本拆成列表。"""
    cleaned = value.replace(";", ",").replace("|", ",").replace("/", ",")
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def read_csv(path: Path, required: Sequence[str] | None = None) -> list[dict[str, str]]:
    """读取 CSV 并去掉单元格两端空白；可校验必需列并拒绝畸形行。"""
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        if required:
            missing = [column for column in required if column not in reader.fieldnames]
            if missing:
                raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if row.get(None):
                raise ValueError(
                    f"{path} row {line_number} has more cells than the header"
                )
            row.pop(None, None)
            rows.append(
                {key: (value or "").strip() for key, value in row.items()}
            )
        return rows


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    """写出 CSV，只保留 fieldnames 中列出的列。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_round_context(official_dir: Path) -> dict[str, str]:
    """读取目标周上下文；没有文件时返回空字典。"""
    path = official_dir / "official_round_context.csv"
    if not path.exists():
        return {}
    rows = read_csv(path)
    return rows[0] if rows else {}


def prompt_loop(prompt_text: str, parse: Callable[[str], T]) -> T:
    """循环读取输入直到 parse 成功；EOF 转成 ValueError 以便干净退出。"""
    while True:
        try:
            raw = input(prompt_text)
        except EOFError as exc:
            raise ValueError("input aborted (EOF)") from exc
        try:
            return parse(raw)
        except ValueError as exc:
            print(f"error: {exc}")


@dataclass(frozen=True)
class Asset:
    """统一的资产模型；scored_round_id 仅换人模型使用，code 仅 Live 工具使用。"""

    asset_id: str
    type: str
    name: str
    price: Decimal = ZERO
    score: Decimal = ZERO
    scored_round_id: str = ""
    code: str = ""


@dataclass(frozen=True)
class Lineup:
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    price: Decimal
    base_score: Decimal
    two_x_driver: Asset
    two_x_bonus: Decimal
    final_score: Decimal


@dataclass(frozen=True)
class TransferLineup:
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    price: Decimal
    base_score: Decimal
    two_x_driver: Asset
    two_x_bonus: Decimal
    gross_score: Decimal
    transfer_count: int
    extra_transfers: int
    transfer_penalty: Decimal
    net_score: Decimal
    transfers_in: tuple[Asset, ...]
    transfers_out: tuple[str, ...]


def load_official_assets(official_dir: Path) -> list[Asset]:
    """从 official_asset_metrics.csv 读取有上一站分数的可用资产。"""
    rows = read_csv(official_dir / "official_asset_metrics.csv")
    assets: list[Asset] = []
    for index, row in enumerate(rows, start=2):
        if row.get("is_active") != "1":
            continue
        asset_type = row.get("type", "").strip().lower()
        if asset_type not in {"driver", "constructor"}:
            raise ValueError(f"official_asset_metrics.csv row {index}: unknown type {asset_type!r}")
        asset_id = row.get("asset_id", "").strip()
        name = row.get("name", "").strip()
        if not asset_id or not name:
            raise ValueError(f"official_asset_metrics.csv row {index}: missing asset_id or name")
        assets.append(
            Asset(
                asset_id=asset_id,
                type=asset_type,
                name=name,
                price=decimal_value(row.get("last1_price"), "last1_price"),
                score=decimal_value(row.get("last1_fpoints"), "last1_fpoints"),
                scored_round_id=row.get("last1_round_id", "").strip(),
            )
        )
    return assets


def split_by_type(assets: Iterable[Asset]) -> tuple[list[Asset], list[Asset]]:
    """把资产列表拆成车手和车队两组。"""
    drivers = [asset for asset in assets if asset.type == "driver"]
    constructors = [asset for asset in assets if asset.type == "constructor"]
    return drivers, constructors


def two_x_driver_for(drivers: Iterable[Asset]) -> Asset:
    """选出本阵容里 2x 后贡献最大的车手。"""
    return max(drivers, key=lambda asset: (asset.score, asset.name))


def iter_lineup_combos(
    assets: Iterable[Asset],
) -> Iterator[tuple[tuple[Asset, ...], tuple[Asset, ...]]]:
    """枚举全部 5 车手 × 2 车队组合，并校验候选数量足够。"""
    drivers, constructors = split_by_type(assets)
    if len(drivers) < DRIVERS_PER_LINEUP:
        raise ValueError(
            f"Need at least {DRIVERS_PER_LINEUP} active drivers, found {len(drivers)}"
        )
    if len(constructors) < CONSTRUCTORS_PER_LINEUP:
        raise ValueError(
            f"Need at least {CONSTRUCTORS_PER_LINEUP} active constructors, "
            f"found {len(constructors)}"
        )
    for driver_combo in combinations(drivers, DRIVERS_PER_LINEUP):
        for constructor_combo in combinations(constructors, CONSTRUCTORS_PER_LINEUP):
            yield driver_combo, constructor_combo


def build_lineup(drivers: tuple[Asset, ...], constructors: tuple[Asset, ...]) -> Lineup:
    """根据 5 个车手和 2 个车队计算阵容价格与分数。"""
    assets = drivers + constructors
    price = sum((asset.price for asset in assets), ZERO)
    base_score = sum((asset.score for asset in assets), ZERO)
    two_x_driver = two_x_driver_for(drivers)
    two_x_bonus = two_x_driver.score
    return Lineup(
        drivers=drivers,
        constructors=constructors,
        price=price,
        base_score=base_score,
        two_x_driver=two_x_driver,
        two_x_bonus=two_x_bonus,
        final_score=base_score + two_x_bonus,
    )


def generate_lineups(assets: list[Asset], budget: Decimal, top: int) -> list[Lineup]:
    """穷举所有合法阵容，并返回分数最高的前几套。"""
    lineups: list[Lineup] = []
    for driver_combo, constructor_combo in iter_lineup_combos(assets):
        lineup = build_lineup(driver_combo, constructor_combo)
        if lineup.price <= budget:
            lineups.append(lineup)

    if not lineups:
        raise ValueError(f"No valid lineup fits budget {fmt_decimal(budget)}M")

    return sorted(
        lineups,
        key=lambda lineup: (
            lineup.final_score,
            lineup.base_score,
            budget - lineup.price,
            ",".join(asset.name for asset in lineup.drivers + lineup.constructors),
        ),
        reverse=True,
    )[:top]


def build_transfer_lineup(
    drivers: tuple[Asset, ...],
    constructors: tuple[Asset, ...],
    previous_ids: set[str],
    free_transfers: int,
    penalty_per_extra: Decimal,
) -> TransferLineup:
    """计算一个候选阵容的总分、换人次数和扣分后净分。"""
    assets = drivers + constructors
    selected_ids = {asset.asset_id for asset in assets}
    transfers_in = tuple(asset for asset in assets if asset.asset_id not in previous_ids)
    transfers_out = tuple(sorted(previous_ids - selected_ids))
    transfer_count = len(transfers_in)
    extra_transfers = max(0, transfer_count - free_transfers)
    transfer_penalty = penalty_per_extra * Decimal(extra_transfers)

    price = sum((asset.price for asset in assets), ZERO)
    base_score = sum((asset.score for asset in assets), ZERO)
    two_x_driver = two_x_driver_for(drivers)
    two_x_bonus = two_x_driver.score
    gross_score = base_score + two_x_bonus
    net_score = gross_score - transfer_penalty

    return TransferLineup(
        drivers=drivers,
        constructors=constructors,
        price=price,
        base_score=base_score,
        two_x_driver=two_x_driver,
        two_x_bonus=two_x_bonus,
        gross_score=gross_score,
        transfer_count=transfer_count,
        extra_transfers=extra_transfers,
        transfer_penalty=transfer_penalty,
        net_score=net_score,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
    )


def generate_best_lineups(
    assets: list[Asset],
    budget: Decimal,
    previous_lineup: tuple[str, ...],
    free_transfers: int,
    penalty_per_extra: Decimal,
    top: int,
) -> list[TransferLineup]:
    """穷举所有合法阵容，按扣分后净分返回最优结果。"""
    previous_ids = set(previous_lineup)
    lineups: list[TransferLineup] = []
    for driver_combo, constructor_combo in iter_lineup_combos(assets):
        lineup = build_transfer_lineup(
            driver_combo,
            constructor_combo,
            previous_ids,
            free_transfers,
            penalty_per_extra,
        )
        if lineup.price <= budget:
            lineups.append(lineup)

    if not lineups:
        raise ValueError(f"No valid lineup fits budget {fmt_decimal(budget)}M")

    return sorted(
        lineups,
        key=lambda lineup: (
            lineup.net_score,
            lineup.gross_score,
            -lineup.transfer_count,
            budget - lineup.price,
            ",".join(asset.name for asset in lineup.drivers + lineup.constructors),
        ),
        reverse=True,
    )[:top]


def print_asset(asset: Asset) -> None:
    """打印单个资产的名称、id、价格和分数。"""
    print(
        f"  - {asset.name} ({asset.asset_id}): "
        f"price {fmt_decimal(asset.price)}M, score {fmt_decimal(asset.score)}"
    )
