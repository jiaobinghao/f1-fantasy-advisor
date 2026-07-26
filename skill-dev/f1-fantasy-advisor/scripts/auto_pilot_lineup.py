#!/usr/bin/env python3
"""Generate simple F1 Fantasy Auto-Pilot lineups from official CSV snapshots."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from f1f_common import (
    Asset,
    Lineup,
    build_lineup,
    decimal_value,
    fmt_decimal,
    generate_lineups,
    load_round_context,
    print_asset,
    read_csv,
    two_x_driver_for,
)
from f1f_common import load_official_assets as load_assets


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
