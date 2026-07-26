import csv
import importlib.util
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skill-dev"
    / "f1-fantasy-advisor"
    / "scripts"
    / "best_live_lineup.py"
)
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("best_live_lineup", SCRIPT)
best_live_lineup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = best_live_lineup
SPEC.loader.exec_module(best_live_lineup)


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


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def metric_row(asset_id, asset_type, name, live_score):
    return {
        "target_round_id": "9",
        "asset_id": asset_id,
        "type": asset_type,
        "name": name,
        "current_price": "99",
        "last1_price": "10",
        "last2_price": "9",
        "current_total_fpoints": "0",
        "rank": "",
        "last1_round_id": "8",
        "last1_fpoints": "-999",
        "last1_price_change": "0",
        "last2_round_id": "7",
        "last2_fpoints": "0",
        "last2_price_change": "0",
        "rolling2_fpoints": "0",
        "score_floor_big_rise": "0",
        "score_floor_small_rise": "0",
        "score_floor_avoid_big_fall": "0",
        "is_active": "1",
        "fetched_at": "2026-07-05T18:00:00Z",
        "live_score": live_score,
    }


class BestLiveLineupTests(unittest.TestCase):
    def write_fixture(self, root, live_round="9"):
        rows = [
            metric_row("d1", "driver", "Driver One", "50"),
            metric_row("d2", "driver", "Driver Two", "40"),
            metric_row("d3", "driver", "Driver Three", "30"),
            metric_row("d4", "driver", "Driver Four", "20"),
            metric_row("d5", "driver", "Driver Five", "10"),
            metric_row("d6", "driver", "Driver Six", "100"),
            metric_row("c1", "constructor", "Constructor One", "20"),
            metric_row("c2", "constructor", "Constructor Two", "20"),
            metric_row("c3", "constructor", "Constructor Three", "80"),
        ]
        official_dir = root / "official"
        write_csv(
            official_dir / "official_asset_metrics.csv",
            METRIC_COLUMNS,
            [{key: value for key, value in row.items() if key != "live_score"} for row in rows],
        )
        write_csv(
            official_dir / "official_round_context.csv",
            ["target_round_id", "meeting_name"],
            [{"target_round_id": "9", "meeting_name": "Fixture GP"}],
        )

        cache = root / "live.csv"
        live_rows = []
        for row in rows:
            live_rows.append(
                {
                    "asset_id": row["asset_id"],
                    "type": row["type"],
                    "name": row["name"],
                    "code": row["asset_id"].upper(),
                    "score": row["live_score"],
                    "status": "finalized",
                    "source": "https://example.test/api/live-scoring",
                    "recorded_at": "2026-07-05T20:00:00Z",
                    "race_name": "Fixture GP",
                    "round_number": live_round,
                }
            )
        write_csv(cache, best_live_lineup.live_scores.CACHE_COLUMNS, live_rows)
        return official_dir, cache

    def test_combines_last1_price_with_live_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            data = best_live_lineup.load_combined_data(official_dir, cache)

        driver_six = next(asset for asset in data.auto_assets if asset.asset_id == "d6")
        self.assertEqual(driver_six.price, Decimal("10"))
        self.assertEqual(driver_six.score, Decimal("100"))

    def test_budget_optimizer_uses_live_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            data = best_live_lineup.load_combined_data(official_dir, cache)
            lineups = best_live_lineup.auto_pilot.generate_lineups(
                list(data.auto_assets), Decimal("70"), 1
            )

        selected = {
            asset.asset_id
            for asset in lineups[0].drivers + lineups[0].constructors
        }
        self.assertIn("d6", selected)
        self.assertIn("c3", selected)
        self.assertEqual(lineups[0].final_score, Decimal("440"))

    def test_transfer_optimizer_uses_live_scores_and_penalty(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            data = best_live_lineup.load_combined_data(official_dir, cache)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            lineups = best_live_lineup.transfers.generate_best_lineups(
                list(data.transfer_assets),
                Decimal("70"),
                previous,
                free_transfers=1,
                penalty_per_extra=Decimal("10"),
                top=1,
            )

        lineup = lineups[0]
        self.assertEqual(lineup.transfer_count, 2)
        self.assertEqual(lineup.transfer_penalty, Decimal("10"))
        self.assertEqual(lineup.net_score, Decimal("430"))

    def test_rejects_mismatched_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp), live_round="10")
            with self.assertRaisesRegex(ValueError, "Round mismatch"):
                best_live_lineup.load_combined_data(official_dir, cache)


if __name__ == "__main__":
    unittest.main()
