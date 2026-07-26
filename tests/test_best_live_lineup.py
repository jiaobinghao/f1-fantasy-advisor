import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from script_loader import METRIC_COLUMNS, load_script, write_csv
from script_loader import metric_row as base_metric_row

best_live_lineup = load_script("best_live_lineup")


def metric_row(asset_id, asset_type, name, live_score):
    row = base_metric_row(
        asset_id,
        asset_type,
        name,
        "99",
        "10",
        "-999",
        target_round_id="9",
        last1_round_id="8",
        last2_round_id="7",
        last2_price="9",
        fetched_at="2026-07-05T18:00:00Z",
    )
    row["rolling2_fpoints"] = "0"
    row["live_score"] = live_score
    return row


class BestLiveLineupTests(unittest.TestCase):
    def write_fixture(self, root, live_round="9", live_name="Fixture GP", status="finalized"):
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
                    "status": status,
                    "source": "https://example.test/api/live-scoring",
                    "recorded_at": "2026-07-05T20:00:00Z",
                    "race_name": live_name,
                    "round_number": live_round,
                }
            )
        write_csv(cache, best_live_lineup.live_scores.CACHE_COLUMNS, live_rows)
        return official_dir, cache

    def test_combines_last1_price_with_live_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            data = best_live_lineup.load_combined_data(official_dir, cache)

        driver_six = next(asset for asset in data.assets if asset.asset_id == "d6")
        self.assertEqual(driver_six.price, Decimal("10"))
        self.assertEqual(driver_six.score, Decimal("100"))

    def test_budget_optimizer_uses_live_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            data = best_live_lineup.load_combined_data(official_dir, cache)
            lineups = best_live_lineup.generate_lineups(
                list(data.assets), Decimal("70"), 1
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
                list(data.assets),
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

    def test_rejects_mismatched_race_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(
                Path(tmp), live_round="9", live_name="Other GP"
            )
            with self.assertRaisesRegex(ValueError, "Race mismatch"):
                best_live_lineup.load_combined_data(official_dir, cache)

    def test_same_race_with_different_round_ids_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp), live_round="10")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                data = best_live_lineup.load_combined_data(official_dir, cache)

        self.assertEqual(len(data.assets), 9)
        self.assertIn("round ids differ", stderr.getvalue())

    def test_rejects_mismatched_rounds_when_names_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(
                Path(tmp), live_round="10", live_name=""
            )
            with self.assertRaisesRegex(ValueError, "Round mismatch"):
                best_live_lineup.load_combined_data(official_dir, cache)

    def test_cli_budget_mode_labels_provisional_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp), status="provisional")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = best_live_lineup.main(
                    [
                        "budget",
                        "70",
                        "--official-dir",
                        str(official_dir),
                        "--cache",
                        str(cache),
                    ]
                )

        output = stdout.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("status: PROVISIONAL", output)
        self.assertIn("Live scores are provisional", output)

    def test_cli_transfers_mode_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir, cache = self.write_fixture(Path(tmp))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = best_live_lineup.main(
                    [
                        "transfers",
                        "70",
                        "--previous-lineup",
                        "d1,d2,d3,d4,d5,c1,c2",
                        "--official-dir",
                        str(official_dir),
                        "--cache",
                        str(cache),
                    ]
                )

        self.assertEqual(rc, 0)
        self.assertIn("net score after transfers", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
