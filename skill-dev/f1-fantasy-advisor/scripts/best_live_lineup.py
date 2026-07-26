#!/usr/bin/env python3
"""用上一站官方价格和本站 Live 分数计算最佳 F1 Fantasy 阵容。"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import auto_pilot_lineup as auto_pilot
import best_lineup_with_transfers as transfers
import live_lineup_score as live_scores
from f1f_common import (
    DEFAULT_FREE_TRANSFERS,
    DEFAULT_PENALTY_PER_EXTRA,
    Asset,
    generate_lineups,
    load_official_assets,
    load_round_context,
    normalize_name,
)


@dataclass(frozen=True)
class CombinedData:
    """保存官方价格、Live 分数及轮次上下文。"""

    snapshot: live_scores.LiveSnapshot
    context: dict[str, str]
    assets: tuple[Asset, ...]


def normalize_race_name(value: str) -> str:
    """把比赛名称归一化用于比较，去掉 Grand Prix/GP 后缀。"""
    cleaned = normalize_name(value)
    for suffix in (" grand prix", " gp"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned.strip()


def validate_live_round(
    snapshot: live_scores.LiveSnapshot, context: dict[str, str]
) -> None:
    """校验 Live 缓存与官方目标站是同一场比赛。

    官方 target_round_id 是 F1 Fantasy 的 GamedayId，而 Live 缓存的
    round_number 来自第三方站点的锦标赛站序，两套编号可能有偏移，
    所以名称匹配优先，编号不一致只作告警；仅当名称缺失时才退回编号比较。
    """
    official_name = normalize_race_name(context.get("meeting_name", ""))
    live_name = normalize_race_name(snapshot.race_name)
    official_round = context.get("target_round_id", "").strip()
    live_round = snapshot.round_number.strip()

    if official_name and live_name:
        if official_name != live_name:
            raise ValueError(
                "Race mismatch: official target is "
                f"{context.get('meeting_name', '').strip()!r}, "
                f"but Live cache is for {snapshot.race_name!r}"
            )
        if official_round and live_round and official_round != live_round:
            print(
                "warning: race names match but round ids differ "
                f"(official {official_round}, live {live_round}); "
                "the two feeds use different numbering schemes",
                file=sys.stderr,
            )
        return

    if official_round and live_round and official_round != live_round:
        raise ValueError(
            f"Round mismatch: official target is {official_round}, "
            f"but Live cache is round {live_round}"
        )


def live_score_map(snapshot: live_scores.LiveSnapshot) -> dict[str, Asset]:
    """把 Live 快照转换成按 asset id 查询的映射。"""
    scores = {asset.asset_id: asset for asset in snapshot.assets}
    if len(scores) != len(snapshot.assets):
        raise ValueError("Live cache contains duplicate asset ids")
    return scores


def merge_live_scores(
    assets: list[Asset], scores: dict[str, Asset]
) -> tuple[Asset, ...]:
    """保留官方价格与上一站 id，并覆盖为本站 Live 分数。"""
    merged: list[Asset] = []
    for asset in assets:
        live_asset = scores.get(asset.asset_id)
        if live_asset is None:
            raise ValueError(f"Live cache is missing {asset.name} ({asset.asset_id})")
        if live_asset.type != asset.type:
            raise ValueError(f"Asset type mismatch for {asset.name} ({asset.asset_id})")
        merged.append(replace(asset, score=live_asset.score))
    return tuple(merged)


def load_combined_data(official_dir: Path, cache_path: Path) -> CombinedData:
    """读取上一站官方价格，并按 asset id 合并本站 Live 分数。"""
    snapshot = live_scores.load_snapshot(cache_path)
    context = load_round_context(official_dir)
    validate_live_round(snapshot, context)
    scores = live_score_map(snapshot)
    return CombinedData(
        snapshot=snapshot,
        context=context,
        assets=merge_live_scores(load_official_assets(official_dir), scores),
    )


def print_sources(data: CombinedData) -> None:
    """打印本站分数与上一站价格的数据来源。"""
    snapshot = data.snapshot
    print("Combined data:")
    print("- prices: official last1_price")
    print(f"- live scores: {snapshot.source}")
    if snapshot.race_name:
        round_text = f" (Round {snapshot.round_number})" if snapshot.round_number else ""
        print(f"- race: {snapshot.race_name}{round_text}")
    print(f"- status: {snapshot.status.upper()}")
    print(f"- recorded_at: {snapshot.recorded_at}")
    if snapshot.status != "finalized":
        print("- warning: Live scores are provisional and may still change")
    print()


def run_budget_mode(args: argparse.Namespace, data: CombinedData) -> None:
    """按预算计算使用本站 Live 分数的理论最佳阵容。"""
    budget = auto_pilot.decimal_value(args.budget, "budget")
    if budget <= 0:
        raise ValueError("budget must be positive")
    if args.top <= 0:
        raise ValueError("--top must be positive")
    lineups = generate_lineups(list(data.assets), budget, args.top)
    print_sources(data)
    auto_pilot.print_report(lineups, budget, data.context)


def run_transfers_mode(args: argparse.Namespace, data: CombinedData) -> None:
    """计算考虑超额换人扣分后的本站最佳阵容。"""
    if args.free_transfers < 0:
        raise ValueError("--free-transfers must be non-negative")
    if args.top <= 0:
        raise ValueError("--top must be positive")
    penalty = transfers.decimal_value(args.penalty_per_extra, "penalty_per_extra")
    if penalty < 0:
        raise ValueError("--penalty-per-extra must be non-negative")

    assets = list(data.assets)
    previous_lineup, budget, excluded_ids = transfers.resolve_transfer_inputs(
        args, assets
    )
    if budget <= 0:
        raise ValueError("budget must be positive")
    excluded_set = set(excluded_ids)
    available_assets = [
        asset for asset in assets if asset.asset_id not in excluded_set
    ]
    lineups = transfers.generate_best_lineups(
        available_assets,
        budget,
        previous_lineup,
        args.free_transfers,
        penalty,
        args.top,
    )
    print_sources(data)
    transfers.print_report(
        lineups,
        assets,
        budget,
        previous_lineup,
        excluded_ids,
        args.free_transfers,
        penalty,
        data.context,
    )


def add_data_arguments(parser: argparse.ArgumentParser) -> None:
    """为子命令添加官方目录与 Live 缓存参数。"""
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=Path("data/official"),
        help="Directory containing official_asset_metrics.csv",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("data/live/live_asset_scores.csv"),
        help="Live score cache created by live_lineup_score.py --fetch",
    )


def build_parser() -> argparse.ArgumentParser:
    """创建预算与换人两种本站最佳阵容子命令。"""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    budget = modes.add_parser("budget", help="Find the highest live-scoring lineup")
    budget.add_argument("budget", help="Total cost cap, e.g. 112")
    budget.add_argument("--top", type=int, default=5)
    add_data_arguments(budget)

    transfer = modes.add_parser(
        "transfers", help="Optimize live score after transfer penalties"
    )
    transfer.add_argument("budget", nargs="?", help="Total cost cap, e.g. 112")
    transfer.add_argument(
        "--previous-lineup",
        default="",
        help="Previous 7 asset ids: 5 drivers and 2 constructors",
    )
    transfer.add_argument(
        "--interactive",
        action="store_true",
        help="Pick previous lineup by number/name, then enter remaining bank",
    )
    transfer.add_argument(
        "--remaining-bank",
        "--remain",
        default="",
        help="Remaining bank; total budget becomes previous lineup price plus this value",
    )
    transfer.add_argument(
        "--exclude",
        default="",
        help="Assets unavailable for this race; supports names, ids, abbreviations, d1/c1",
    )
    transfer.add_argument(
        "--free-transfers",
        type=int,
        default=DEFAULT_FREE_TRANSFERS,
        help="Free transfers before penalties apply",
    )
    transfer.add_argument(
        "--penalty-per-extra",
        default=DEFAULT_PENALTY_PER_EXTRA,
        help="Points deducted per extra transfer",
    )
    transfer.add_argument("--top", type=int, default=5, help="Number of lineups to print")
    add_data_arguments(transfer)
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：合并数据后调用现有两个阵容求解器。"""
    args = build_parser().parse_args(argv)
    try:
        data = load_combined_data(args.official_dir, args.cache)
        if args.mode == "budget":
            run_budget_mode(args, data)
        else:
            run_transfers_mode(args, data)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
