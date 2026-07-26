"""Shared test helpers: script module loading and CSV fixtures."""

import csv
import importlib.util
import sys
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "skill-dev" / "f1-fantasy-advisor" / "scripts"


def load_script(name):
    """Load a script module by name, reusing an already-loaded instance.

    The scripts directory is put on sys.path first so that sibling imports
    inside the scripts (e.g. best_live_lineup importing auto_pilot_lineup)
    resolve to the same module instances the tests use.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


METRIC_COLUMNS = [
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

ROUND_COLUMNS = [
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


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def metric_row(
    asset_id,
    asset_type,
    name,
    current_price,
    last1_price,
    score,
    active="1",
    target_round_id="7",
    last1_round_id="6",
    last2_round_id="5",
    last2_price="0",
    fetched_at="2026-06-14T00:00:00Z",
):
    return {
        "target_round_id": target_round_id,
        "asset_id": asset_id,
        "type": asset_type,
        "name": name,
        "current_price": current_price,
        "last1_price": last1_price,
        "last2_price": last2_price,
        "current_total_fpoints": "0",
        "rank": "",
        "last1_round_id": last1_round_id,
        "last1_fpoints": score,
        "last1_price_change": "0",
        "last2_round_id": last2_round_id,
        "last2_fpoints": "0",
        "last2_price_change": "0",
        "rolling2_fpoints": score,
        "score_floor_big_rise": "0",
        "score_floor_small_rise": "0",
        "score_floor_avoid_big_fall": "0",
        "is_active": active,
        "fetched_at": fetched_at,
    }
