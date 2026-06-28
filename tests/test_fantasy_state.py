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
    / "fantasy_state.py"
)
SPEC = importlib.util.spec_from_file_location("fantasy_state", SCRIPT)
fantasy_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = fantasy_state
SPEC.loader.exec_module(fantasy_state)


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class FantasyStateTests(unittest.TestCase):
    def test_price_change_tiers(self):
        cases = [
            ("20.0", "73", "0.3"),
            ("20.0", "60", "0.1"),
            ("20.0", "48", "-0.1"),
            ("20.0", "30", "-0.3"),
            ("10.0", "37", "0.6"),
            ("10.0", "30", "0.2"),
            ("10.0", "24", "-0.2"),
            ("10.0", "10", "-0.6"),
        ]
        for price, rolling_3, expected_change in cases:
            with self.subTest(price=price, rolling_3=rolling_3):
                _, change = fantasy_state.price_change_for(
                    Decimal(price), Decimal(rolling_3)
                )
                self.assertEqual(change, Decimal(expected_change))

    def test_driver_price_change_is_clamped_at_minimum_price(self):
        cases = [
            ("3.0", "0", "0.0"),
            ("3.3", "0", "-0.3"),
        ]
        for price, rolling_3, expected_change in cases:
            with self.subTest(price=price, rolling_3=rolling_3):
                _, change = fantasy_state.price_change_for(
                    Decimal(price), Decimal(rolling_3), "driver"
                )
                self.assertEqual(change, Decimal(expected_change))

    def test_constructor_price_change_is_not_clamped_by_driver_minimum(self):
        _, change = fantasy_state.price_change_for(
            Decimal("3.0"), Decimal("0"), "constructor"
        )
        self.assertEqual(change, Decimal("-0.6"))

    def test_update_round_handles_negative_score_and_updates_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            fantasy_state.ensure_headers(data_dir)
            write_csv(
                data_dir / "assets_state.csv",
                fantasy_state.ASSET_COLUMNS,
                [
                    {
                        "asset_id": "drv_exp",
                        "type": "driver",
                        "name": "Expensive Driver",
                        "current_price": "20.0",
                        "current_total_fpoints": "100",
                        "previous_race_fpoints": "30",
                        "last_race_fpoints": "30",
                    },
                    {
                        "asset_id": "drv_cheap",
                        "type": "driver",
                        "name": "Cheap Driver",
                        "current_price": "10.0",
                        "current_total_fpoints": "50",
                        "previous_race_fpoints": "10",
                        "last_race_fpoints": "15",
                    },
                    {
                        "asset_id": "con_exp",
                        "type": "constructor",
                        "name": "Fast Constructor",
                        "current_price": "25.0",
                        "current_total_fpoints": "200",
                        "previous_race_fpoints": "20",
                        "last_race_fpoints": "20",
                    },
                ],
            )
            write_csv(
                data_dir / "imports" / "round_drivers.csv",
                ["asset_id", "total_fpoints"],
                [
                    {"asset_id": "drv_exp", "total_fpoints": "95"},
                    {"asset_id": "drv_cheap", "total_fpoints": "64"},
                ],
            )
            write_csv(
                data_dir / "imports" / "round_constructors.csv",
                ["asset_id", "total_fpoints"],
                [{"asset_id": "con_exp", "total_fpoints": "230"}],
            )

            rc = fantasy_state.main(
                [
                    "update-round",
                    "--data-dir",
                    str(data_dir),
                    "--round",
                    "Fixture",
                    "--drivers",
                    str(data_dir / "imports" / "round_drivers.csv"),
                    "--constructors",
                    str(data_dir / "imports" / "round_constructors.csv"),
                    "--apply",
                ]
            )
            self.assertEqual(rc, 0)

            assets = {row["asset_id"]: row for row in fantasy_state.read_csv(data_dir / "assets_state.csv")}
            self.assertEqual(assets["drv_exp"]["current_total_fpoints"], "95")
            self.assertEqual(assets["drv_exp"]["previous_race_fpoints"], "30")
            self.assertEqual(assets["drv_exp"]["last_race_fpoints"], "-5")
            self.assertEqual(assets["drv_exp"]["current_price"], "20.1")

            scores = {row["asset_id"]: row for row in fantasy_state.read_csv(data_dir / "race_scores.csv")}
            self.assertEqual(scores["drv_exp"]["race_fpoints"], "-5")
            self.assertEqual(scores["drv_exp"]["rolling_3"], "55")
            self.assertEqual(scores["drv_exp"]["price_change"], "0.1")
            self.assertEqual(scores["drv_cheap"]["price_change"], "0.6")

    def test_limitless_uses_shadow_lineup_for_budget_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            fantasy_state.ensure_headers(data_dir)
            write_csv(
                data_dir / "race_scores.csv",
                fantasy_state.RACE_SCORE_COLUMNS,
                [
                    {
                        "round": "Fixture",
                        "asset_id": "limitless_a",
                        "type": "driver",
                        "name": "Limitless A",
                        "race_fpoints": "30",
                        "rolling_3": "80",
                        "avg_ppm": "1.333",
                        "price_change": "0.3",
                        "price_after": "20.3",
                    },
                    {
                        "round": "Fixture",
                        "asset_id": "limitless_b",
                        "type": "driver",
                        "name": "Limitless B",
                        "race_fpoints": "30",
                        "rolling_3": "80",
                        "avg_ppm": "1.333",
                        "price_change": "0.6",
                        "price_after": "10.6",
                    },
                    {
                        "round": "Fixture",
                        "asset_id": "shadow_a",
                        "type": "constructor",
                        "name": "Shadow A",
                        "race_fpoints": "10",
                        "rolling_3": "40",
                        "avg_ppm": "0.533",
                        "price_change": "-0.3",
                        "price_after": "24.7",
                    },
                ],
            )
            write_csv(
                data_dir / "team_state.csv",
                fantasy_state.TEAM_COLUMNS,
                [
                    {
                        "round": "Fixture",
                        "team_id": "Team3",
                        "budget_before": "100.0",
                        "budget_after": "",
                        "total_fpoints": "",
                        "transfer_penalty": "0",
                        "chip": "Limitless",
                        "lineup_asset_ids": "limitless_a,limitless_b",
                        "boost_asset_id": "limitless_a",
                        "shadow_lineup_asset_ids": "shadow_a",
                        "notes": "",
                    }
                ],
            )

            changes = fantasy_state.load_round_scores(data_dir, "Fixture")
            lines = fantasy_state.team_impact_lines(data_dir, "Fixture", changes)
            self.assertEqual(len(lines), 1)
            self.assertIn("shadow_lineup_asset_ids", lines[0])
            self.assertIn("budget change -0.3M", lines[0])
            self.assertIn("estimated budget after 99.7M", lines[0])

    def test_record_team_replaces_round_team_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            fantasy_state.ensure_headers(data_dir)

            rc = fantasy_state.main(
                [
                    "record-team",
                    "--data-dir",
                    str(data_dir),
                    "--round",
                    "Spain",
                    "--team-id",
                    "Team1",
                    "--lineup",
                    "drv1,drv2,drv3,drv4,drv5,con1,con2",
                    "--boost-asset-id",
                    "drv1",
                    "--budget-before",
                    "4.7",
                    "--transfer-penalty",
                    "-10",
                    "--chip",
                    "No Negative",
                    "--notes",
                    "initial record",
                ]
            )
            self.assertEqual(rc, 0)

            rc = fantasy_state.main(
                [
                    "record-team",
                    "--data-dir",
                    str(data_dir),
                    "--round",
                    "Spain",
                    "--team-id",
                    "Team1",
                    "--lineup",
                    "drv1,drv2,drv3,drv4,drv5,con1,con2",
                    "--boost-asset-id",
                    "drv2",
                    "--budget-before",
                    "5.1",
                ]
            )
            self.assertEqual(rc, 0)

            rows = fantasy_state.read_csv(data_dir / "team_state.csv")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["round"], "Spain")
            self.assertEqual(rows[0]["team_id"], "Team1")
            self.assertEqual(rows[0]["budget_before"], "5.1")
            self.assertEqual(rows[0]["boost_asset_id"], "drv2")
            self.assertEqual(rows[0]["transfer_penalty"], "0")


if __name__ == "__main__":
    unittest.main()
