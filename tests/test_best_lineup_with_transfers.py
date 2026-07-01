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
    / "best_lineup_with_transfers.py"
)
SPEC = importlib.util.spec_from_file_location("best_lineup_with_transfers", SCRIPT)
best_lineup_with_transfers = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = best_lineup_with_transfers
SPEC.loader.exec_module(best_lineup_with_transfers)


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


def metric_row(asset_id, asset_type, name, current_price, last1_price, score, active="1"):
    return {
        "target_round_id": "8",
        "asset_id": asset_id,
        "type": asset_type,
        "name": name,
        "current_price": current_price,
        "last1_price": last1_price,
        "last2_price": "0",
        "current_total_fpoints": "0",
        "rank": "",
        "last1_round_id": "7",
        "last1_fpoints": score,
        "last1_price_change": "0",
        "last2_round_id": "6",
        "last2_fpoints": "0",
        "last2_price_change": "0",
        "rolling2_fpoints": score,
        "score_floor_big_rise": "0",
        "score_floor_small_rise": "0",
        "score_floor_avoid_big_fall": "0",
        "is_active": active,
        "fetched_at": "2026-06-27T00:00:00Z",
    }


class BestLineupWithTransfersTests(unittest.TestCase):
    def write_fixture(self, official_dir):
        rows = [
            metric_row("d1", "driver", "Driver One", "99", "10", "50"),
            metric_row("d2", "driver", "Driver Two", "99", "10", "40"),
            metric_row("d3", "driver", "Driver Three", "99", "10", "30"),
            metric_row("d4", "driver", "Driver Four", "99", "10", "20"),
            metric_row("d5", "driver", "Driver Five", "99", "10", "10"),
            metric_row("d6", "driver", "Driver Six", "99", "10", "100"),
            metric_row("d7", "driver", "Inactive Driver", "1", "1", "200", "0"),
            metric_row("c1", "constructor", "Constructor One", "99", "10", "20"),
            metric_row("c2", "constructor", "Constructor Two", "99", "10", "20"),
            metric_row("c3", "constructor", "Constructor Three", "99", "10", "80"),
            metric_row("c4", "constructor", "Inactive Constructor", "1", "1", "200", "0"),
        ]
        write_csv(official_dir / "official_asset_metrics.csv", METRIC_COLUMNS, rows)

    def test_selects_best_net_score_after_transfer_penalty(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = best_lineup_with_transfers.load_assets(official_dir)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            lineups = best_lineup_with_transfers.generate_best_lineups(
                assets,
                Decimal("70"),
                previous,
                free_transfers=1,
                penalty_per_extra=Decimal("10"),
                top=1,
            )

            lineup = lineups[0]
            selected_ids = {
                asset.asset_id for asset in lineup.drivers + lineup.constructors
            }
            self.assertIn("d6", selected_ids)
            self.assertIn("c3", selected_ids)
            self.assertEqual(lineup.price, Decimal("70"))
            self.assertEqual(lineup.base_score, Decimal("340"))
            self.assertEqual(lineup.two_x_driver.asset_id, "d6")
            self.assertEqual(lineup.two_x_bonus, Decimal("100"))
            self.assertEqual(lineup.gross_score, Decimal("440"))
            self.assertEqual(lineup.transfer_count, 2)
            self.assertEqual(lineup.extra_transfers, 1)
            self.assertEqual(lineup.transfer_penalty, Decimal("10"))
            self.assertEqual(lineup.net_score, Decimal("430"))

    def test_large_penalty_can_keep_previous_lineup_best(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = best_lineup_with_transfers.load_assets(official_dir)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            lineups = best_lineup_with_transfers.generate_best_lineups(
                assets,
                Decimal("70"),
                previous,
                free_transfers=0,
                penalty_per_extra=Decimal("150"),
                top=1,
            )

            lineup = lineups[0]
            selected_ids = {
                asset.asset_id for asset in lineup.drivers + lineup.constructors
            }
            self.assertEqual(selected_ids, set(previous))
            self.assertEqual(lineup.transfer_count, 0)
            self.assertEqual(lineup.transfer_penalty, Decimal("0"))
            self.assertEqual(lineup.net_score, Decimal("240"))

    def test_inactive_assets_are_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = best_lineup_with_transfers.load_assets(official_dir)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            lineups = best_lineup_with_transfers.generate_best_lineups(
                assets,
                Decimal("70"),
                previous,
                free_transfers=2,
                penalty_per_extra=Decimal("10"),
                top=1,
            )
            selected_ids = {
                asset.asset_id for asset in lineups[0].drivers + lineups[0].constructors
            }

            self.assertNotIn("d7", selected_ids)
            self.assertNotIn("c4", selected_ids)

    def test_previous_lineup_validation(self):
        with self.assertRaisesRegex(ValueError, "exactly 7 asset ids"):
            best_lineup_with_transfers.validate_previous_lineup("d1,d2")
        with self.assertRaisesRegex(ValueError, "duplicate asset ids"):
            best_lineup_with_transfers.validate_previous_lineup(
                "d1,d1,d2,d3,d4,c1,c2"
            )

    def test_parse_asset_selection_accepts_number_id_name_and_abbreviation(self):
        candidates = [
            best_lineup_with_transfers.Asset(
                "11161", "driver", "Kimi Antonelli", Decimal("25"), Decimal("10"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "110", "driver", "Lewis Hamilton", Decimal("24"), Decimal("20"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "124", "driver", "George Russell", Decimal("28"), Decimal("30"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "131", "driver", "Max Verstappen", Decimal("28"), Decimal("40"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "115", "driver", "Charles Leclerc", Decimal("24"), Decimal("50"), "7"
            ),
        ]

        selected = best_lineup_with_transfers.parse_asset_selection(
            "1,ham,rus,131,lec", candidates, 5, "driver"
        )

        self.assertEqual(
            [asset.asset_id for asset in selected],
            ["11161", "110", "124", "131", "115"],
        )

    def test_parse_asset_selection_rejects_ambiguous_short_name(self):
        candidates = [
            best_lineup_with_transfers.Asset(
                "1", "driver", "Carlos Sainz", Decimal("12"), Decimal("10"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "2", "driver", "Charles Leclerc", Decimal("24"), Decimal("20"), "7"
            ),
        ]

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            best_lineup_with_transfers.parse_asset_selection("c", candidates, 1, "driver")

    def test_budget_from_remaining_bank_uses_previous_lineup_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = best_lineup_with_transfers.load_assets(official_dir)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            budget = best_lineup_with_transfers.budget_from_remaining_bank(
                assets, previous, Decimal("2.5")
            )

            self.assertEqual(budget, Decimal("72.5"))

    def test_parse_exclusion_selection_accepts_prefixed_numbers_and_names(self):
        drivers = [
            best_lineup_with_transfers.Asset(
                "d1", "driver", "Kimi Antonelli", Decimal("25"), Decimal("10"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "d2", "driver", "Lewis Hamilton", Decimal("24"), Decimal("20"), "7"
            ),
        ]
        constructors = [
            best_lineup_with_transfers.Asset(
                "c1", "constructor", "Ferrari", Decimal("25"), Decimal("30"), "7"
            ),
            best_lineup_with_transfers.Asset(
                "c2", "constructor", "Mercedes", Decimal("31"), Decimal("40"), "7"
            ),
        ]

        excluded = best_lineup_with_transfers.parse_exclusion_selection(
            "d1,mercedes,ham", drivers, constructors
        )

        self.assertEqual(
            [asset.asset_id for asset in excluded],
            ["d1", "c2", "d2"],
        )

    def test_excluded_assets_are_not_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            self.write_fixture(official_dir)

            assets = best_lineup_with_transfers.load_assets(official_dir)
            previous = ("d1", "d2", "d3", "d4", "d5", "c1", "c2")
            available_assets = [asset for asset in assets if asset.asset_id != "d6"]
            lineups = best_lineup_with_transfers.generate_best_lineups(
                available_assets,
                Decimal("70"),
                previous,
                free_transfers=2,
                penalty_per_extra=Decimal("10"),
                top=1,
            )
            selected_ids = {
                asset.asset_id for asset in lineups[0].drivers + lineups[0].constructors
            }

            self.assertNotIn("d6", selected_ids)


if __name__ == "__main__":
    unittest.main()
