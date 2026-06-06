#!/usr/bin/env python3
"""Maintain F1 Fantasy asset totals, rolling scores, and price changes."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable


ASSET_COLUMNS = [
    "asset_id",
    "type",
    "name",
    "current_price",
    "current_total_fpoints",
    "previous_race_fpoints",
    "last_race_fpoints",
]

RACE_SCORE_COLUMNS = [
    "round",
    "asset_id",
    "type",
    "name",
    "race_fpoints",
    "rolling_3",
    "avg_ppm",
    "price_change",
    "price_after",
]

TEAM_COLUMNS = [
    "round",
    "team_id",
    "budget_before",
    "chip",
    "lineup_asset_ids",
    "boost_asset_id",
    "shadow_lineup_asset_ids",
]

IMPORT_TOTAL_COLUMNS = ["asset_id", "name", "total_fpoints"]

EXPENSIVE_CUTOFF = Decimal("18.5")
AVG_GREAT = Decimal("1.2")
AVG_GOOD = Decimal("0.9")
AVG_POOR = Decimal("0.6")


@dataclass(frozen=True)
class Asset:
    asset_id: str
    type: str
    name: str
    current_price: Decimal
    current_total_fpoints: Decimal
    previous_race_fpoints: Decimal
    last_race_fpoints: Decimal


@dataclass(frozen=True)
class RaceResult:
    round: str
    asset: Asset
    race_fpoints: Decimal
    rolling_3: Decimal
    avg_ppm: Decimal
    price_change: Decimal
    price_after: Decimal


def decimal_value(raw: object, field: str) -> Decimal:
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


def fmt_decimal(value: Decimal, places: str = "0.1") -> str:
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def fmt_ppm(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), "f")


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().replace(".", "").split())


def split_ids(value: str) -> list[str]:
    if not value:
        return []
    cleaned = value.replace(";", ",").replace("|", ",").replace("/", ",")
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def ensure_headers(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "imports").mkdir(parents=True, exist_ok=True)
    files = [
        ("assets_state.csv", ASSET_COLUMNS),
        ("race_scores.csv", RACE_SCORE_COLUMNS),
        ("team_state.csv", TEAM_COLUMNS),
    ]
    for filename, columns in files:
        path = data_dir / filename
        if not path.exists():
            write_csv(path, columns, [])


def load_assets(data_dir: Path) -> list[Asset]:
    rows = read_csv(data_dir / "assets_state.csv")
    assets: list[Asset] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows, start=2):
        asset_id = row.get("asset_id", "").strip()
        if not asset_id:
            raise ValueError(f"assets_state.csv row {index}: missing asset_id")
        if asset_id in seen_ids:
            raise ValueError(f"assets_state.csv row {index}: duplicate asset_id {asset_id}")
        seen_ids.add(asset_id)
        asset_type = row.get("type", "").strip().lower()
        if asset_type not in {"driver", "constructor"}:
            raise ValueError(
                f"assets_state.csv row {index}: type must be driver or constructor"
            )
        name = row.get("name", "").strip()
        if not name:
            raise ValueError(f"assets_state.csv row {index}: missing name")
        assets.append(
            Asset(
                asset_id=asset_id,
                type=asset_type,
                name=name,
                current_price=decimal_value(row.get("current_price"), "current_price"),
                current_total_fpoints=decimal_value(
                    row.get("current_total_fpoints"), "current_total_fpoints"
                ),
                previous_race_fpoints=decimal_value(
                    row.get("previous_race_fpoints"), "previous_race_fpoints"
                ),
                last_race_fpoints=decimal_value(
                    row.get("last_race_fpoints"), "last_race_fpoints"
                ),
            )
        )
    return assets


def asset_rows(assets: Iterable[Asset]) -> list[dict[str, str]]:
    return [
        {
            "asset_id": asset.asset_id,
            "type": asset.type,
            "name": asset.name,
            "current_price": fmt_decimal(asset.current_price),
            "current_total_fpoints": fmt_decimal(asset.current_total_fpoints),
            "previous_race_fpoints": fmt_decimal(asset.previous_race_fpoints),
            "last_race_fpoints": fmt_decimal(asset.last_race_fpoints),
        }
        for asset in assets
    ]


def price_change_for(current_price: Decimal, rolling_3: Decimal) -> tuple[Decimal, Decimal]:
    if current_price <= 0:
        raise ValueError(f"current_price must be positive, got {current_price}")
    avg_ppm = rolling_3 / Decimal("3") / current_price
    expensive = current_price > EXPENSIVE_CUTOFF
    if avg_ppm > AVG_GREAT:
        change = Decimal("0.3") if expensive else Decimal("0.6")
    elif avg_ppm >= AVG_GOOD:
        change = Decimal("0.1") if expensive else Decimal("0.2")
    elif avg_ppm >= AVG_POOR:
        change = Decimal("-0.1") if expensive else Decimal("-0.2")
    else:
        change = Decimal("-0.3") if expensive else Decimal("-0.6")
    return avg_ppm, change


def load_import_totals(path: Path, asset_type: str, assets: list[Asset]) -> dict[str, Decimal]:
    rows = read_csv(path)
    by_id = {asset.asset_id: asset for asset in assets if asset.type == asset_type}
    by_name = {normalize_name(asset.name): asset for asset in assets if asset.type == asset_type}
    totals: dict[str, Decimal] = {}
    for index, row in enumerate(rows, start=2):
        asset_id = row.get("asset_id", "").strip()
        name = row.get("name", "").strip()
        if asset_id:
            asset = by_id.get(asset_id)
            if asset is None:
                raise ValueError(f"{path} row {index}: unknown asset_id {asset_id}")
        elif name:
            asset = by_name.get(normalize_name(name))
            if asset is None:
                raise ValueError(f"{path} row {index}: unknown {asset_type} name {name!r}")
        else:
            raise ValueError(f"{path} row {index}: provide asset_id or name")

        if asset.asset_id in totals:
            raise ValueError(f"{path} row {index}: duplicate asset {asset.asset_id}")
        totals[asset.asset_id] = decimal_value(row.get("total_fpoints"), "total_fpoints")
    return totals


def compute_round(
    round_name: str,
    assets: list[Asset],
    imported_totals: dict[str, Decimal],
) -> list[RaceResult]:
    results: list[RaceResult] = []
    missing = [asset.asset_id for asset in assets if asset.asset_id not in imported_totals]
    if missing:
        raise ValueError("Missing imported totals for assets: " + ", ".join(missing))

    for asset in assets:
        new_total = imported_totals[asset.asset_id]
        race_fpoints = new_total - asset.current_total_fpoints
        rolling_3 = asset.previous_race_fpoints + asset.last_race_fpoints + race_fpoints
        avg_ppm, price_change = price_change_for(asset.current_price, rolling_3)
        results.append(
            RaceResult(
                round=round_name,
                asset=asset,
                race_fpoints=race_fpoints,
                rolling_3=rolling_3,
                avg_ppm=avg_ppm,
                price_change=price_change,
                price_after=asset.current_price + price_change,
            )
        )
    return sorted(results, key=lambda result: (result.asset.type, result.asset.name))


def race_result_rows(results: Iterable[RaceResult]) -> list[dict[str, str]]:
    return [
        {
            "round": result.round,
            "asset_id": result.asset.asset_id,
            "type": result.asset.type,
            "name": result.asset.name,
            "race_fpoints": fmt_decimal(result.race_fpoints),
            "rolling_3": fmt_decimal(result.rolling_3),
            "avg_ppm": fmt_ppm(result.avg_ppm),
            "price_change": fmt_decimal(result.price_change),
            "price_after": fmt_decimal(result.price_after),
        }
        for result in results
    ]


def updated_assets(assets: list[Asset], results: list[RaceResult]) -> list[Asset]:
    by_id = {result.asset.asset_id: result for result in results}
    updated: list[Asset] = []
    for asset in assets:
        result = by_id[asset.asset_id]
        updated.append(
            Asset(
                asset_id=asset.asset_id,
                type=asset.type,
                name=asset.name,
                current_price=result.price_after,
                current_total_fpoints=asset.current_total_fpoints + result.race_fpoints,
                previous_race_fpoints=asset.last_race_fpoints,
                last_race_fpoints=result.race_fpoints,
            )
        )
    return updated


def replace_round_scores(data_dir: Path, round_name: str, results: list[RaceResult]) -> None:
    path = data_dir / "race_scores.csv"
    existing = read_csv(path) if path.exists() else []
    kept = [row for row in existing if row.get("round") != round_name]
    write_csv(path, RACE_SCORE_COLUMNS, kept + race_result_rows(results))


def load_round_scores(data_dir: Path, round_name: str) -> dict[str, Decimal]:
    rows = read_csv(data_dir / "race_scores.csv")
    changes: dict[str, Decimal] = {}
    for row in rows:
        if row.get("round") == round_name:
            changes[row["asset_id"]] = decimal_value(row.get("price_change"), "price_change")
    return changes


def team_impact_lines(data_dir: Path, round_name: str, changes: dict[str, Decimal]) -> list[str]:
    path = data_dir / "team_state.csv"
    if not path.exists():
        return []
    rows = [row for row in read_csv(path) if row.get("round") == round_name]
    lines: list[str] = []
    for row in rows:
        team_id = row.get("team_id", "").strip() or "unknown-team"
        chip = row.get("chip", "").strip()
        is_limitless = chip.lower() == "limitless"
        lineup_field = "shadow_lineup_asset_ids" if is_limitless else "lineup_asset_ids"
        asset_ids = split_ids(row.get(lineup_field, ""))
        if is_limitless and not asset_ids:
            lines.append(
                f"{team_id}: Limitless active, but shadow_lineup_asset_ids is blank; "
                "budget impact cannot be estimated."
            )
            continue
        if not asset_ids:
            continue
        missing = [asset_id for asset_id in asset_ids if asset_id not in changes]
        if missing:
            lines.append(
                f"{team_id}: missing race score rows for lineup assets: {', '.join(missing)}"
            )
            continue
        total_change = sum((changes[asset_id] for asset_id in asset_ids), Decimal("0"))
        budget_before_raw = row.get("budget_before", "").strip()
        if budget_before_raw:
            budget_before = decimal_value(budget_before_raw, "budget_before")
            budget_after = budget_before + total_change
            lines.append(
                f"{team_id}: price lineup={lineup_field}, budget change "
                f"{fmt_decimal(total_change)}M, estimated budget after "
                f"{fmt_decimal(budget_after)}M"
            )
        else:
            lines.append(
                f"{team_id}: price lineup={lineup_field}, budget change "
                f"{fmt_decimal(total_change)}M"
            )
    return lines


def print_round_report(results: list[RaceResult], data_dir: Path | None = None) -> None:
    print("asset_id,type,name,race_fpoints,rolling_3,avg_ppm,price_change,price_after")
    for row in race_result_rows(results):
        print(
            ",".join(
                [
                    row["asset_id"],
                    row["type"],
                    row["name"],
                    row["race_fpoints"],
                    row["rolling_3"],
                    row["avg_ppm"],
                    row["price_change"],
                    row["price_after"],
                ]
            )
        )

    risers = [
        result
        for result in sorted(results, key=lambda result: result.price_change, reverse=True)
        if result.price_change > 0
    ][:5]
    fallers = [
        result
        for result in sorted(results, key=lambda result: result.price_change)
        if result.price_change < 0
    ][:5]
    print()
    print("Top price risers:")
    if risers:
        for result in risers:
            print(f"- {result.asset.name}: {fmt_decimal(result.price_change)}M")
    else:
        print("- none")
    print("Top price fallers:")
    if fallers:
        for result in fallers:
            print(f"- {result.asset.name}: {fmt_decimal(result.price_change)}M")
    else:
        print("- none")

    if data_dir is not None:
        changes = {result.asset.asset_id: result.price_change for result in results}
        lines = team_impact_lines(data_dir, results[0].round if results else "", changes)
        if lines:
            print()
            print("Team budget impact:")
            for line in lines:
                print(f"- {line}")


def cmd_init_data(args: argparse.Namespace) -> int:
    ensure_headers(args.data_dir)
    print(f"Initialized data files under {args.data_dir}")
    return 0


def cmd_update_round(args: argparse.Namespace) -> int:
    ensure_headers(args.data_dir)
    assets = load_assets(args.data_dir)
    if not assets:
        raise ValueError(
            "assets_state.csv is empty. Add initial current price, total fPoints, "
            "and previous two race scores before updating a round."
        )
    imported_totals: dict[str, Decimal] = {}
    imported_totals.update(load_import_totals(args.drivers, "driver", assets))
    imported_totals.update(load_import_totals(args.constructors, "constructor", assets))
    results = compute_round(args.round, assets, imported_totals)
    print_round_report(results, args.data_dir)
    if args.apply:
        write_csv(args.data_dir / "assets_state.csv", ASSET_COLUMNS, asset_rows(updated_assets(assets, results)))
        replace_round_scores(args.data_dir, args.round, results)
        print()
        print(f"Applied {args.round}: assets_state.csv and race_scores.csv updated.")
    else:
        print()
        print("Dry run only. Re-run with --apply to update CSV state.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    rows = [row for row in read_csv(args.data_dir / "race_scores.csv") if row.get("round") == args.round]
    if not rows:
        raise ValueError(f"No race_scores.csv rows found for round {args.round}")

    print("asset_id,type,name,race_fpoints,rolling_3,avg_ppm,price_change,price_after")
    for row in rows:
        print(
            ",".join(
                [
                    row["asset_id"],
                    row["type"],
                    row["name"],
                    row["race_fpoints"],
                    row["rolling_3"],
                    row["avg_ppm"],
                    row["price_change"],
                    row["price_after"],
                ]
            )
        )

    changes = load_round_scores(args.data_dir, args.round)
    lines = team_impact_lines(args.data_dir, args.round, changes)
    if lines:
        print()
        print("Team budget impact:")
        for line in lines:
            print(f"- {line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-data", help="Create empty data CSV files")
    init_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    init_parser.set_defaults(func=cmd_init_data)

    update_parser = subparsers.add_parser(
        "update-round", help="Compute race scores and price changes from total fPoints imports"
    )
    update_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    update_parser.add_argument("--round", required=True, help="Round name, e.g. Monaco")
    update_parser.add_argument("--drivers", type=Path, required=True, help="Driver total fPoints CSV")
    update_parser.add_argument(
        "--constructors", type=Path, required=True, help="Constructor total fPoints CSV"
    )
    update_parser.add_argument("--apply", action="store_true", help="Update assets_state.csv and race_scores.csv")
    update_parser.set_defaults(func=cmd_update_round)

    report_parser = subparsers.add_parser("report", help="Print an existing round report")
    report_parser.add_argument("--data-dir", type=Path, default=Path("data"))
    report_parser.add_argument("--round", required=True)
    report_parser.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
