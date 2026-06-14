#!/usr/bin/env python3
"""Generate simple F1 Fantasy Auto-Pilot lineups from official CSV snapshots."""

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


@dataclass(frozen=True)
class Lineup:
    drivers: tuple[Asset, ...]
    constructors: tuple[Asset, ...]
    price: Decimal
    base_score: Decimal
    two_x_driver: Asset
    two_x_bonus: Decimal
    final_score: Decimal


def decimal_value(raw: object, field: str) -> Decimal:
    """把 CSV 里的数字文本转成 Decimal。"""
    value = "" if raw is None else str(raw).strip()
    value = value.replace("$", "").replace("M", "").replace(",", "").replace("+", "")
    if value == "":
        raise ValueError(f"Missing numeric value for {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {raw!r}") from exc


def fmt_decimal(value: Decimal, places: str = "0.1") -> str:
    """按网页价格/分数习惯格式化 Decimal。"""
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def read_csv(path: Path) -> list[dict[str, str]]:
    """读取 CSV 并去掉单元格两端空白。"""
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def load_round_context(official_dir: Path) -> dict[str, str]:
    """读取本站信息；文件不存在时返回空字典。"""
    path = official_dir / "official_round_context.csv"
    if not path.exists():
        return {}
    rows = read_csv(path)
    return rows[0] if rows else {}


def load_assets(official_dir: Path) -> list[Asset]:
    """从 official_asset_metrics.csv 读取可用资产。"""
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
            )
        )
    return assets


def two_x_driver_for(drivers: Iterable[Asset]) -> Asset:
    """选出 Auto-Pilot 自动 2x 的最高分车手。"""
    return max(drivers, key=lambda asset: (asset.score, asset.name))


def build_lineup(drivers: tuple[Asset, ...], constructors: tuple[Asset, ...]) -> Lineup:
    """根据 5 个车手和 2 个车队计算阵容价格与分数。"""
    assets = drivers + constructors
    price = sum((asset.price for asset in assets), Decimal("0"))
    base_score = sum((asset.score for asset in assets), Decimal("0"))
    two_x_driver = two_x_driver_for(drivers)
    two_x_bonus = two_x_driver.score
    final_score = base_score + two_x_bonus
    return Lineup(
        drivers=drivers,
        constructors=constructors,
        price=price,
        base_score=base_score,
        two_x_driver=two_x_driver,
        two_x_bonus=two_x_bonus,
        final_score=final_score,
    )


def generate_lineups(assets: list[Asset], budget: Decimal, top: int) -> list[Lineup]:
    """穷举所有合法阵容，并返回分数最高的前几套。"""
    drivers = [asset for asset in assets if asset.type == "driver"]
    constructors = [asset for asset in assets if asset.type == "constructor"]
    if len(drivers) < 5:
        raise ValueError(f"Need at least 5 active drivers, found {len(drivers)}")
    if len(constructors) < 2:
        raise ValueError(f"Need at least 2 active constructors, found {len(constructors)}")

    lineups: list[Lineup] = []
    for driver_combo in combinations(drivers, 5):
        for constructor_combo in combinations(constructors, 2):
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


def print_asset(asset: Asset) -> None:
    """打印单个资产的名称、id、价格和分数。"""
    print(
        f"  - {asset.name} ({asset.asset_id}): "
        f"price {fmt_decimal(asset.price)}M, score {fmt_decimal(asset.score)}"
    )


def print_report(lineups: list[Lineup], budget: Decimal, context: dict[str, str]) -> None:
    """打印本站信息和每套阵容的分数明细。"""
    meeting = context.get("meeting_name", "")
    target_round = context.get("target_round_id", "")
    fetched_at = context.get("fetched_at", "")
    if meeting or target_round or fetched_at:
        print("Round context:")
        if target_round:
            print(f"- target_round_id: {target_round}")
        if meeting:
            print(f"- meeting: {meeting}")
        if fetched_at:
            print(f"- fetched_at: {fetched_at}")
        print()

    print(f"Budget: {fmt_decimal(budget)}M")
    for index, lineup in enumerate(lineups, start=1):
        remaining = budget - lineup.price
        print()
        print(f"Lineup #{index}")
        print(f"- total price: {fmt_decimal(lineup.price)}M")
        print(f"- remaining budget: {fmt_decimal(remaining)}M")
        print(f"- raw lineup score: {fmt_decimal(lineup.base_score)}")
        print(f"- 2x driver bonus score: {fmt_decimal(lineup.two_x_bonus)}")
        print(f"- final score with 2x: {fmt_decimal(lineup.final_score)}")
        print(
            "- Auto-Pilot 2x driver: "
            f"{lineup.two_x_driver.name} ({lineup.two_x_driver.asset_id})"
        )
        print("Drivers:")
        for asset in sorted(lineup.drivers, key=lambda item: item.score, reverse=True):
            print_asset(asset)
        print("Constructors:")
        for asset in sorted(lineup.constructors, key=lambda item: item.score, reverse=True):
            print_asset(asset)


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("budget", help="Total cost cap, e.g. 112")
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=Path("data/official"),
        help="Directory containing official_asset_metrics.csv",
    )
    parser.add_argument("--top", type=int, default=5, help="Number of lineups to print")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：读取数据、生成阵容并打印报告。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        budget = decimal_value(args.budget, "budget")
        if budget <= 0:
            raise ValueError("budget must be positive")
        if args.top <= 0:
            raise ValueError("--top must be positive")
        assets = load_assets(args.official_dir)
        lineups = generate_lineups(assets, budget, args.top)
        print_report(lineups, budget, load_round_context(args.official_dir))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
