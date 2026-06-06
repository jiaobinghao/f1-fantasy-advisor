import importlib.util
import sys
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
                        "PlayerValue": 24.7,
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
        self.assertEqual(scores[0]["player_value"], "24.7")
        self.assertEqual(scores[0]["old_player_value"], "24.4")
        self.assertEqual(scores[0]["price_change"], "0.3")
        self.assertEqual(scores[0]["is_gameday_complete"], "1")
        self.assertEqual(breakdown[1]["event"], "Qualifying Position")
        self.assertEqual(gamedays["6"]["meeting_name"], "Monaco Grand Prix")
        self.assertEqual(gamedays["6"]["session_types"], "Qualifying;Race")
        self.assertEqual(gamedays["6"]["is_complete"], "1")

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


if __name__ == "__main__":
    unittest.main()
