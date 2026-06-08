import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skill-dev"
    / "f1-fantasy-advisor"
    / "scripts"
    / "fetch_fantasy_public.py"
)
SPEC = importlib.util.spec_from_file_location("fetch_fantasy_public", SCRIPT)
fetch_public = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = fetch_public
SPEC.loader.exec_module(fetch_public)


class FetchFantasyPublicTests(unittest.TestCase):
    def test_resolves_common_statistics_url(self):
        feed = {
            "Data": {
                "config": {
                    "tourId": 4,
                    "statistics": {
                        "endPoints": {
                            "commonStatistics": "statistics/driverconstructors_{tourId}.json"
                        }
                    },
                }
            }
        }
        self.assertEqual(
            fetch_public.resolve_common_statistics_url(feed),
            "https://fantasy.formula1.com/feeds/v2/statistics/driverconstructors_4.json",
        )

    def test_parses_current_assets_from_fpoints_groups(self):
        feed = {
            "Data": {
                "driver": [
                    {"config": {"key": "other"}, "participants": []},
                    {
                        "config": {"key": "fPoints"},
                        "participants": [
                            {
                                "playerid": "11161",
                                "playername": "Kimi Antonelli",
                                "curvalue": 24.7,
                                "statvalue": 264,
                                "rnk": 1,
                            }
                        ],
                    },
                ],
                "constructor": [
                    {
                        "config": {"key": "fPoints"},
                        "participants": [
                            {
                                "playerid": "28",
                                "teamname": "Mercedes",
                                "curvalue": 30.8,
                                "statvalue": 508,
                                "rnk": 1,
                            }
                        ],
                    }
                ],
            }
        }
        rows = fetch_public.current_asset_rows(fetch_public.parse_current_assets(feed))
        self.assertEqual(
            rows,
            [
                {
                    "asset_id": "11161",
                    "type": "driver",
                    "name": "Kimi Antonelli",
                    "current_price": "24.7",
                    "current_total_fpoints": "264",
                    "rank": "1",
                },
                {
                    "asset_id": "28",
                    "type": "constructor",
                    "name": "Mercedes",
                    "current_price": "30.8",
                    "current_total_fpoints": "508",
                    "rank": "1",
                },
            ],
        )

    def test_parses_gameday_history_and_price_change(self):
        asset = fetch_public.PublicAsset(
            asset_id="11161",
            type="driver",
            name="Kimi Antonelli",
            current_price=fetch_public.Decimal("24.7"),
            current_total_fpoints=fetch_public.Decimal("264"),
            rank="1",
        )
        feed = {
            "Value": {
                "FixtureWiseStats": [
                    {
                        "GamedayId": 6,
                        "RaceDayWise": [
                            {
                                "MeetingNumber": 6,
                                "MeetingName": "Monaco Grand Prix",
                                "MeetingLocation": "Monte Carlo",
                                "CountryName": "Monaco",
                                "CircuitOfficialName": "Circuit de Monaco",
                                "Season": "2026",
                                "SessionType": "Qualifying",
                                "MatchStatus": "4",
                                "SessionStartDate": "2026-06-06T16:00:00+02:00",
                            },
                            {
                                "SessionType": "Race",
                                "MatchStatus": "4",
                                "SessionStartDate": "2026-06-07T15:00:00+02:00",
                            },
                        ],
                    }
                ],
                "GamedayWiseStats": [
                    {
                        "GamedayId": 6,
                        "PlayerValue": 24.4,
                        "OldPlayerValue": 24.4,
                        "IsPlayed": 1,
                        "IsActive": 1,
                        "StatsWise": [
                            {"Frequency": "-", "Event": "Total", "Value": 10},
                            {"Frequency": "1st", "Event": "Qualifying Position", "Value": 10},
                        ],
                    }
                ],
            }
        }
        scores, breakdown, gamedays = fetch_public.parse_player_history(asset, feed)
        self.assertEqual(scores[0]["race_fpoints"], "10")
        self.assertEqual(scores[0]["player_value"], "24.4")
        self.assertEqual(scores[0]["old_player_value"], "24.4")
        self.assertEqual(scores[0]["price_change"], "0.3")
        self.assertEqual(scores[0]["is_gameday_complete"], "1")
        self.assertEqual(breakdown[1]["event"], "Qualifying Position")
        self.assertEqual(gamedays["6"]["meeting_name"], "Monaco Grand Prix")
        self.assertEqual(gamedays["6"]["session_types"], "Qualifying;Race")
        self.assertEqual(gamedays["6"]["is_complete"], "1")

    def test_price_change_uses_next_visible_price(self):
        asset = fetch_public.PublicAsset(
            asset_id="111",
            type="driver",
            name="Nico Hulkenberg",
            current_price=fetch_public.Decimal("3.5"),
            current_total_fpoints=fetch_public.Decimal("-28"),
            rank="21",
        )
        feed = {
            "Value": {
                "GamedayWiseStats": [
                    {
                        "GamedayId": 6,
                        "PlayerValue": 3.8,
                        "OldPlayerValue": 4.1,
                        "IsPlayed": 1,
                        "IsActive": 1,
                        "StatsWise": [{"Frequency": "-", "Event": "Total", "Value": 3}],
                    },
                    {
                        "GamedayId": 5,
                        "PlayerValue": 4.4,
                        "OldPlayerValue": 4.4,
                        "IsPlayed": 1,
                        "IsActive": 1,
                        "StatsWise": [{"Frequency": "-", "Event": "Total", "Value": 1}],
                    },
                ],
            }
        }
        scores, _, _ = fetch_public.parse_player_history(asset, feed)

        self.assertEqual([row["gameday_id"] for row in scores], ["5", "6"])
        self.assertEqual(scores[0]["price_change"], "-0.6")
        self.assertEqual(scores[1]["price_change"], "-0.3")

    def test_marks_partial_gameday_incomplete(self):
        asset = fetch_public.PublicAsset(
            asset_id="11161",
            type="driver",
            name="Kimi Antonelli",
            current_price=fetch_public.Decimal("24.7"),
            current_total_fpoints=fetch_public.Decimal("264"),
            rank="1",
        )
        feed = {
            "Value": {
                "FixtureWiseStats": [
                    {
                        "GamedayId": 6,
                        "RaceDayWise": [
                            {"SessionType": "Qualifying", "MatchStatus": "5"},
                            {"SessionType": "Race", "MatchStatus": "1"},
                        ],
                    }
                ],
                "GamedayWiseStats": [
                    {
                        "GamedayId": 6,
                        "PlayerValue": 24.7,
                        "OldPlayerValue": 24.4,
                        "IsPlayed": 1,
                        "IsActive": 1,
                        "StatsWise": [{"Frequency": "-", "Event": "Total", "Value": 10}],
                    }
                ],
            }
        }
        scores, _, gamedays = fetch_public.parse_player_history(asset, feed)
        self.assertEqual(scores[0]["is_gameday_complete"], "0")
        self.assertEqual(gamedays["6"]["match_statuses"], "5;1")
        self.assertEqual(gamedays["6"]["is_complete"], "0")

    def test_builds_assets_state_snapshot_from_latest_two_scores(self):
        assets = [
            fetch_public.PublicAsset(
                asset_id="11161",
                type="driver",
                name="Kimi Antonelli",
                current_price=fetch_public.Decimal("24.7"),
                current_total_fpoints=fetch_public.Decimal("264"),
                rank="1",
            )
        ]
        rows = fetch_public.asset_state_snapshot_rows(
            assets,
            [
                {
                    "gameday_id": "4",
                    "asset_id": "11161",
                    "race_fpoints": "42",
                    "is_gameday_complete": "1",
                },
                {
                    "gameday_id": "6",
                    "asset_id": "11161",
                    "race_fpoints": "10",
                    "is_gameday_complete": "0",
                },
                {
                    "gameday_id": "5",
                    "asset_id": "11161",
                    "race_fpoints": "62",
                    "is_gameday_complete": "1",
                },
            ],
        )
        self.assertEqual(
            rows[0],
            {
                "asset_id": "11161",
                "type": "driver",
                "name": "Kimi Antonelli",
                "current_price": "24.7",
                "current_total_fpoints": "264",
                "previous_race_fpoints": "42",
                "last_race_fpoints": "62",
            },
        )

    def test_builds_official_metrics_with_price_zone_floors(self):
        assets = [
            fetch_public.PublicAsset(
                asset_id="drv",
                type="driver",
                name="Driver",
                current_price=fetch_public.Decimal("10.0"),
                current_total_fpoints=fetch_public.Decimal("200"),
                rank="1",
            )
        ]
        rows = fetch_public.official_asset_metric_rows(
            assets,
            [
                {
                    "gameday_id": "4",
                    "asset_id": "drv",
                    "race_fpoints": "28",
                    "player_value": "9.8",
                    "price_change": "0.6",
                    "is_gameday_complete": "1",
                    "is_active": "1",
                },
                {
                    "gameday_id": "5",
                    "asset_id": "drv",
                    "race_fpoints": "35",
                    "player_value": "10.0",
                    "price_change": "0.2",
                    "is_gameday_complete": "1",
                    "is_active": "1",
                },
                {
                    "gameday_id": "6",
                    "asset_id": "drv",
                    "race_fpoints": "-28",
                    "player_value": "10.0",
                    "price_change": "0",
                    "is_gameday_complete": "0",
                    "is_active": "1",
                },
            ],
            "6",
            "2026-06-08T00:00:00Z",
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(
            list(row.keys())[:7],
            [
                "target_round_id",
                "asset_id",
                "type",
                "name",
                "current_price",
                "last1_price",
                "last2_price",
            ],
        )
        self.assertEqual(row["last1_round_id"], "5")
        self.assertEqual(row["last2_round_id"], "4")
        self.assertEqual(row["last1_price"], "10")
        self.assertEqual(row["last2_price"], "9.8")
        self.assertEqual(row["rolling2_fpoints"], "63")
        self.assertEqual(row["score_floor_big_rise"], "-27")
        self.assertEqual(row["score_floor_small_rise"], "-36")
        self.assertEqual(row["score_floor_avoid_big_fall"], "-45")
        self.assertNotIn("score_floor_avoid_small_fall", row)
        self.assertNotIn("needed_for_big_rise", row)
        self.assertNotIn("negative_score_buffer_for_big_rise", row)
        self.assertLess(
            fetch_public.Decimal("-28"),
            fetch_public.Decimal(row["score_floor_big_rise"]),
        )

    def test_rankings_are_narrow_sorted_views_of_score_floors(self):
        assets = [
            fetch_public.PublicAsset(
                asset_id="easier",
                type="driver",
                name="Easier",
                current_price=fetch_public.Decimal("10.0"),
                current_total_fpoints=fetch_public.Decimal("200"),
                rank="1",
            ),
            fetch_public.PublicAsset(
                asset_id="harder",
                type="driver",
                name="Harder",
                current_price=fetch_public.Decimal("10.0"),
                current_total_fpoints=fetch_public.Decimal("190"),
                rank="2",
            ),
        ]
        metric_rows = fetch_public.official_asset_metric_rows(
            assets,
            [
                {
                    "gameday_id": "5",
                    "asset_id": "easier",
                    "race_fpoints": "20",
                    "price_change": "0.2",
                    "is_gameday_complete": "1",
                    "is_active": "1",
                },
                {
                    "gameday_id": "5",
                    "asset_id": "harder",
                    "race_fpoints": "18",
                    "price_change": "0.2",
                    "is_gameday_complete": "1",
                    "is_active": "1",
                },
            ],
            "6",
            "2026-06-08T00:00:00Z",
        )
        rankings = fetch_public.official_asset_ranking_rows(metric_rows)
        avoid_big_fall_rows = [
            row for row in rankings if row["ranking_metric"] == "avoid_big_fall"
        ]

        self.assertEqual(
            set(rankings[0].keys()),
            set(fetch_public.OFFICIAL_ASSET_RANKINGS_COLUMNS),
        )
        self.assertEqual(
            {row["ranking_metric"] for row in rankings},
            {"big_rise", "small_rise", "avoid_big_fall"},
        )
        self.assertEqual(avoid_big_fall_rows[0]["asset_id"], "easier")
        self.assertEqual(avoid_big_fall_rows[0]["score_floor"], "-2")
        self.assertEqual(avoid_big_fall_rows[1]["asset_id"], "harder")
        self.assertEqual(avoid_big_fall_rows[1]["score_floor"], "0")
        self.assertNotIn("current_price", rankings[0])
        self.assertNotIn("rolling2_fpoints", rankings[0])

    def test_fetch_public_data_writes_v3_csvs_without_default_breakdown(self):
        common_feed = {
            "Data": {
                "driver": [
                    {
                        "config": {"key": "fPoints"},
                        "participants": [
                            {
                                "playerid": "drv",
                                "playername": "Driver",
                                "curvalue": 10.0,
                                "statvalue": 200,
                                "rnk": 1,
                            }
                        ],
                    }
                ],
                "constructor": [
                    {
                        "config": {"key": "fPoints"},
                        "participants": [
                            {
                                "playerid": "con",
                                "teamname": "Constructor",
                                "curvalue": 20.0,
                                "statvalue": 300,
                                "rnk": 1,
                            }
                        ],
                    }
                ],
            }
        }

        def history_feed(asset_id):
            total = 35 if asset_id == "drv" else 50
            return {
                "Value": {
                    "FixtureWiseStats": [
                        {
                            "GamedayId": 5,
                            "RaceDayWise": [
                                {
                                    "MeetingName": "Completed GP",
                                    "CountryName": "Done",
                                    "CircuitOfficialName": "Done Circuit",
                                    "Season": "2026",
                                    "SessionType": "Race",
                                    "MatchStatus": "4",
                                    "SessionStartDate": "2026-05-31T15:00:00Z",
                                }
                            ],
                        },
                        {
                            "GamedayId": 6,
                            "RaceDayWise": [
                                {
                                    "MeetingName": "Target GP",
                                    "CountryName": "Target",
                                    "CircuitOfficialName": "Target Circuit",
                                    "Season": "2026",
                                    "SessionType": "Race",
                                    "MatchStatus": "1",
                                    "SessionStartDate": "2026-06-07T15:00:00Z",
                                }
                            ],
                        },
                    ],
                    "GamedayWiseStats": [
                        {
                            "GamedayId": 5,
                            "PlayerValue": 10,
                            "OldPlayerValue": 9.8,
                            "IsPlayed": 1,
                            "IsActive": 1,
                            "StatsWise": [
                                {"Frequency": "-", "Event": "Total", "Value": total}
                            ],
                        },
                        {
                            "GamedayId": 6,
                            "PlayerValue": 10,
                            "OldPlayerValue": 10,
                            "IsPlayed": 0,
                            "IsActive": 1,
                            "StatsWise": [
                                {"Frequency": "-", "Event": "Total", "Value": -5}
                            ],
                        },
                    ],
                }
            }

        def fake_fetch_json(url, timeout):
            if url == fetch_public.WEB_CONFIG_URL:
                return {
                    "Data": {
                        "config": {
                            "tourId": 4,
                            "statistics": {
                                "endPoints": {
                                    "commonStatistics": "statistics/common_{tourId}.json"
                                }
                            },
                        }
                    }
                }
            if url == "https://fantasy.formula1.com/feeds/v2/statistics/common_4.json":
                return common_feed
            if url.endswith("playerstats_drv.json"):
                return history_feed("drv")
            if url.endswith("playerstats_con.json"):
                return history_feed("con")
            raise AssertionError(f"unexpected url {url}")

        original_fetch_json = fetch_public.fetch_json
        fetch_public.fetch_json = fake_fetch_json
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_dir = Path(tmp) / "official"
                asset_count, history_count = fetch_public.fetch_public_data(
                    out_dir, None, False, 20
                )

                self.assertEqual(asset_count, 2)
                self.assertEqual(history_count, 2)
                self.assertTrue((out_dir / "official_round_context.csv").exists())
                self.assertTrue((out_dir / "official_asset_metrics.csv").exists())
                self.assertTrue((out_dir / "official_asset_rankings.csv").exists())
                self.assertFalse((out_dir / "gameday_score_breakdown.csv").exists())
                self.assertFalse((out_dir / "current_assets.csv").exists())

                with (out_dir / "official_round_context.csv").open(
                    "r", encoding="utf-8", newline=""
                ) as handle:
                    context = list(csv.DictReader(handle))
                self.assertEqual(context[0]["target_round_id"], "6")
                self.assertEqual(context[0]["is_complete"], "0")

                with (out_dir / "official_asset_metrics.csv").open(
                    "r", encoding="utf-8", newline=""
                ) as handle:
                    metrics = list(csv.DictReader(handle))
                self.assertEqual(
                    set(metrics[0].keys()),
                    set(fetch_public.OFFICIAL_ASSET_METRICS_COLUMNS),
                )
                self.assertEqual({row["type"] for row in metrics}, {"driver", "constructor"})
                self.assertEqual({row["last1_round_id"] for row in metrics}, {"5"})
        finally:
            fetch_public.fetch_json = original_fetch_json


if __name__ == "__main__":
    unittest.main()
