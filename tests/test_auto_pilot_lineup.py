import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from script_loader import (
    METRIC_COLUMNS,
    ROUND_COLUMNS,
    load_script,
    metric_row,
    write_csv,
)

auto_pilot_lineup = load_script("auto_pilot_lineup")


class AutoPilotLineupTests(unittest.TestCase):
    def write_fixture(self, official_dir):
        rows = [
            metric_row("d1", "driver", "Driver One", "99", "10", "50"),
            metric_row("d2", "driver", "Driver Two", "99", "11", "40"),
            metric_row("d3", "driver", "Driver Three", "99", "12", "30"),
            metric_row("d4", "driver", "Driver Four", "99", "13", "20"),
            metric_row("d5", "driver", "Driver Five", "99", "14", "10"),
            metric_row("d6", "driver", "Inactive Driver", "1", "1", "100", "0"),
            metric_row("c1", "constructor", "Constructor One", "99", "20", "60"),
            metric_row("c2", "constructor", "Constructor Two", "99", "21", "25"),
            metric_row("c3", "constructor", "Inactive Constructor", "1", "1", "100", "0"),
        ]
        write_csv(official_dir / "official_asset_metrics.csv", METRIC_COLUMNS, rows)
        write_csv(
            official_dir / "official_round_context.csv",
            ROUND_COLUMNS,
            [
                {
                    "target_round_id": "7",
                    "season": "2026",
                    "gameday_id": "7",
                    "meeting_name": "Fixture GP",
                    "country": "Testland",
                    "circuit": "Test Circuit",
                    "is_complete": "0",
                    "session_types": "Qualifying;Race",
                    "first_session_start": "",
                    "last_session_start": "",
                    "fetched_at": "2026-06-14T00:00:00Z",
                }
            ],
        )

    def test_generates_valid_lineup_from_last1_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = auto_pilot_lineup.load_assets(official_dir)
            lineups = auto_pilot_lineup.generate_lineups(assets, Decimal("101"), 5)

            self.assertEqual(len(lineups), 1)
            lineup = lineups[0]
            self.assertEqual(len(lineup.drivers), 5)
            self.assertEqual(len(lineup.constructors), 2)
            self.assertEqual(lineup.price, Decimal("101"))
            self.assertLessEqual(lineup.price, Decimal("101"))
            self.assertEqual(lineup.base_score, Decimal("235"))
            self.assertEqual(lineup.two_x_driver.asset_id, "d1")
            self.assertEqual(lineup.two_x_bonus, Decimal("50"))
            self.assertEqual(lineup.final_score, Decimal("285"))

    def test_inactive_assets_are_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = auto_pilot_lineup.load_assets(official_dir)
            lineups = auto_pilot_lineup.generate_lineups(assets, Decimal("101"), 1)
            selected_ids = {
                asset.asset_id
                for asset in lineups[0].drivers + lineups[0].constructors
            }

            self.assertNotIn("d6", selected_ids)
            self.assertNotIn("c3", selected_ids)

    def test_budget_too_low_has_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = auto_pilot_lineup.load_assets(official_dir)
            with self.assertRaisesRegex(ValueError, "No valid lineup fits budget 100M"):
                auto_pilot_lineup.generate_lineups(assets, Decimal("100"), 5)


if __name__ == "__main__":
    unittest.main()
