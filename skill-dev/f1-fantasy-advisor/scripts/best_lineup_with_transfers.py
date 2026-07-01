#!/usr/bin/env python3
"""Find the best scored F1 Fantasy lineup after transfer penalties."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Asset:
    asset_id: str
    type: str
    name: str
    price: Decimal
    score: Decimal
    scored_round_id: str


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


def decimal_value(raw: object, field: str) -> Decimal:
    """把 CSV 或命令行里的数字转成 Decimal。"""
    value = "" if raw is None else str(raw).strip()
    value = value.replace("$", "").replace("M", "").replace(",", "").replace("+", "")
    if value == "":
        raise ValueError(f"Missing numeric value for {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {raw!r}") from exc


def fmt_decimal(value: Decimal, places: str = "0.1") -> str:
    """把 Decimal 格式化成紧凑的一位小数文本。"""
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def read_csv(path: Path) -> list[dict[str, str]]:
    """读取 CSV 并清理每个字段两端空白。"""
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def split_ids(value: str) -> list[str]:
    """把逗号、分号或斜杠分隔的 asset id 文本拆成列表。"""
    cleaned = value.replace(";", ",").replace("|", ",").replace("/", ",")
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def load_round_context(official_dir: Path) -> dict[str, str]:
    """读取目标周上下文；没有文件时返回空字典。"""
    path = official_dir / "official_round_context.csv"
    if not path.exists():
        return {}
    rows = read_csv(path)
    return rows[0] if rows else {}


def load_assets(official_dir: Path) -> list[Asset]:
    """从 official_asset_metrics.csv 读取本周已有分数的资产。"""
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


def validate_previous_lineup(raw_lineup: str) -> tuple[str, ...]:
    """校验上周阵容必须是 7 个不重复 asset id。"""
    asset_ids = split_ids(raw_lineup)
    if len(asset_ids) != 7:
        raise ValueError("--previous-lineup must contain exactly 7 asset ids")
    if len(set(asset_ids)) != 7:
        raise ValueError("--previous-lineup must not contain duplicate asset ids")
    return tuple(asset_ids)


def normalize_name(value: str) -> str:
    """把名称转成适合模糊匹配的格式。"""
    return " ".join(value.lower().replace(".", "").split())


def initials_for(value: str) -> str:
    """生成名称首字母缩写，例如 Lewis Hamilton -> lh。"""
    return "".join(part[0] for part in normalize_name(value).split() if part)


def match_asset_token(
    token: str, candidates: list[Asset], label: str, allow_number_index: bool = True
) -> Asset:
    """用列表编号、asset id、全名或缩写匹配一个资产。"""
    cleaned = token.strip()
    if not cleaned:
        raise ValueError(f"empty {label} selection")
    if allow_number_index and cleaned.isdigit():
        index = int(cleaned)
        if 1 <= index <= len(candidates):
            return candidates[index - 1]

    by_id = {asset.asset_id: asset for asset in candidates}
    if cleaned in by_id:
        return by_id[cleaned]

    normalized = normalize_name(cleaned)
    exact = [asset for asset in candidates if normalize_name(asset.name) == normalized]
    if len(exact) == 1:
        return exact[0]

    initial_matches = [
        asset for asset in candidates if initials_for(asset.name) == normalized
    ]
    if len(initial_matches) == 1:
        return initial_matches[0]

    fuzzy = [
        asset
        for asset in candidates
        if normalized in normalize_name(asset.name)
        or any(part.startswith(normalized) for part in normalize_name(asset.name).split())
    ]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if not fuzzy:
        raise ValueError(f"No {label} matched {token!r}")
    names = ", ".join(asset.name for asset in fuzzy)
    raise ValueError(f"{label} selection {token!r} is ambiguous: {names}")


def parse_asset_selection(
    raw_selection: str,
    candidates: list[Asset],
    expected_count: int,
    label: str,
) -> tuple[Asset, ...]:
    """解析一次性输入的多个资产选择。"""
    tokens = split_ids(raw_selection)
    if len(tokens) != expected_count:
        raise ValueError(f"Select exactly {expected_count} {label}s")
    selected = tuple(match_asset_token(token, candidates, label) for token in tokens)
    selected_ids = [asset.asset_id for asset in selected]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError(f"Duplicate {label} selections are not allowed")
    return selected


def match_prefixed_asset_number(
    token: str, drivers: list[Asset], constructors: list[Asset]
) -> Asset | None:
    """解析 d1/c1 这种带类型前缀的列表编号。"""
    cleaned = token.strip().lower()
    if len(cleaned) < 2 or not cleaned[1:].isdigit():
        return None
    index = int(cleaned[1:]) - 1
    if cleaned[0] == "d" and 0 <= index < len(drivers):
        return drivers[index]
    if cleaned[0] == "c" and 0 <= index < len(constructors):
        return constructors[index]
    return None


def parse_exclusion_selection(
    raw_selection: str, drivers: list[Asset], constructors: list[Asset]
) -> tuple[Asset, ...]:
    """解析本场不能选择的资产列表。"""
    tokens = split_ids(raw_selection)
    if not tokens:
        return ()

    all_assets = drivers + constructors
    selected: list[Asset] = []
    for token in tokens:
        prefixed = match_prefixed_asset_number(token, drivers, constructors)
        if prefixed is not None:
            selected.append(prefixed)
            continue
        selected.append(
            match_asset_token(
                token, all_assets, "excluded asset", allow_number_index=False
            )
        )

    selected_ids = [asset.asset_id for asset in selected]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Duplicate excluded assets are not allowed")
    return tuple(selected)


def previous_lineup_price(assets: list[Asset], previous_lineup: tuple[str, ...]) -> Decimal:
    """用上周阵容 asset id 计算上周阵容价格。"""
    assets_by_id = {asset.asset_id: asset for asset in assets}
    missing = [asset_id for asset_id in previous_lineup if asset_id not in assets_by_id]
    if missing:
        raise ValueError("Previous lineup assets are missing from official data: " + ", ".join(missing))
    return sum((assets_by_id[asset_id].price for asset_id in previous_lineup), Decimal("0"))


def budget_from_remaining_bank(
    assets: list[Asset], previous_lineup: tuple[str, ...], remaining_bank: Decimal
) -> Decimal:
    """把剩余资金转换成总预算。"""
    if remaining_bank < 0:
        raise ValueError("remaining bank must be non-negative")
    return previous_lineup_price(assets, previous_lineup) + remaining_bank


def print_asset_choices(title: str, candidates: list[Asset]) -> None:
    """打印交互模式的可选资产列表。"""
    print(title)
    for index, asset in enumerate(candidates, start=1):
        print(
            f"{index:2}. {asset.name} ({asset.asset_id}) "
            f"price {fmt_decimal(asset.price)}M, score {fmt_decimal(asset.score)}"
        )


def prompt_asset_selection(candidates: list[Asset], expected_count: int, label: str) -> tuple[Asset, ...]:
    """循环询问用户选择资产，直到输入合法。"""
    while True:
        raw_selection = input(
            f"Select {expected_count} {label}s by number, id, name, or abbreviation: "
        )
        try:
            return parse_asset_selection(raw_selection, candidates, expected_count, label)
        except ValueError as exc:
            print(f"error: {exc}")


def prompt_decimal(prompt: str, field: str) -> Decimal:
    """循环询问一个 Decimal 数字。"""
    while True:
        try:
            return decimal_value(input(prompt), field)
        except ValueError as exc:
            print(f"error: {exc}")


def prompt_excluded_assets(drivers: list[Asset], constructors: list[Asset]) -> tuple[Asset, ...]:
    """询问本场不能选择的资产。"""
    while True:
        raw_selection = input(
            "Unavailable picks for this race (optional; names/ids, or d1/c1 list numbers): "
        )
        try:
            return parse_exclusion_selection(raw_selection, drivers, constructors)
        except ValueError as exc:
            print(f"error: {exc}")


def interactive_previous_lineup_budget_and_exclusions(
    assets: list[Asset],
) -> tuple[tuple[str, ...], Decimal, tuple[str, ...]]:
    """交互式选择上周阵容、询问剩余资金和本场不可选资产。"""
    drivers = [asset for asset in assets if asset.type == "driver"]
    constructors = [asset for asset in assets if asset.type == "constructor"]
    print_asset_choices("Drivers:", drivers)
    selected_drivers = prompt_asset_selection(drivers, 5, "driver")
    print()
    print_asset_choices("Constructors:", constructors)
    selected_constructors = prompt_asset_selection(constructors, 2, "constructor")
    previous_lineup = tuple(
        asset.asset_id for asset in selected_drivers + selected_constructors
    )
    previous_price = previous_lineup_price(assets, previous_lineup)
    remaining_bank = prompt_decimal("Remaining bank (M): ", "remaining bank")
    budget = previous_price + remaining_bank
    excluded_assets = prompt_excluded_assets(drivers, constructors)
    excluded_ids = tuple(asset.asset_id for asset in excluded_assets)
    print()
    print(f"Previous lineup price: {fmt_decimal(previous_price)}M")
    print(f"Remaining bank: {fmt_decimal(remaining_bank)}M")
    print(f"Computed budget: {fmt_decimal(budget)}M")
    if excluded_assets:
        print("Unavailable picks:")
        for asset in excluded_assets:
            print(f"  - {asset.name} ({asset.asset_id})")
    print()
    return previous_lineup, budget, excluded_ids


def latest_scored_round_id(assets: Iterable[Asset]) -> str:
    """从资产数据里找出官方已有分数的最新周 id。"""
    round_ids = sorted({asset.scored_round_id for asset in assets if asset.scored_round_id})
    return round_ids[-1] if round_ids else ""


def two_x_driver_for(drivers: Iterable[Asset]) -> Asset:
    """选出本阵容里 2x 后贡献最大的车手。"""
    return max(drivers, key=lambda asset: (asset.score, asset.name))


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

    price = sum((asset.price for asset in assets), Decimal("0"))
    base_score = sum((asset.score for asset in assets), Decimal("0"))
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
    drivers = [asset for asset in assets if asset.type == "driver"]
    constructors = [asset for asset in assets if asset.type == "constructor"]
    if len(drivers) < 5:
        raise ValueError(f"Need at least 5 active drivers, found {len(drivers)}")
    if len(constructors) < 2:
        raise ValueError(f"Need at least 2 active constructors, found {len(constructors)}")

    previous_ids = set(previous_lineup)
    lineups: list[TransferLineup] = []
    for driver_combo in combinations(drivers, 5):
        for constructor_combo in combinations(constructors, 2):
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


def name_for_asset_id(asset_id: str, assets_by_id: dict[str, Asset]) -> str:
    """把 asset id 格式化成带名称的文本。"""
    asset = assets_by_id.get(asset_id)
    return f"{asset.name} ({asset.asset_id})" if asset else asset_id


def print_asset(asset: Asset) -> None:
    """打印一个资产的价格和本周得分。"""
    print(
        f"  - {asset.name} ({asset.asset_id}): "
        f"price {fmt_decimal(asset.price)}M, score {fmt_decimal(asset.score)}"
    )


def print_report(
    lineups: list[TransferLineup],
    assets: list[Asset],
    budget: Decimal,
    previous_lineup: tuple[str, ...],
    excluded_ids: tuple[str, ...],
    free_transfers: int,
    penalty_per_extra: Decimal,
    context: dict[str, str],
) -> None:
    """打印周信息、换人规则和每套候选阵容。"""
    assets_by_id = {asset.asset_id: asset for asset in assets}
    scored_round = latest_scored_round_id(assets)
    target_round = context.get("target_round_id", "")
    fetched_at = context.get("fetched_at", "")

    print("Official data:")
    if scored_round:
        print(f"- latest scored round: {scored_round}")
    if target_round:
        print(f"- target_round_id in snapshot: {target_round}")
    if fetched_at:
        print(f"- fetched_at: {fetched_at}")
    print()
    print(f"Budget: {fmt_decimal(budget)}M")
    print(f"Free transfers: {free_transfers}")
    print(f"Penalty per extra transfer: -{fmt_decimal(penalty_per_extra)}")
    print("Previous lineup:")
    for asset_id in previous_lineup:
        print(f"  - {name_for_asset_id(asset_id, assets_by_id)}")
    if excluded_ids:
        print("Unavailable picks excluded from optimization:")
        for asset_id in excluded_ids:
            print(f"  - {name_for_asset_id(asset_id, assets_by_id)}")

    for index, lineup in enumerate(lineups, start=1):
        remaining = budget - lineup.price
        print()
        print(f"Lineup #{index}")
        print(f"- total price: {fmt_decimal(lineup.price)}M")
        print(f"- remaining budget: {fmt_decimal(remaining)}M")
        print(f"- raw lineup score: {fmt_decimal(lineup.base_score)}")
        print(f"- 2x driver bonus score: {fmt_decimal(lineup.two_x_bonus)}")
        print(f"- gross score with 2x: {fmt_decimal(lineup.gross_score)}")
        print(f"- transfer count: {lineup.transfer_count}")
        print(f"- extra transfers: {lineup.extra_transfers}")
        print(f"- transfer penalty: -{fmt_decimal(lineup.transfer_penalty)}")
        print(f"- net score after transfers: {fmt_decimal(lineup.net_score)}")
        print(f"- 2x driver: {lineup.two_x_driver.name} ({lineup.two_x_driver.asset_id})")
        print("Transfers in:")
        if lineup.transfers_in:
            for asset in sorted(lineup.transfers_in, key=lambda item: item.name):
                print_asset(asset)
        else:
            print("  - none")
        print("Transfers out:")
        if lineup.transfers_out:
            for asset_id in lineup.transfers_out:
                print(f"  - {name_for_asset_id(asset_id, assets_by_id)}")
        else:
            print("  - none")
        print("Drivers:")
        for asset in sorted(lineup.drivers, key=lambda item: item.score, reverse=True):
            print_asset(asset)
        print("Constructors:")
        for asset in sorted(lineup.constructors, key=lambda item: item.score, reverse=True):
            print_asset(asset)


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("budget", nargs="?", help="Total cost cap, e.g. 112")
    parser.add_argument(
        "--previous-lineup",
        default="",
        help="Previous 7 asset ids: 5 drivers and 2 constructors",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pick previous lineup by number/name, then enter remaining bank",
    )
    parser.add_argument(
        "--remaining-bank",
        "--remain",
        default="",
        help="Remaining bank; total budget becomes previous lineup price plus this value",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Assets unavailable for this race; supports names, ids, abbreviations, d1/c1",
    )
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=Path("data/official"),
        help="Directory containing official_asset_metrics.csv",
    )
    parser.add_argument("--free-transfers", type=int, default=2)
    parser.add_argument("--penalty-per-extra", default="10")
    parser.add_argument("--top", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：读取数据、枚举阵容并打印最优结果。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        penalty_per_extra = decimal_value(args.penalty_per_extra, "penalty_per_extra")
        if args.free_transfers < 0:
            raise ValueError("--free-transfers must be non-negative")
        if penalty_per_extra < 0:
            raise ValueError("--penalty-per-extra must be non-negative")
        if args.top <= 0:
            raise ValueError("--top must be positive")

        assets = load_assets(args.official_dir)
        if args.interactive:
            previous_lineup, budget, excluded_ids = (
                interactive_previous_lineup_budget_and_exclusions(assets)
            )
        else:
            if not args.previous_lineup:
                raise ValueError("provide --previous-lineup or use --interactive")
            previous_lineup = validate_previous_lineup(args.previous_lineup)
            if args.remaining_bank:
                remaining_bank = decimal_value(args.remaining_bank, "remaining bank")
                budget = budget_from_remaining_bank(assets, previous_lineup, remaining_bank)
            elif args.budget:
                budget = decimal_value(args.budget, "budget")
            else:
                raise ValueError("provide budget or --remaining-bank")
            drivers = [asset for asset in assets if asset.type == "driver"]
            constructors = [asset for asset in assets if asset.type == "constructor"]
            excluded_assets = parse_exclusion_selection(args.exclude, drivers, constructors)
            excluded_ids = tuple(asset.asset_id for asset in excluded_assets)

        if budget <= 0:
            raise ValueError("budget must be positive")
        available_assets = [
            asset for asset in assets if asset.asset_id not in set(excluded_ids)
        ]
        lineups = generate_best_lineups(
            available_assets,
            budget,
            previous_lineup,
            args.free_transfers,
            penalty_per_extra,
            args.top,
        )
        print_report(
            lineups,
            assets,
            budget,
            previous_lineup,
            excluded_ids,
            args.free_transfers,
            penalty_per_extra,
            load_round_context(args.official_dir),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
