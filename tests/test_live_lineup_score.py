import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from script_loader import METRIC_COLUMNS, load_script, metric_row, write_csv

live_lineup_score = load_script("live_lineup_score")


def asset(asset_id, asset_type, name, code, score=Decimal("0")):
    return live_lineup_score.Asset(
        asset_id=asset_id, type=asset_type, name=name, code=code, score=score
    )


class LiveLineupScoreTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            asset("d1", "driver", "Lewis Hamilton", "HAM"),
            asset("d2", "driver", "George Russell", "RUS"),
            asset("d3", "driver", "Lando Norris", "NOR"),
            asset("d4", "driver", "Isack Hadjar", "HAD"),
            asset("d5", "driver", "Kimi Antonelli", "ANT"),
            asset("d6", "driver", "Charles Leclerc", "LEC"),
            asset("c1", "constructor", "McLaren", "MCL"),
            asset("c2", "constructor", "Ferrari", "FER"),
            asset("c3", "constructor", "Mercedes", "MER"),
        ]

    def test_parses_full_table_and_simple_rows(self):
        text = """
        FINALIZED
        DR | TOT | delta | POS
        HAM | 56 | 0.3 | 9
        RUS\t28\t-0.3\t10
        NOR,23,-0.3,7
        HAD=22
        Kimi Antonelli 35
        LEC 0
        MCL | 67 | 0.3
        FER 58
        MER,39,0.3
        """

        snapshot = live_lineup_score.parse_live_text(text, self.catalog)
        scores = {item.code: item.score for item in snapshot.assets}

        self.assertEqual(snapshot.status, "finalized")
        self.assertEqual(scores["HAM"], Decimal("56"))
        self.assertEqual(scores["ANT"], Decimal("35"))
        self.assertEqual(scores["LEC"], Decimal("0"))
        self.assertEqual(scores["MCL"], Decimal("67"))

    def test_requires_enough_assets(self):
        with self.assertRaisesRegex(ValueError, "at least 5 drivers and 2 constructors"):
            live_lineup_score.parse_live_text("HAM 56\nMCL 67", self.catalog)

    def test_rejects_conflicting_duplicate_scores(self):
        text = "HAM 56\nHAM 55\nRUS 1\nNOR 1\nHAD 1\nANT 1\nMCL 1\nFER 1"
        with self.assertRaisesRegex(ValueError, "Conflicting scores for HAM"):
            live_lineup_score.parse_live_text(text, self.catalog)

    def test_cache_round_trip(self):
        text = "HAM 56\nRUS 28\nNOR 23\nHAD 22\nANT -4\nMCL 67\nFER 58"
        snapshot = live_lineup_score.parse_live_text(text, self.catalog, "provisional")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            live_lineup_score.save_snapshot(snapshot, path)
            loaded = live_lineup_score.load_snapshot(path)

        self.assertEqual(loaded.status, "provisional")
        self.assertEqual(loaded.assets, snapshot.assets)

    def test_selection_accepts_codes_names_and_numbers(self):
        text = "HAM 56\nRUS 28\nNOR 23\nHAD 22\nANT -4\nLEC 0\nMCL 67\nFER 58"
        snapshot = live_lineup_score.parse_live_text(text, self.catalog)
        drivers = [item for item in snapshot.assets if item.type == "driver"]

        selected = live_lineup_score.parse_selection(
            "ham,russell,d3,had,ant", drivers, 5, "d"
        )

        self.assertEqual([item.code for item in selected], ["HAM", "RUS", "NOR", "HAD", "ANT"])

    def test_calculates_two_x_score(self):
        text = "HAM 56\nRUS 28\nNOR 23\nHAD 22\nANT -4\nMCL 67\nFER 58"
        snapshot = live_lineup_score.parse_live_text(text, self.catalog, "finalized")
        drivers = tuple(item for item in snapshot.assets if item.type == "driver")
        constructors = tuple(item for item in snapshot.assets if item.type == "constructor")

        lineup = live_lineup_score.calculate_lineup(drivers, constructors, drivers[0])

        self.assertEqual(lineup.base_score, Decimal("250"))
        self.assertEqual(lineup.two_x_bonus, Decimal("56"))
        self.assertEqual(lineup.final_score, Decimal("306"))

    def test_two_x_driver_must_be_selected(self):
        drivers = tuple(
            asset(item.asset_id, item.type, item.name, item.code, Decimal("1"))
            for item in self.catalog[:5]
        )
        constructors = tuple(
            asset(item.asset_id, item.type, item.name, item.code, Decimal("1"))
            for item in self.catalog[6:8]
        )
        other = asset("other", "driver", "Other Driver", "OTH", Decimal("1"))

        with self.assertRaisesRegex(ValueError, "2x driver must be"):
            live_lineup_score.calculate_lineup(drivers, constructors, other)

    def test_cli_has_separate_fetch_and_interactive_modes(self):
        parser = live_lineup_score.build_parser()

        fetch_args = parser.parse_args(["--fetch"])
        interactive_args = parser.parse_args(["--interactive"])

        self.assertTrue(fetch_args.fetch)
        self.assertFalse(fetch_args.interactive)
        self.assertTrue(interactive_args.interactive)
        self.assertFalse(interactive_args.fetch)

    def test_parses_nextjs_live_html(self):
        drivers = [
            {
                "id": item.asset_id,
                "abbreviation": item.code,
                "type": "driver",
                "isActive": True,
                "price": 10,
                "totalPoints": index,
            }
            for index, item in enumerate(self.catalog[:6], start=10)
        ]
        constructors = [
            {
                "id": item.asset_id,
                "abbreviation": item.code,
                "type": "constructor",
                "isActive": True,
                "price": 20,
                "totalPoints": index,
            }
            for index, item in enumerate(self.catalog[6:], start=30)
        ]
        race = {
            "name": "Fixture Grand Prix",
            "roundNumber": 9,
            "status": {"race": {"finalized": True}},
        }
        stream = (
            '7:["$",null,{"initialDrivers":'
            + json.dumps(drivers, separators=(",", ":"))
            + ',"initialConstructors":'
            + json.dumps(constructors, separators=(",", ":"))
            + ',"initialRace":'
            + json.dumps(race, separators=(",", ":"))
            + "}]"
        )
        html = (
            "<html><script>self.__next_f.push("
            + json.dumps([1, stream], separators=(",", ":"))
            + ")</script></html>"
        )

        snapshot = live_lineup_score.parse_live_html(html, self.catalog)
        scores = {item.code: item.score for item in snapshot.assets}

        self.assertEqual(len(snapshot.assets), 9)
        self.assertEqual(snapshot.status, "finalized")
        self.assertEqual(snapshot.race_name, "Fixture Grand Prix")
        self.assertEqual(snapshot.round_number, "9")
        self.assertEqual(scores["HAM"], Decimal("10"))
        self.assertEqual(scores["MER"], Decimal("32"))

    def test_parses_hydrated_live_api(self):
        drivers = [
            {
                "abbreviation": item.code,
                "isActive": True,
                "totalPoints": index,
            }
            for index, item in enumerate(self.catalog[:6], start=20)
        ]
        constructors = [
            {
                "abbreviation": item.code,
                "isActive": True,
                "totalPoints": index,
            }
            for index, item in enumerate(self.catalog[6:], start=40)
        ]
        payload = {
            "drivers": drivers,
            "constructors": constructors,
            "race": {
                "name": "Hydrated Grand Prix",
                "roundNumber": 10,
                "status": {"race": {"finalized": True}},
            },
        }

        snapshot = live_lineup_score.parse_live_api(payload, self.catalog)
        scores = {item.code: item.score for item in snapshot.assets}

        self.assertEqual(snapshot.source, live_lineup_score.LIVE_API_URL)
        self.assertEqual(snapshot.status, "finalized")
        self.assertEqual(snapshot.race_name, "Hydrated Grand Prix")
        self.assertEqual(scores["HAM"], Decimal("20"))
        self.assertEqual(scores["MER"], Decimal("42"))

    def test_rejects_invalid_live_api_shape(self):
        with self.assertRaisesRegex(ValueError, "unexpected shape"):
            live_lineup_score.parse_live_api([], self.catalog)


class SiteCodeTests(unittest.TestCase):
    def test_load_catalog_uses_overrides_and_builtin_irregular_codes(self):
        rows = [
            metric_row("d1", "driver", "Zhou Guanyu", "99", "10", "5"),
            metric_row("d2", "driver", "Lewis Hamilton", "99", "10", "5"),
            metric_row("c1", "constructor", "Future Team", "99", "10", "5"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            official_dir = Path(tmp)
            write_csv(official_dir / "official_asset_metrics.csv", METRIC_COLUMNS, rows)
            write_csv(
                official_dir / "asset_codes.csv",
                ["asset_id", "type", "name", "code"],
                [{"asset_id": "", "type": "constructor", "name": "Future Team", "code": "FUT"}],
            )
            catalog = live_lineup_score.load_catalog(official_dir)

        codes = {item.asset_id: item.code for item in catalog}
        self.assertEqual(codes["d1"], "ZHO")
        self.assertEqual(codes["d2"], "HAM")
        self.assertEqual(codes["c1"], "FUT")

    def test_unknown_constructor_code_mentions_override_file(self):
        with self.assertRaisesRegex(ValueError, "asset_codes.csv"):
            live_lineup_score.site_code("constructor", "Mystery Racing")


class CliInputDetectionTests(unittest.TestCase):
    DRIVERS = [
        ("d1", "Lewis Hamilton", "HAM"),
        ("d2", "George Russell", "RUS"),
        ("d3", "Lando Norris", "NOR"),
        ("d4", "Isack Hadjar", "HAD"),
        ("d5", "Kimi Antonelli", "ANT"),
        ("d6", "Charles Leclerc", "LEC"),
    ]
    CONSTRUCTORS = [
        ("c1", "McLaren", "MCL"),
        ("c2", "Ferrari", "FER"),
        ("c3", "Mercedes", "MER"),
    ]

    def run_fetch_input(self, root, content, filename):
        official_dir = root / "official"
        rows = [
            metric_row(asset_id, "driver", name, "99", "10", "0")
            for asset_id, name, _ in self.DRIVERS
        ] + [
            metric_row(asset_id, "constructor", name, "99", "10", "0")
            for asset_id, name, _ in self.CONSTRUCTORS
        ]
        write_csv(official_dir / "official_asset_metrics.csv", METRIC_COLUMNS, rows)
        input_path = root / filename
        input_path.write_text(content, encoding="utf-8")
        cache = root / "live.csv"
        with redirect_stdout(io.StringIO()):
            rc = live_lineup_score.main(
                [
                    "--fetch",
                    "--input",
                    str(input_path),
                    "--official-dir",
                    str(official_dir),
                    "--cache",
                    str(cache),
                ]
            )
        self.assertEqual(rc, 0)
        return live_lineup_score.load_snapshot(cache)

    def site_payload(self):
        drivers = [
            {"abbreviation": code, "isActive": True, "totalPoints": 10}
            for _, _, code in self.DRIVERS
        ]
        constructors = [
            {"abbreviation": code, "isActive": True, "totalPoints": 20}
            for _, _, code in self.CONSTRUCTORS
        ]
        race = {
            "name": "Input GP",
            "roundNumber": 9,
            "status": {"race": {"finalized": True}},
        }
        return drivers, constructors, race

    def test_input_detects_plain_text(self):
        text = "FINALIZED\nHAM 56\nRUS 28\nNOR 23\nHAD 22\nANT -4\nMCL 67\nFER 58"
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self.run_fetch_input(Path(tmp), text, "live.txt")

        self.assertEqual(snapshot.status, "finalized")
        self.assertEqual(len(snapshot.assets), 7)

    def test_input_detects_api_json(self):
        drivers, constructors, race = self.site_payload()
        payload = {"drivers": drivers, "constructors": constructors, "race": race}
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self.run_fetch_input(Path(tmp), json.dumps(payload), "live.json")

        self.assertEqual(snapshot.race_name, "Input GP")
        self.assertEqual(len(snapshot.assets), 9)

    def test_input_detects_nextjs_html(self):
        drivers, constructors, race = self.site_payload()
        stream = (
            '7:["$",null,{"initialDrivers":'
            + json.dumps(drivers, separators=(",", ":"))
            + ',"initialConstructors":'
            + json.dumps(constructors, separators=(",", ":"))
            + ',"initialRace":'
            + json.dumps(race, separators=(",", ":"))
            + "}]"
        )
        html = (
            "<html><script>self.__next_f.push("
            + json.dumps([1, stream], separators=(",", ":"))
            + ")</script></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = self.run_fetch_input(Path(tmp), html, "live.html")

        self.assertEqual(snapshot.race_name, "Input GP")
        self.assertEqual(snapshot.round_number, "9")


if __name__ == "__main__":
    unittest.main()
