#!/usr/bin/env python3
"""Fetch public F1 Fantasy data feeds and export stable CSV snapshots."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WEB_CONFIG_URL = "https://fantasy.formula1.com/feeds/v2/apps/web_config.json"
FEEDS_V2_BASE = "https://fantasy.formula1.com/feeds/v2/"
PLAYER_STATS_URL = "https://fantasy.formula1.com/feeds/popup/playerstats_{asset_id}.json"

CURRENT_COLUMNS = [
    "asset_id",
    "type",
    "name",
    "current_price",
    "current_total_fpoints",
    "rank",
]

ASSET_STATE_COLUMNS = [
    "asset_id",
    "type",
    "name",
    "current_price",
    "current_total_fpoints",
    "previous_race_fpoints",
    "last_race_fpoints",
]

GAMEDAY_SCORE_COLUMNS = [
    "gameday_id",
    "asset_id",
    "type",
    "name",
    "race_fpoints",
    "player_value",
    "old_player_value",
    "price_change",
    "is_gameday_complete",
    "is_played",
    "is_active",
]

BREAKDOWN_COLUMNS = [
    "gameday_id",
    "asset_id",
    "type",
    "name",
    "event",
    "frequency",
    "fpoints",
]

GAMEDAY_COLUMNS = [
    "gameday_id",
    "meeting_number",
    "meeting_name",
    "meeting_location",
    "country_name",
    "circuit_official_name",
    "season",
    "session_types",
    "match_statuses",
    "is_complete",
    "first_session_start",
    "last_session_start",
]

OFFICIAL_ROUND_CONTEXT_COLUMNS = [
    "target_round_id",
    "season",
    "gameday_id",
    "meeting_name",
    "country",
    "circuit",
    "is_complete",
    "session_types",
    "first_session_start",
    "last_session_start",
    "fetched_at",
]

OFFICIAL_ASSET_METRICS_COLUMNS = [
    "target_round_id",
    "asset_id",
    "type",
    "name",
    "current_price",
    "last1_price",
    "last2_price",
    "current_total_fpoints",
    "rank",
    "last1_round_id",
    "last1_fpoints",
    "last1_price_change",
    "last2_round_id",
    "last2_fpoints",
    "last2_price_change",
    "rolling2_fpoints",
    "score_floor_big_rise",
    "score_floor_small_rise",
    "score_floor_avoid_big_fall",
    "is_active",
    "fetched_at",
]

OFFICIAL_ASSET_RANKINGS_COLUMNS = [
    "target_round_id",
    "type",
    "ranking_metric",
    "metric_rank",
    "asset_id",
    "name",
    "score_floor",
    "value_note",
]

PRICE_BIG_RISE_AVG = Decimal("1.2")
PRICE_SMALL_RISE_AVG = Decimal("0.9")
PRICE_AVOID_BIG_FALL_AVG = Decimal("0.6")
SCORE_THRESHOLD_PLACES = "0.01"
ZERO = Decimal("0")


@dataclass(frozen=True)
class PublicAsset:
    asset_id: str
    type: str
    name: str
    current_price: Decimal
    current_total_fpoints: Decimal
    rank: str


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "f1-fantasy-advisor/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}") from exc


def decimal_value(raw: object, field: str) -> Decimal:
    value = "" if raw is None else str(raw).strip()
    if value == "":
        raise ValueError(f"Missing numeric value for {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {raw!r}") from exc


def fmt_decimal(value: Decimal, places: str = "0.1") -> str:
    quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == ZERO:
        return "0"
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def fmt_score_threshold(value: Decimal) -> str:
    return fmt_decimal(value, SCORE_THRESHOLD_PLACES)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def resolve_common_statistics_url(config_feed: dict[str, Any]) -> str:
    config = config_feed.get("Data", {}).get("config", {})
    tour_id = str(config.get("tourId", "")).strip()
    endpoint = (
        config.get("statistics", {})
        .get("endPoints", {})
        .get("commonStatistics", "")
        .strip()
    )
    if not tour_id:
        raise ValueError("web_config feed did not contain Data.config.tourId")
    if not endpoint:
        raise ValueError(
            "web_config feed did not contain Data.config.statistics.endPoints.commonStatistics"
        )
    return FEEDS_V2_BASE + endpoint.replace("{tourId}", tour_id)


def fpoints_group(groups: list[dict[str, Any]], asset_type: str) -> dict[str, Any]:
    for group in groups:
        if group.get("config", {}).get("key") == "fPoints":
            return group
    raise ValueError(f"Missing fPoints group for {asset_type}")


def parse_current_assets(common_feed: dict[str, Any]) -> list[PublicAsset]:
    data = common_feed.get("Data", {})
    parsed: list[PublicAsset] = []
    for key, asset_type in (("driver", "driver"), ("constructor", "constructor")):
        group = fpoints_group(data.get(key, []), asset_type)
        for participant in group.get("participants", []):
            asset_id = str(participant.get("playerid", "")).strip()
            name = str(
                participant.get("playername")
                or participant.get("teamname")
                or ""
            ).strip()
            if not asset_id or not name:
                raise ValueError(f"{asset_type} fPoints participant missing id or name")
            parsed.append(
                PublicAsset(
                    asset_id=asset_id,
                    type=asset_type,
                    name=name,
                    current_price=decimal_value(participant.get("curvalue"), "curvalue"),
                    current_total_fpoints=decimal_value(
                        participant.get("statvalue"), "statvalue"
                    ),
                    rank=str(participant.get("rnk", "")).strip(),
                )
            )
    return parsed


def current_asset_rows(assets: Iterable[PublicAsset]) -> list[dict[str, str]]:
    return [
        {
            "asset_id": asset.asset_id,
            "type": asset.type,
            "name": asset.name,
            "current_price": fmt_decimal(asset.current_price),
            "current_total_fpoints": fmt_decimal(asset.current_total_fpoints),
            "rank": asset.rank,
        }
        for asset in assets
    ]


def asset_state_snapshot_rows(
    assets: Iterable[PublicAsset],
    gameday_score_rows: Iterable[dict[str, str]],
    complete_only: bool = True,
) -> list[dict[str, str]]:
    scores_by_asset: dict[str, list[dict[str, str]]] = {}
    for row in gameday_score_rows:
        if complete_only and row.get("is_gameday_complete", "1") != "1":
            continue
        scores_by_asset.setdefault(row["asset_id"], []).append(row)

    rows: list[dict[str, str]] = []
    for asset in assets:
        scores = sorted(
            scores_by_asset.get(asset.asset_id, []),
            key=lambda row: int(row["gameday_id"]) if row["gameday_id"].isdigit() else 0,
        )
        previous_score = scores[-2]["race_fpoints"] if len(scores) >= 2 else "0"
        last_score = scores[-1]["race_fpoints"] if scores else "0"
        rows.append(
            {
                "asset_id": asset.asset_id,
                "type": asset.type,
                "name": asset.name,
                "current_price": fmt_decimal(asset.current_price),
                "current_total_fpoints": fmt_decimal(asset.current_total_fpoints),
                "previous_race_fpoints": previous_score,
                "last_race_fpoints": last_score,
            }
        )
    return rows


def total_points(stats_wise: list[dict[str, Any]]) -> Decimal:
    for item in stats_wise:
        if str(item.get("Event", "")).strip().lower() == "total":
            return decimal_value(item.get("Value"), "StatsWise Total")
    return Decimal("0")


def parse_player_history(
    asset: PublicAsset, detail_feed: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, dict[str, str]]]:
    value = detail_feed.get("Value") or detail_feed.get("Data") or detail_feed
    score_rows: list[dict[str, str]] = []
    breakdown_rows: list[dict[str, str]] = []
    gamedays: dict[str, dict[str, str]] = {}
    completed_gamedays: dict[str, bool] = {}

    for fixture in value.get("FixtureWiseStats", []):
        gameday_id = str(fixture.get("GamedayId", "")).strip()
        sessions = fixture.get("RaceDayWise", [])
        if not gameday_id or not sessions:
            continue
        first = sessions[0]
        starts = [
            str(session.get("SessionStartDate", "")).strip()
            for session in sessions
            if str(session.get("SessionStartDate", "")).strip()
        ]
        session_types = sorted(
            {
                str(session.get("SessionType", "")).strip()
                for session in sessions
                if str(session.get("SessionType", "")).strip()
            }
        )
        match_statuses = [
            str(session.get("MatchStatus", "")).strip()
            for session in sessions
            if str(session.get("MatchStatus", "")).strip()
        ]
        is_complete = bool(match_statuses) and all(
            status == "4" for status in match_statuses
        )
        completed_gamedays[gameday_id] = is_complete
        gamedays.setdefault(
            gameday_id,
            {
                "gameday_id": gameday_id,
                "meeting_number": str(first.get("MeetingNumber", "")).strip(),
                "meeting_name": str(first.get("MeetingName", "")).strip(),
                "meeting_location": str(first.get("MeetingLocation", "")).strip(),
                "country_name": str(first.get("CountryName", "")).strip(),
                "circuit_official_name": str(
                    first.get("CircuitOfficialName", "")
                ).strip(),
                "season": str(first.get("Season", "")).strip(),
                "session_types": ";".join(session_types),
                "match_statuses": ";".join(match_statuses),
                "is_complete": "1" if is_complete else "0",
                "first_session_start": min(starts) if starts else "",
                "last_session_start": max(starts) if starts else "",
            },
        )

    gameday_items = sorted(
        [
            item
            for item in value.get("GamedayWiseStats", [])
            if str(item.get("GamedayId", "")).strip()
        ],
        key=lambda item: gameday_sort_key(str(item.get("GamedayId", "")).strip()),
    )
    for index, item in enumerate(gameday_items):
        gameday_id = str(item.get("GamedayId", "")).strip()
        player_value = decimal_value(item.get("PlayerValue"), "PlayerValue")
        old_player_value = decimal_value(item.get("OldPlayerValue"), "OldPlayerValue")
        next_player_value = (
            decimal_value(
                gameday_items[index + 1].get("PlayerValue"), "next PlayerValue"
            )
            if index + 1 < len(gameday_items)
            else asset.current_price
        )
        price_change = next_player_value - player_value
        stats_wise = item.get("StatsWise", [])
        score_rows.append(
            {
                "gameday_id": gameday_id,
                "asset_id": asset.asset_id,
                "type": asset.type,
                "name": asset.name,
                "race_fpoints": fmt_decimal(total_points(stats_wise)),
                "player_value": fmt_decimal(player_value),
                "old_player_value": fmt_decimal(old_player_value),
                "price_change": fmt_decimal(price_change),
                "is_gameday_complete": "1"
                if completed_gamedays.get(gameday_id, False)
                else "0",
                "is_played": str(item.get("IsPlayed", "")).strip(),
                "is_active": str(item.get("IsActive", "")).strip(),
            }
        )
        for stat in stats_wise:
            breakdown_rows.append(
                {
                    "gameday_id": gameday_id,
                    "asset_id": asset.asset_id,
                    "type": asset.type,
                    "name": asset.name,
                    "event": str(stat.get("Event", "")).strip(),
                    "frequency": str(stat.get("Frequency", "")).strip(),
                    "fpoints": fmt_decimal(decimal_value(stat.get("Value"), "Value")),
                }
            )

    return score_rows, breakdown_rows, gamedays


def gameday_sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)


def is_before_target_round(gameday_id: str, target_round_id: str) -> bool:
    if not target_round_id:
        return True
    if gameday_id.isdigit() and target_round_id.isdigit():
        return int(gameday_id) < int(target_round_id)
    return gameday_id != target_round_id


def resolve_target_round_id(
    gameday_rows: Iterable[dict[str, str]], requested_target_round_id: str = ""
) -> str:
    if requested_target_round_id:
        return requested_target_round_id
    sorted_rows = sorted(
        gameday_rows,
        key=lambda row: gameday_sort_key(row.get("gameday_id", "")),
    )
    incomplete_rows = [row for row in sorted_rows if row.get("is_complete") != "1"]
    if incomplete_rows:
        return incomplete_rows[0].get("gameday_id", "")
    if sorted_rows:
        return sorted_rows[-1].get("gameday_id", "")
    return ""


def official_round_context_rows(
    target_round_id: str,
    gameday_rows: dict[str, dict[str, str]],
    fetched_at: str,
) -> list[dict[str, str]]:
    gameday = gameday_rows.get(target_round_id, {})
    return [
        {
            "target_round_id": target_round_id,
            "season": gameday.get("season", ""),
            "gameday_id": gameday.get("gameday_id", ""),
            "meeting_name": gameday.get("meeting_name", ""),
            "country": gameday.get("country_name", ""),
            "circuit": gameday.get("circuit_official_name", ""),
            "is_complete": gameday.get("is_complete", ""),
            "session_types": gameday.get("session_types", ""),
            "first_session_start": gameday.get("first_session_start", ""),
            "last_session_start": gameday.get("last_session_start", ""),
            "fetched_at": fetched_at,
        }
    ]


def latest_is_active(score_rows: list[dict[str, str]]) -> str:
    if not score_rows:
        return ""
    latest = sorted(
        score_rows,
        key=lambda row: gameday_sort_key(row.get("gameday_id", "")),
    )[-1]
    return latest.get("is_active", "")


def score_floor(current_price: Decimal, rolling2_fpoints: Decimal, avg: Decimal) -> Decimal:
    return avg * Decimal("3") * current_price - rolling2_fpoints


def official_asset_metric_rows(
    assets: Iterable[PublicAsset],
    gameday_score_rows: Iterable[dict[str, str]],
    target_round_id: str,
    fetched_at: str,
) -> list[dict[str, str]]:
    scores_by_asset: dict[str, list[dict[str, str]]] = {}
    for row in gameday_score_rows:
        scores_by_asset.setdefault(row["asset_id"], []).append(row)

    rows: list[dict[str, str]] = []
    for asset in assets:
        asset_scores = scores_by_asset.get(asset.asset_id, [])
        completed_scores = [
            row
            for row in asset_scores
            if row.get("is_gameday_complete") == "1"
            and is_before_target_round(row.get("gameday_id", ""), target_round_id)
        ]
        completed_scores = sorted(
            completed_scores,
            key=lambda row: gameday_sort_key(row.get("gameday_id", "")),
            reverse=True,
        )
        last1 = completed_scores[0] if len(completed_scores) >= 1 else {}
        last2 = completed_scores[1] if len(completed_scores) >= 2 else {}
        last1_fpoints = decimal_value(last1.get("race_fpoints", "0"), "last1_fpoints")
        last2_fpoints = decimal_value(last2.get("race_fpoints", "0"), "last2_fpoints")
        last1_price = decimal_value(last1.get("player_value", "0"), "last1_price")
        last2_price = decimal_value(last2.get("player_value", "0"), "last2_price")
        last1_price_change = decimal_value(
            last1.get("price_change", "0"), "last1_price_change"
        )
        last2_price_change = decimal_value(
            last2.get("price_change", "0"), "last2_price_change"
        )
        rolling2_fpoints = last1_fpoints + last2_fpoints

        floor_big = score_floor(
            asset.current_price, rolling2_fpoints, PRICE_BIG_RISE_AVG
        )
        floor_small = score_floor(
            asset.current_price, rolling2_fpoints, PRICE_SMALL_RISE_AVG
        )
        floor_avoid_fall = score_floor(
            asset.current_price, rolling2_fpoints, PRICE_AVOID_BIG_FALL_AVG
        )

        rows.append(
            {
                "target_round_id": target_round_id,
                "asset_id": asset.asset_id,
                "type": asset.type,
                "name": asset.name,
                "current_price": fmt_decimal(asset.current_price),
                "last1_price": fmt_decimal(last1_price),
                "last2_price": fmt_decimal(last2_price),
                "current_total_fpoints": fmt_decimal(asset.current_total_fpoints),
                "rank": asset.rank,
                "last1_round_id": last1.get("gameday_id", ""),
                "last1_fpoints": fmt_decimal(last1_fpoints),
                "last1_price_change": fmt_decimal(last1_price_change),
                "last2_round_id": last2.get("gameday_id", ""),
                "last2_fpoints": fmt_decimal(last2_fpoints),
                "last2_price_change": fmt_decimal(last2_price_change),
                "rolling2_fpoints": fmt_decimal(rolling2_fpoints),
                "score_floor_big_rise": fmt_score_threshold(floor_big),
                "score_floor_small_rise": fmt_score_threshold(floor_small),
                "score_floor_avoid_big_fall": fmt_score_threshold(floor_avoid_fall),
                "is_active": latest_is_active(asset_scores),
                "fetched_at": fetched_at,
            }
        )
    return rows


def value_note_for(score_floor_value: Decimal) -> str:
    if score_floor_value < ZERO:
        return f"target score can be negative down to {fmt_score_threshold(score_floor_value)}"
    return f"target score floor {fmt_score_threshold(score_floor_value)}"


def official_asset_ranking_rows(
    metric_rows: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    by_type: dict[str, list[dict[str, str]]] = {}
    for row in metric_rows:
        by_type.setdefault(row["type"], []).append(row)

    ranking_metrics = [
        ("big_rise", "score_floor_big_rise"),
        ("small_rise", "score_floor_small_rise"),
        ("avoid_big_fall", "score_floor_avoid_big_fall"),
    ]

    for asset_type in sorted(by_type):
        for ranking_metric, floor_key in ranking_metrics:
            ranked = sorted(
                by_type[asset_type],
                key=lambda row: (decimal_value(row[floor_key], floor_key), row["name"]),
            )
            for index, metric in enumerate(ranked, start=1):
                floor_value = decimal_value(metric[floor_key], floor_key)
                rows.append(
                    {
                        "target_round_id": metric["target_round_id"],
                        "type": metric["type"],
                        "ranking_metric": ranking_metric,
                        "metric_rank": str(index),
                        "asset_id": metric["asset_id"],
                        "name": metric["name"],
                        "score_floor": metric[floor_key],
                        "value_note": value_note_for(floor_value),
                    }
                )
    return rows


def fetch_public_data(
    out_dir: Path,
    asset_ids: set[str] | None,
    skip_history: bool,
    timeout: int,
    target_round_id: str = "",
) -> tuple[int, int]:
    fetched_at = utc_timestamp()
    config_feed = fetch_json(WEB_CONFIG_URL, timeout)
    common_url = resolve_common_statistics_url(config_feed)
    common_feed = fetch_json(common_url, timeout)
    assets = parse_current_assets(common_feed)
    if asset_ids:
        assets = [asset for asset in assets if asset.asset_id in asset_ids]
        missing = sorted(asset_ids - {asset.asset_id for asset in assets})
        if missing:
            raise ValueError("Unknown asset ids in current feed: " + ", ".join(missing))

    history_count = 0
    if skip_history:
        write_csv(out_dir / "current_assets.csv", CURRENT_COLUMNS, current_asset_rows(assets))
        return len(assets), history_count

    score_rows: list[dict[str, str]] = []
    gameday_rows: dict[str, dict[str, str]] = {}
    for asset in assets:
        detail_feed = fetch_json(PLAYER_STATS_URL.format(asset_id=asset.asset_id), timeout)
        asset_scores, _, asset_gamedays = parse_player_history(asset, detail_feed)
        score_rows.extend(asset_scores)
        gameday_rows.update(asset_gamedays)
        history_count += 1

    resolved_target_round_id = resolve_target_round_id(
        gameday_rows.values(), target_round_id
    )
    metric_rows = official_asset_metric_rows(
        assets, score_rows, resolved_target_round_id, fetched_at
    )
    write_csv(
        out_dir / "official_round_context.csv",
        OFFICIAL_ROUND_CONTEXT_COLUMNS,
        official_round_context_rows(resolved_target_round_id, gameday_rows, fetched_at),
    )
    write_csv(
        out_dir / "official_asset_metrics.csv",
        OFFICIAL_ASSET_METRICS_COLUMNS,
        metric_rows,
    )
    write_csv(
        out_dir / "official_asset_rankings.csv",
        OFFICIAL_ASSET_RANKINGS_COLUMNS,
        official_asset_ranking_rows(metric_rows),
    )

    return len(assets), history_count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/official"),
        help="Directory for exported CSV snapshots",
    )
    parser.add_argument(
        "--asset-id",
        action="append",
        default=[],
        help="Fetch only selected asset id; may be repeated",
    )
    parser.add_argument(
        "--skip-history",
        action="store_true",
        help="Only export current fPoints and prices",
    )
    parser.add_argument(
        "--target-round-id",
        default="",
        help="Gameday id to use as the target race week; defaults to next incomplete gameday",
    )
    parser.add_argument("--timeout", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        asset_count, history_count = fetch_public_data(
            args.out_dir,
            set(args.asset_id) if args.asset_id else None,
            args.skip_history,
            args.timeout,
            args.target_round_id,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.skip_history:
        print(f"Wrote current_assets.csv for {asset_count} assets under {args.out_dir}")
        print("Skipped player history feeds.")
    else:
        print(f"Wrote official fantasy CSVs for {asset_count} assets under {args.out_dir}")
        print(f"Fetched player history for {history_count} assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
