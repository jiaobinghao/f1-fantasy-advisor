"""Scoring, forecasting, provenance, and exact-search regression tests."""

import contextlib
import copy
import io
import json
import math
import tempfile
import unittest
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from script_loader import load_script

cli = load_script("fantasy_forecast")
core = load_script("forecast_core")
lineups = load_script("forecast_lineups")
prob = load_script("forecast_probabilities")


def race(position=1, start=1, overtakes=0, status="classified", fl=False, dotd=False):
    return {"status": status, "position": position, "start_position": start,
            "overtakes": overtakes, "fastest_lap": fl, "driver_of_day": dotd}


def qualifying(position=1, q2=True, q3=True, status="classified"):
    return {"status": status, "position": position, "q2": q2, "q3": q3}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.rules = core.load_rules()
        self.model = cli.demo_model()

    def test_nc_retains_overtakes_but_not_positions_lost(self):
        result = core.driver_categories(race(None, 16, 7, "nc"), "race", self.rules)
        self.assertEqual(sum(result.values()), -13)
        self.assertNotIn("race_positions_lost", result)
        self.assertEqual(core.driver_categories(qualifying(16, False, False), "qualifying", self.rules),
                         {"qualifying_position": 0})

    def test_dsq_cancels_session_rewards_and_constructor_gets_extra_penalty(self):
        for session, penalty in (("qualifying", -5), ("race", -20), ("sprint", -10)):
            with self.subTest(session=session):
                model = cli.demo_model(sprint=True)
                s = model["scenarios"][0]
                s[session]["d1"] = (qualifying(None, False, False, "dsq") if session == "qualifying"
                                     else race(None, 1, status="dsq"))
                ds = [a for a in model["assets"] if a["type"] == "driver"]
                cs = [a for a in model["assets"] if a["type"] == "constructor"]
                values = core.score_scenario(s, ds, cs, self.rules, True)
                self.assertEqual(values["d1"][f"{session}_nc"], penalty)
                self.assertEqual(values["c1"][f"{session}_constructor_dsq"], penalty)
                self.assertNotIn(f"{session}_position", core.driver_categories(s[session]["d1"], session, self.rules))

    def test_race_driver_and_constructor_reconciliation(self):
        # Public US scoring example: Leclerc 53, Hamilton 23, Ferrari 81.
        ds = [{"asset_id": "lec", "constructor_id": "fer"}, {"asset_id": "ham", "constructor_id": "fer"}]
        s = {"qualifying": {"lec": qualifying(4), "ham": qualifying(5)},
             "race": {"lec": race(2, 4, 6, fl=True, dotd=True), "ham": race(4, 5, 4)},
             "pit_stops": {"fer": {"fastest_stop_seconds": 2.3, "fastest_of_race": False, "world_record": False}}}
        result = core.score_scenario(s, ds, [{"asset_id": "fer"}], self.rules)
        self.assertEqual(sum(result["lec"].values()), 53)
        self.assertEqual(sum(result["ham"].values()), 23)
        self.assertEqual(sum(result["fer"].values()), 81)
        self.assertNotIn("race_dotd", result["fer"])

    def test_sprint_cap_and_fl(self):
        result = core.driver_categories(race(20, 1, fl=True), "sprint", self.rules)
        self.assertEqual(result["sprint_positions_lost"], -10)
        self.assertEqual(result["sprint_fastest_lap"], 5)
        self.assertNotIn("race_dotd", result)
        self.assertEqual(core.driver_categories(race(20, 1), "race", self.rules)["race_positions_lost"], -19)

    def test_pit_thresholds_and_record_bonus(self):
        _, ds, cs = core.validate_model(self.model, self.rules)
        s = self.model["scenarios"][0]
        for seconds, expected in ((1.99, 20), (2.0, 10), (2.19, 10), (2.2, 5), (2.49, 5), (2.5, 2), (2.99, 2), (3.0, 0)):
            with self.subTest(seconds=seconds):
                s["pit_stops"]["c1"]["fastest_stop_seconds"] = seconds
                self.assertEqual(core.score_scenario(s, ds, cs, self.rules)["c1"]["pit_time"], expected)
        s["pit_stops"]["c1"].update(fastest_stop_seconds=1.7, world_record=True)
        core.validate_model(self.model, self.rules)
        value = core.score_scenario(s, ds, cs, self.rules)["c1"]
        self.assertEqual(value["pit_time"] + value["pit_fastest"] + value["pit_record"], 40)

    def test_progression_bonus_is_exclusive(self):
        _, ds, cs = core.validate_model(self.model, self.rules)
        s = self.model["scenarios"][0]
        for flags, expected in ((((False, False), (False, False)), -1),
                                (((True, False), (False, False)), 1),
                                (((True, False), (True, False)), 3),
                                (((True, True), (True, False)), 5),
                                (((True, True), (True, True)), 10)):
            for aid, (q2, q3) in zip(("d1", "d2"), flags):
                s["qualifying"][aid].update(q2=q2, q3=q3)
            self.assertEqual(core.score_scenario(s, ds, cs, self.rules)["c1"]["qualifying_progress"], expected)

    def test_no_negative_clips_categories_not_asset_total(self):
        evaluation = core.evaluate_model(self.model, self.rules)
        self.assertEqual(evaluation["scores"]["d1"][2], -9)  # Q10 - NC20 + OT1.
        self.assertEqual(evaluation["protected_scores"]["d1"][2], 11)
        categories = evaluation["scenario_categories"][2]["c1"]
        self.assertGreater(evaluation["protected_scores"]["c1"][2], max(sum(categories.values()), 0))

    def test_component_pmf_and_mean_reconcile(self):
        e = core.evaluate_model(self.model, self.rules)
        mass, means = defaultdict(float), defaultdict(float)
        for row in e["component_distributions"]:
            mass[row["asset_id"], row["category"]] += row["probability"]
            means[row["asset_id"]] += row["mu_contribution"]
        for value in mass.values():
            self.assertAlmostEqual(value, 1)
        for row in e["asset_metrics"]:
            self.assertAlmostEqual(row["mu"], means[row["asset_id"]])

    def test_standard_and_sprint_are_distinct(self):
        standard = core.evaluate_model(self.model, self.rules)
        sprint = core.evaluate_model(cli.demo_model(True), self.rules)
        self.assertGreater(sprint["asset_metrics"][0]["mu"], standard["asset_metrics"][0]["mu"])
        self.assertFalse(any("sprint" in r["category"] for r in standard["component_distributions"]))


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.model = cli.demo_model()
        self.rules = core.load_rules()

    def rejects(self, model=None, message=None):
        with self.assertRaisesRegex(ValueError, message or ".*"):
            core.validate_model(model or self.model, self.rules)

    def test_probability_mass_nonfinite_boolean_and_sign(self):
        for bad in (0.6, -0.1, float("nan"), float("inf"), True):
            with self.subTest(bad=bad):
                model = copy.deepcopy(self.model)
                model["scenarios"][0]["probability"] = bad
                self.rejects(model)

    def test_joint_position_and_award_constraints(self):
        for field, value in (("position", 1), ("start_position", 1), ("fastest_lap", True)):
            with self.subTest(field=field):
                model = copy.deepcopy(self.model)
                model["scenarios"][0]["race"]["d2"][field] = value
                self.rejects(model)
        self.model["scenarios"][0]["race"]["d1"]["driver_of_day"] = True
        self.rejects()

    def test_unknown_scoring_field_rejected(self):
        self.model["scenarios"][0]["race"]["d1"]["fastest_lpa"] = True
        self.rejects(message="exactly")

    def test_full_field_required_outside_synthetic_demo(self):
        self.model["metadata"]["synthetic"] = False
        self.rejects(message="full field")

    def test_season_profile_and_progression_caps(self):
        self.model["metadata"]["season"] = 2027
        self.rejects(message="mismatch")
        self.model["metadata"]["season"] = 2026
        self.rules["max_q3"] = 3
        self.rejects(message="too many")

    def test_sprint_leakage(self):
        self.model["scenarios"][0]["sprint"] = copy.deepcopy(self.model["scenarios"][0]["race"])
        self.rejects(message="standard")

    def test_temporal_leakage(self):
        for field in ("prices_observed_at", "as_of"):
            model = copy.deepcopy(self.model)
            model["metadata"][field] = "2026-01-03T00:00:00Z"
            self.rejects(model)
        self.model["metadata"]["evidence"][0]["observed_at"] = "2026-01-03T00:00:00Z"
        self.rejects(message="cutoff")

    def test_probability_audits_and_calibration_required(self):
        del self.model["metadata"]["probability_models"]["race_order"]
        self.rejects(message="probability_models")
        self.model = cli.demo_model()
        self.model["metadata"]["probability_models"]["race_order"]["effective_sample_size"] = 5
        self.rejects()
        self.model = cli.demo_model()
        self.model["metadata"].update(synthetic=False, model_status="calibrated")
        self.rejects(message="report")

    def test_invalid_record_and_fastest_stop(self):
        self.model["scenarios"][0]["pit_stops"]["c1"]["world_record"] = True
        self.rejects(message="record")
        self.model["scenarios"][0]["pit_stops"]["c1"].update(world_record=False, fastest_stop_seconds=1.7)
        self.rejects(message="record")
        self.model["scenarios"][0]["pit_stops"]["c1"]["fastest_stop_seconds"] = 3.2
        self.rejects(message="minimum")


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.spec = {"schema_version": 1, "target": {"round": 4, "as_of": "2026-04-01T00:00:00Z"},
                     "half_life_rounds": 1,
                     "prior": {"probabilities": {"yes": 0.75, "no": 0.25}, "strength": 2,
                               "source": "test", "available_at": "2026-01-01T00:00:00Z"},
                     "observations": [{"id": "a", "round": 2, "observed_at": "2026-02-01T00:00:00Z",
                                       "source": "test", "outcome": "no"},
                                      {"id": "b", "round": 3, "observed_at": "2026-03-01T00:00:00Z",
                                       "source": "test", "outcome": "yes"}]}

    def test_power_prior_hand_calculation(self):
        result = prob.estimate_categorical(self.spec)
        self.assertAlmostEqual(result["weighted_exposure"], 1.5)
        self.assertAlmostEqual(result["probabilities"]["yes"], 2.5 / 3.5)
        self.assertAlmostEqual(result["effective_sample_size"], 2.25 / 1.25)
        p = 2.5 / 3.5
        self.assertAlmostEqual(result["posterior_sd"]["yes"], math.sqrt(p * (1 - p) / 4.5))

    def test_prior_only(self):
        self.spec["observations"] = []
        result = prob.estimate_categorical(self.spec)
        self.assertEqual(result["probabilities"], self.spec["prior"]["probabilities"])
        self.assertEqual(result["status"], "prior_only")
        self.assertEqual(result["effective_sample_size"], 0)

    def test_duplicate_future_unknown_outcome_rejected(self):
        for key, value in (("id", "b"), ("round", 4), ("observed_at", "2027-01-01T00:00:00Z"),
                           ("outcome", "maybe"), ("weight", -1)):
            spec = copy.deepcopy(self.spec)
            spec["observations"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                prob.estimate_categorical(spec)

    def calibration_input(self):
        return {"schema_version": 1, "predictions": [
            {"id": "p", "round": 1, "source": "test", "trained_through": "2026-01-01T00:00:00Z",
             "as_of": "2026-02-01T00:00:00Z", "lock_at": "2026-02-02T00:00:00Z",
             "outcome_known_at": "2026-02-03T00:00:00Z", "probabilities": {"yes": 0.8, "no": 0.2}, "actual": "yes"}]}

    def test_calibration_brier_and_log_loss(self):
        report = prob.calibration_report(self.calibration_input())
        self.assertAlmostEqual(report["multiclass_brier"], 0.08)
        self.assertAlmostEqual(report["mean_log_loss"], -math.log(0.8))
        self.assertEqual(report["test_rounds"], 1)

    def test_impossible_actual_is_not_smoothed_away(self):
        spec = self.calibration_input()
        spec["predictions"][0]["probabilities"] = {"yes": 0, "no": 1}
        report = prob.calibration_report(spec)
        self.assertIsNone(report["mean_log_loss"])
        self.assertTrue(report["log_loss_infinite"])
        self.assertEqual(report["multiclass_brier"], 2)

    def test_backtest_leakage_rejected(self):
        spec = self.calibration_input()
        spec["predictions"][0]["trained_through"] = "2026-02-03T00:00:00Z"
        with self.assertRaises(ValueError):
            prob.calibration_report(spec)


class LineupTests(unittest.TestCase):
    def setUp(self):
        self.rules = core.load_rules()
        self.evaluation = core.evaluate_model(cli.demo_model(), self.rules)
        self.ids = ["d1", "d2", "d3", "d4", "d5", "c1", "c2"]

    def test_exact_optimum_matches_independent_brute_force(self):
        e = self.evaluation
        budget, free = 122, 0
        result = lineups.optimize(e, {"previous_lineup": self.ids, "bank": 2, "free_transfers": free}, self.rules)
        candidates = []
        for ds in combinations([f"d{i}" for i in range(1, 7)], 5):
            for cs in combinations(["c1", "c2", "c3"], 2):
                ids = ds + cs
                if sum(e["assets"][aid]["price"] for aid in ids) > budget:
                    continue
                penalty = 10 * len(set(ids) - set(self.ids))
                for boosted in ds:
                    mu = sum(p * (sum(e["scores"][aid][j] for aid in ids) + e["scores"][boosted][j] - penalty)
                             for j, p in enumerate(e["weights"]))
                    candidates.append(mu)
        self.assertAlmostEqual(result["budget"], budget)
        self.assertAlmostEqual(result["top"][0]["mu"], max(candidates))
        self.assertLessEqual(result["top"][0]["cost"], budget)

    def test_no_negative_does_not_remove_transfer_penalty(self):
        team = {"previous_lineup": self.ids, "bank": 0, "free_transfers": 0, "max_transfers": 0,
                "chip": "no_negative", "penalty_already_incurred": 10}
        result = lineups.optimize(self.evaluation, team, self.rules)
        row = result["top"][0]
        e = self.evaluation
        expected = sum(sum(p * v for p, v in zip(e["weights"], e["protected_scores"][aid])) for aid in self.ids + [row["boost_2x"]]) - 10
        self.assertAlmostEqual(row["mu"], expected)
        self.assertEqual(row["transfer_penalty"], 10)
        self.assertAlmostEqual(row["gain_vs_no_transfers"], 0)

    def test_paid_transfer_compares_net_points_to_best_free(self):
        e = copy.deepcopy(self.evaluation)
        e["scores"]["d6"] = [100] * len(e["weights"])
        result = lineups.optimize(e, {"previous_lineup": self.ids, "bank": 0,
                                     "free_transfers": 0, "max_transfers": 1}, self.rules)
        row = result["top"][0]
        self.assertEqual(row["transfers"], 1)
        self.assertEqual(row["transfer_penalty"], 10)
        self.assertIn("d6", row["transfers_in"])
        self.assertGreater(row["gain_vs_best_free"], 0)
        self.assertAlmostEqual(row["gain_vs_best_free"], row["mu"] - result["best_free"]["mu"])
        self.assertEqual(result["best_free"]["transfers"], 0)
        self.assertAlmostEqual(row["p_beat_no_transfers"], 1)

    def test_3x_has_distinct_normal_2x(self):
        team = {"budget": 125, "chip": "3x"}
        row = lineups.optimize(self.evaluation, team, self.rules)["top"][0]
        self.assertNotEqual(row["boost_2x"], row["boost_3x"])
        means = {m["asset_id"]: m["mu"] for m in self.evaluation["asset_metrics"]}
        self.assertAlmostEqual(row["mu"], sum(means[aid] for aid in row["asset_ids"])
                               + means[row["boost_2x"]] + 2 * means[row["boost_3x"]])

    def test_joint_correlation_changes_risk_and_autopilot_not_fixed_boost_mean(self):
        ids = ["a", "b", "c", "d", "e", "x", "y"]
        correlated = {aid: [0, 0] for aid in ids}
        correlated.update(a=[0, 20], b=[0, 20])
        anticorrelated = dict(correlated, b=[20, 0])
        weights = [0.5, 0.5]
        fixed1, _, _ = lineups.lineup_values(ids, ids[:5], correlated, weights, "none", 0)
        fixed2, _, _ = lineups.lineup_values(ids, ids[:5], anticorrelated, weights, "none", 0)
        self.assertEqual(core.summarize(fixed1, weights)["mu"], core.summarize(fixed2, weights)["mu"])
        self.assertNotEqual(core.summarize(fixed1, weights)["sd"], core.summarize(fixed2, weights)["sd"])
        auto1, _, _ = lineups.lineup_values(ids, ids[:5], correlated, weights, "autopilot", 0)
        auto2, _, _ = lineups.lineup_values(ids, ids[:5], anticorrelated, weights, "autopilot", 0)
        self.assertEqual(core.summarize(auto1, weights)["mu"], 30)
        self.assertEqual(core.summarize(auto2, weights)["mu"], 40)

    def test_wildcard_limitless_and_same_chip_baseline(self):
        for chip in ("wildcard", "limitless", "autopilot"):
            result = lineups.optimize(self.evaluation, {"previous_lineup": self.ids, "bank": 0,
                                      "free_transfers": 0, "chip": chip}, self.rules)
            self.assertEqual(result["baseline"]["chip"], chip)
            if chip in ("wildcard", "limitless"):
                self.assertEqual(result["top"][0]["transfer_penalty"], 0)
        result = lineups.optimize(self.evaluation, {"budget": 1, "chip": "limitless"}, self.rules)
        self.assertIsNone(result["top"][0]["bank"])
        with self.assertRaises(ValueError):
            lineups.optimize(self.evaluation, {"budget": 1, "chip": "wildcard"}, self.rules)

    def test_inactive_holding_can_be_sold_but_not_scored_as_zero(self):
        model = cli.demo_model()
        model["assets"].append({"asset_id": "old", "type": "driver", "name": "Inactive", "price": 8, "active": False})
        evaluation = core.evaluate_model(model, self.rules)
        previous = ["old" if aid == "d5" else aid for aid in self.ids]
        result = lineups.optimize(evaluation, {"previous_lineup": previous, "bank": 0, "free_transfers": 1}, self.rules)
        self.assertTrue(result["baseline_unavailable"])
        self.assertIsNone(result["baseline"])
        self.assertIn("old", result["top"][0]["transfers_out"])

    def test_invalid_money_and_final_fix(self):
        for team in ({"budget": 100.01}, {"budget": True}, {"budget": 125, "chip": "final_fix"}):
            with self.assertRaises(ValueError):
                lineups.optimize(self.evaluation, team, self.rules)

    def test_keep_and_sell_constraints_do_not_remove_race_participants(self):
        keep = lineups.optimize(self.evaluation, {"budget": 125, "required_assets": ["d6"]}, self.rules)
        sell = lineups.optimize(self.evaluation, {"budget": 125, "excluded_assets": ["d6"]}, self.rules)
        self.assertTrue(all("d6" in row["asset_ids"] for row in keep["top"]))
        self.assertTrue(all("d6" not in row["asset_ids"] for row in sell["top"]))
        self.assertIn("d6", self.evaluation["scores"])
        with self.assertRaises(ValueError):
            lineups.optimize(self.evaluation, {"budget": 125, "required_assets": ["d6"], "excluded_assets": ["d6"]}, self.rules)


class CommandTests(unittest.TestCase):
    def test_all_commands_standard_and_sprint(self):
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stdout(io.StringIO()):
            for fmt in ("standard", "sprint"):
                out = Path(root) / fmt
                self.assertEqual(cli.main(["example", "--out-dir", str(out), "--format", fmt]), 0)
                self.assertEqual(cli.main(["validate", str(out / "forecast.json")]), 0)
                self.assertEqual(cli.main(["evaluate", str(out / "forecast.json"), "--out-dir", str(out / "results")]), 0)
                self.assertTrue((out / "results" / "component_probabilities.csv").exists())
                self.assertEqual(cli.main(["optimize", str(out / "forecast.json"), "--teams", str(out / "teams.json"),
                                          "--out", str(out / "optimized.json")]), 0)
                self.assertEqual(len(json.loads((out / "optimized.json").read_text())["teams"]), 3)
                for command, filename in (("estimate", "probability_input.json"), ("calibrate", "calibration_input.json")):
                    self.assertEqual(cli.main([command, str(out / filename)]), 0)

    def test_example_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            cli.write_example(path)
            with self.assertRaises(ValueError):
                cli.write_example(path)


if __name__ == "__main__":
    unittest.main()
