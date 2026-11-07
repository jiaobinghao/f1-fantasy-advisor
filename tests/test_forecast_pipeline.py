"""Behavioral checks for the v1 acquisition, forecast and budget pipeline."""

import copy
import csv
import json
import math
import tempfile
import unittest
from itertools import combinations
from pathlib import Path

from script_loader import load_script

core = load_script("forecast_core")
example = load_script("forecast_example")
generate = load_script("forecast_generate")
grid = load_script("forecast_grid")
prices = load_script("forecast_prices")
pipeline = load_script("forecast_run")
lineups = load_script("forecast_lineups")
data_module = load_script("forecast_data")
io_module = load_script("forecast_io")
circuits = load_script("forecast_circuits")


def make_generator(format="standard", configure=None):
    config, data, teams = example.example_data(format)
    config["model_parameters"]["samples"] = 32
    if configure:
        configure(config, data)
    sources = [{"id": "input", "source": "Synthetic test", "observed_at": config["as_of"]}]
    rules = core.load_rules()
    grid_rules = core.load_json(pipeline.REFERENCES / "grid-rules-2026.json")
    return generate.Generator(data, config, rules, grid_rules, sources), teams


class DriverPositionTests(unittest.TestCase):
    def test_weighted_positions_condition_on_available_outcomes(self):
        model = {
            "assets": [{"asset_id": "d1", "type": "driver", "name": "Driver"},
                       {"asset_id": "d2", "type": "driver", "name": "Inactive", "active": False},
                       {"asset_id": "c1", "type": "constructor", "name": "Team"}],
            "scenarios": [
                {"probability": 0.25, "qualifying": {"d1": {"status": "classified", "position": 2}},
                 "race": {"d1": {"status": "classified", "start_position": 4, "position": 3}},
                 "sprint": {"d1": {"status": "classified", "start_position": 5, "position": 4}}},
                {"probability": 0.5, "qualifying": {"d1": {"status": "classified", "position": 6}},
                 "race": {"d1": {"status": "nc", "start_position": 8, "position": None}},
                 "sprint": {"d1": {"status": "classified", "start_position": 7, "position": 8}}},
                {"probability": 0.25, "qualifying": {"d1": {"status": "nc", "position": None}},
                 "race": {"d1": {"status": "dns", "start_position": 9, "position": None}},
                 "sprint": {"d1": {"status": "dsq", "start_position": 9, "position": None}}},
            ],
        }
        row, = pipeline.driver_position_means(model)
        self.assertAlmostEqual(row["mean_qualifying_position"], 14 / 3)
        self.assertAlmostEqual(row["p_qualifying_position_available"], 0.75)
        self.assertAlmostEqual(row["mean_race_start_position"], 20 / 3)
        self.assertAlmostEqual(row["p_race_start_position_available"], 0.75)
        self.assertEqual(row["mean_race_finish_position"], 3)
        self.assertAlmostEqual(row["p_race_finish_position_available"], 0.25)
        self.assertEqual(row["mean_sprint_start_position"], 7)
        self.assertAlmostEqual(row["mean_sprint_finish_position"], 20 / 3)
        self.assertAlmostEqual(row["p_sprint_finish_position_available"], 0.75)

    def test_no_available_position_is_null_and_standard_has_no_sprint(self):
        model = {"assets": [{"asset_id": "d1", "type": "driver", "name": "Driver"}],
                 "scenarios": [{"probability": 1.0,
                                "qualifying": {"d1": {"status": "nc", "position": None}},
                                "race": {"d1": {"status": "dns", "start_position": None, "position": None}}}]}
        row, = pipeline.driver_position_means(model)
        self.assertIsNone(row["mean_qualifying_position"])
        self.assertIsNone(row["mean_race_start_position"])
        self.assertIsNone(row["mean_race_finish_position"])
        self.assertEqual(row["p_race_finish_position_available"], 0)
        self.assertNotIn("mean_sprint_start_position", row)


class GridTests(unittest.TestCase):
    def setUp(self):
        self.order = [f"d{i}" for i in range(1, 7)]
        self.rules = {"algorithm": "fia_temporary_positions", "back_of_grid_above": 15}

    def penalty(self, driver, places, eid=None):
        return {"event_id": eid or driver, "asset_id": driver, "session": "race", "penalty_type": "grid_places", "places": places}

    def ordered(self, penalties, qualifying=None):
        result = grid.allocate_grid(self.order, qualifying or {}, penalties, "race", {}, self.rules)
        return sorted(result, key=result.get)

    def test_tied_temporary_positions_and_unpenalized_drivers(self):
        actual = self.ordered([self.penalty("d1", 3), self.penalty("d3", 1)])
        self.assertEqual(actual, ["d2", "d4", "d1", "d3", "d5", "d6"])

    def test_large_penalties_and_unclassified_order(self):
        events = [self.penalty("d1", 20), self.penalty("d3", 30)]
        self.assertEqual(self.ordered(events), ["d2", "d4", "d5", "d6", "d1", "d3"])
        actual = self.ordered(events, {"d6": {"status": "nc"}})
        self.assertEqual(actual[-3:], ["d1", "d3", "d6"])

    def test_official_grid_not_penalized_twice(self):
        events = [self.penalty("d1", 5)]
        official = {"official_orders": {"race": {"asset_ids": ["d2", "d3", "d4", "d5", "d6", "d1"], "applied_event_ids": ["d1"]}}}
        result = grid.allocate_grid(self.order, {}, events, "race", official, self.rules)
        self.assertEqual(result["d1"], 6)
        with self.assertRaisesRegex(ValueError, "applied_event_ids"):
            grid.allocate_grid(self.order, {}, [], "race", official, self.rules)

    def test_pit_lane_requires_sourced_scoring_convention(self):
        event = {"event_id": "pit", "asset_id": "d1", "session": "race", "penalty_type": "pit_lane"}
        with self.assertRaisesRegex(ValueError, "pit-lane"):
            self.ordered([event])
        result = grid.allocate_grid(self.order, {}, [event], "race",
                                    {"pit_lane_convention": {"method": "ordered_after_grid", "source_ref": "test"}}, self.rules)
        self.assertEqual(result["d1"], 6)

    def test_uncertain_penalties_do_not_get_invented_probabilities(self):
        event = {**self.penalty("d1", 5), "status": "expected"}
        rows, weighted = grid.branches({}, [event])
        self.assertFalse(weighted)
        self.assertEqual([r["active"] for r in rows], [set(), {"d1"}])
        rows, weighted = grid.branches({}, [{**event, "probability": 0.8}])
        self.assertTrue(weighted)
        self.assertAlmostEqual(rows[1]["probability"], 0.8)
        _, weighted = grid.branches({}, [{**event, "probability": 0.8}, {**event, "event_id": "d2", "probability": 0.4}])
        self.assertFalse(weighted)

    def test_many_uncertain_penalties_accept_explicit_joint_branches(self):
        events = [{**self.penalty("d1", 1, str(i)), "status": "expected"} for i in range(7)]
        with self.assertRaisesRegex(ValueError, "explicit joint branches"):
            grid.branches({}, events)
        rows, weighted = grid.branches({"joint_branches": [{"active_events": [], "probability": 0.2},
            {"active_events": [str(i) for i in range(7)], "probability": 0.8}],
            "joint_probability_method": "Synthetic joint assumption", "joint_probability_source": "input"}, events)
        self.assertTrue(weighted)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[1]["active"]), 7)


class GenerationTests(unittest.TestCase):
    def test_four_round_linear_weights_drive_rank_and_status_estimates(self):
        gen, _ = make_generator()
        audit = gen.audit["race:d1"]
        self.assertEqual(audit["rounds"], [3, 4, 5, 6])
        self.assertEqual(audit["sample_weights"], [0.25, 0.5, 0.75, 1.0])
        self.assertAlmostEqual(audit["history_score"], 5.4)
        self.assertAlmostEqual(audit["status_probabilities"]["classified"],
                               (8*audit["prior"]["classified"]+2.5)/10.5)
        self.assertEqual(gen.audit["pit:c1"]["sample_weights"], [0.25, 0.5, 0.75, 1.0])
        self.assertEqual(gen.audit["race:fastest_lap"]["sample_weights"], [0.25, 0.5, 0.75, 1.0])

    def test_history_pace_and_draws_are_isolated_by_session(self):
        baseline, _ = make_generator("sprint")
        for changed_session in baseline.sessions:
            def change(_, data):
                for row in data["history"]:
                    if row["session"] == changed_session and row["status"] == "classified":
                        row["position"] = row["field_size"]+1-row["position"]
            changed, _ = make_generator("sprint", change)
            with self.subTest(session=changed_session):
                for session in baseline.sessions:
                    audit = changed.audit[f"{session}:d1"]
                    history = audit["pace_history"]
                    self.assertEqual(history["session"], session)
                    self.assertEqual(history["rounds"], [3, 4, 5, 6])
                    self.assertEqual(history["sample_weights"], [0.25, 0.5, 0.75, 1.0])
                    self.assertEqual(history["sample_count"], 4)
                    self.assertAlmostEqual(audit["practice_score"], 6)
                    self.assertEqual(audit["practice_weight"], 0.4)
                    self.assertAlmostEqual(audit["combined_score"], 0.6*history["score"]+0.4*6)
                    old_draws = [baseline.pace_order(session, s) for s in range(32)]
                    new_draws = [changed.pace_order(session, s) for s in range(32)]
                    if session == changed_session:
                        self.assertNotEqual(changed.strength[session], baseline.strength[session])
                        self.assertNotEqual(new_draws, old_draws)
                    else:
                        self.assertEqual(changed.strength[session], baseline.strength[session])
                        self.assertEqual(new_draws, old_draws)

    def test_pace_fallback_stays_in_its_session_and_exports_its_actual_pool(self):
        for fallback in ("constructor", "midfield"):
            def change(_, data):
                data["history"] = [r for r in data["history"] if not (
                    r["session"] == "race" and (r["person_id"] == "person1" or
                    (fallback == "midfield" and r["constructor_id"] == "c1")))]
            gen, _ = make_generator(configure=change)
            with self.subTest(fallback=fallback):
                audit = gen.audit["race:d1"]
                self.assertEqual(audit["pace_history"]["fallback"], fallback)
                self.assertEqual(audit["sample_count"], 0)
                self.assertEqual(gen.audit["qualifying:d1"]["rank_fallback"], "own_current_spell")
                if fallback == "constructor":
                    self.assertEqual(audit["pace_history"]["sample_count"], 4)
                    self.assertEqual(audit["history_score"], gen.audit["race:d2"]["history_score"])
                else:
                    self.assertEqual(audit["pace_history"]["rounds"], [])
                    self.assertEqual(audit["pace_history"]["source_refs"], [])
                    self.assertEqual(audit["history_score"], 3.5)

    def test_linear_weights_use_valid_round_order_and_share_weight_within_round(self):
        gen, _ = make_generator()
        rows = [{"round": rnd} for rnd in (1, 3, 5, 6, 6)]
        self.assertEqual(gen.weights(rows), [0.25, 0.5, 0.75, 1.0, 1.0])
        self.assertEqual(gen.weights([{"round": 1}, {"round": 3}]), [0.75, 1.0])
        with self.assertRaisesRegex(ValueError, "precede the target"):
            gen.weights(rows, target=6)

    def test_exponential_mode_retains_calendar_round_decay(self):
        gen, _ = make_generator(configure=lambda c, d: c["model_parameters"].update(decay_mode="exponential", half_life=2))
        weights = gen.weights([{"round": rnd} for rnd in (2, 4, 6)])
        self.assertEqual(weights, [0.25, 0.5, 1.0])
        with self.assertRaisesRegex(ValueError, "decay_mode"):
            make_generator(configure=lambda c, d: c["model_parameters"].update(decay_mode="unknown"))

    def test_news_adjusts_only_target_practice_and_is_deduplicated(self):
        gen, _ = make_generator()
        adjusted = next(r for r in gen.adjustments if r["asset_id"] == "d2")
        self.assertEqual(adjusted["raw_score"], 5)
        self.assertEqual(adjusted["adjusted_score"], 3)
        for session in gen.sessions:
            self.assertEqual(gen.practice[session]["d1"], 6)
        def duplicate(_, data):
            data["news"] += copy.deepcopy(data["news"])
        again, _ = make_generator(configure=duplicate)
        self.assertEqual(gen.practice, again.practice)
        self.assertEqual(gen.status, again.status)

    def test_incident_with_no_rank_uses_history_without_bonus(self):
        def change(_, data):
            data["practice"][1]["rank"] = None
            data["news"][0]["tag"] = "incident_compensation"
            for row in data["history"]:
                if row["session"] == "qualifying":
                    row["position"] = 7-row["position"]
        gen, _ = make_generator("sprint", change)
        self.assertNotEqual(gen.practice["qualifying"]["d2"], gen.practice["race"]["d2"])
        for session in gen.sessions:
            with self.subTest(session=session):
                expected = gen.history_score(gen.by_id["d2"], session)[0]
                self.assertAlmostEqual(gen.practice[session]["d2"], expected)
                self.assertAlmostEqual(gen.audit[f"{session}:d2"]["combined_score"], expected)
                adjusted = next(r for r in gen.adjustments if r["asset_id"] == "d2" and r["forecast_session"] == session)
                self.assertIsNone(adjusted["raw_score"])
                self.assertEqual(adjusted["adjusted_score"], expected)
                self.assertEqual(adjusted["fallback"], "own_current_spell")

    def test_missing_practice_uses_history_at_full_weight(self):
        def change(_, data):
            data["practice"] = []
            data["news"] = []
        gen, _ = make_generator("sprint", change)
        self.assertFalse(any(gen.practice.values()))
        for session in gen.sessions:
            for aid in gen.ids:
                audit = gen.audit[f"{session}:{aid}"]
                self.assertIsNone(audit["practice_score"])
                self.assertEqual(audit["practice_weight"], 0)
                self.assertEqual(audit["combined_score"], audit["history_score"])

    def test_no_future_or_duplicate_person_observations(self):
        for field, value in (("round", 7), ("completed_at", "2027-01-01T00:00:00Z")):
            def change(_, data):
                data["history"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                make_generator(configure=change)
        def duplicate(_, data):
            data["history"].append({**data["history"][0], "asset_id": "old-card"})
        with self.assertRaisesRegex(ValueError, "duplicate historical person"):
            make_generator(configure=duplicate)

    def test_future_news_and_unknown_parameters_rejected(self):
        def future(_, data):
            data["news"][0]["published_at"] = "2027-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "after cutoff"):
            make_generator(configure=future)
        with self.assertRaisesRegex(ValueError, "unknown model"):
            make_generator(configure=lambda c, d: c["model_parameters"].update(unknown=1))

    def test_news_cannot_postdate_its_source_snapshot(self):
        config, data, _ = example.example_data()
        sources = [{"id": "input", "source": "Synthetic test", "observed_at": config["as_of"]}]
        data["news"][0]["published_at"] = "2026-06-02T00:00:00Z"
        config["as_of"] = "2026-06-03T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "after source snapshot"):
            generate.Generator(data, config, core.load_rules(), {"season": 2026}, sources)

    def test_normalized_practice_rejects_duplicate_ranks(self):
        def duplicate(_, data):
            data["practice"][1]["rank"] = data["practice"][0]["rank"]
        with self.assertRaisesRegex(ValueError, "duplicate practice rank"):
            make_generator(configure=duplicate)

    def test_penalty_changes_grid_and_recovery_without_changing_qualifying(self):
        gen, _ = make_generator()
        yes, yes_traffic = gen.generate({"fictional-grid-drop"})
        no, no_traffic = gen.generate(set())
        self.assertEqual([s["qualifying"] for s in yes["scenarios"]], [s["qualifying"] for s in no["scenarios"]])
        self.assertEqual([s["race"]["d1"]["status"] for s in yes["scenarios"]], [s["race"]["d1"]["status"] for s in no["scenarios"]])
        self.assertGreater(sum(s["race"]["d1"]["start_position"] for s in yes["scenarios"]), sum(s["race"]["d1"]["start_position"] for s in no["scenarios"]))
        yes_b = next(r["expected_slower_ahead"] for r in yes_traffic if r["asset_id"] == "d1")
        no_b = next(r["expected_slower_ahead"] for r in no_traffic if r["asset_id"] == "d1")
        self.assertGreater(yes_b, no_b)
        self.assertNotEqual([s["race"]["d1"]["position"] for s in yes["scenarios"]], [s["race"]["d1"]["position"] for s in no["scenarios"]])
        again, _ = gen.generate({"fictional-grid-drop"})
        self.assertEqual(yes, again)

    def test_grid_weight_changes_recovery_and_gain_linked_overtakes(self):
        models = {}
        for weight in (0.2, 0.4, 0.8):
            gen, _ = make_generator("sprint", lambda c, d: c["model_parameters"].update(circuit_difficulty=round((weight-0.2)/0.6, 12)))
            for row in gen.history:
                if row["asset_id"] == "d3" and row["session"] != "qualifying":
                    row.update(start_position=3, position=3 if row["round"] == 2 else 2, overtakes=2)
            for session in gen.sessions:
                gen.status[session] = {aid: {"classified": 1, "nc": 0, "dsq": 0} for aid in gen.ids}
            gen.pace_order = lambda session, sample, namespace=None: (
                ["d1", "d2", "d3", "d4", "d5", "d6"] if session == "qualifying" else
                ["d3", "d1", "d2", "d4", "d5", "d6"])
            models[weight], _ = gen.generate(set())
        expected = {0.2: ["d3", "d1", "d2"], 0.4: ["d1", "d3", "d2"], 0.8: ["d1", "d2", "d3"]}
        for weight, model in models.items():
            with self.subTest(grid_weight=weight):
                for scenario, baseline in zip(model["scenarios"], models[0.4]["scenarios"]):
                    self.assertEqual(scenario["qualifying"], baseline["qualifying"])
                    for session in ("race", "sprint"):
                        results = scenario[session]
                        self.assertEqual(sorted(results, key=lambda aid: results[aid]["position"]),
                                         expected[weight]+["d4", "d5", "d6"])
                        for aid in gen.ids:
                            self.assertEqual(results[aid]["start_position"], baseline[session][aid]["start_position"])
        self.assertEqual(models[0.2]["scenarios"][0]["race"]["d3"]["overtakes"], 4)
        self.assertEqual(models[0.8]["scenarios"][0]["race"]["d3"]["overtakes"], 2)

    def test_legacy_thinning_parameter_requires_migration(self):
        with self.assertRaisesRegex(ValueError, "replaced"):
            make_generator(configure=lambda c, d: c["model_parameters"].update(circuit_factor=0.6))

    def test_difficulty_defaults_and_validation(self):
        gen, _ = make_generator()
        self.assertIsNone(gen.parameters["circuit_difficulty"])
        for invalid in (-0.1, 1.1, float("nan"), True):
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, "circuit_difficulty"):
                make_generator(configure=lambda c, d: c["model_parameters"].update(circuit_difficulty=invalid))

    def test_gain_ratio_uses_weighted_sums_and_preserves_integer_count_expectation(self):
        gen, _ = make_generator()
        gains = {3: 2, 4: 4, 5: 1, 6: 3}
        counts = {3: 4, 4: 8, 5: 0, 6: 6}
        for row in gen.history:
            if row["asset_id"] == "d1" and row["session"] == "race" and row["round"] in gains:
                row.update(position=1, start_position=1+gains[row["round"]], overtakes=counts[row["round"]])
        ratio = gen.gain_ratio("d1", "race")
        self.assertEqual(ratio["pool"], "driver")
        self.assertEqual(ratio["rounds"], [3, 4, 5, 6])
        self.assertAlmostEqual(ratio["q"], 6.25/11)
        values = [gen.overtakes("d1", "race", "classified", 6, 1, s) for s in range(4096)]
        self.assertEqual(set(values), {8, 9})
        self.assertAlmostEqual(sum(values)/len(values), 8.8, delta=0.03)
        self.assertTrue(gen.overtake_audit["d1/race/gain_ratio"]["extrapolated_gain"])
        self.assertEqual(values[0], gen.overtakes("d1", "race", "classified", 6, 1, 0))

    def test_flat_and_losing_finishes_keep_historical_overtakes(self):
        gen, _ = make_generator()
        for row in gen.history:
            if row["asset_id"] == "d1" and row["session"] == "race":
                row.update(position=3, start_position=2, overtakes=7)
        for start, finish in ((3, 3), (2, 5)):
            self.assertEqual(gen.overtakes("d1", "race", "classified", start, finish, 0), 7)
        for status in ("dns", "dsq"):
            self.assertEqual(gen.overtakes("d1", "race", status, 2, None, 0), 0)
        self.assertEqual(gen.overtakes("d6", "race", "nc", 2, None, 0),
                         next(r["overtakes"] for r in gen.history if r["asset_id"] == "d6" and r["status"] == "nc"))

    def test_zero_overtake_gain_history_has_zero_rate_without_division_by_zero(self):
        gen, _ = make_generator()
        for row in gen.history:
            if row["asset_id"] == "d1" and row["session"] == "race":
                row.update(position=1, start_position=3, overtakes=0)
        ratio = gen.gain_ratio("d1", "race")
        self.assertIsNone(ratio["q"])
        self.assertEqual(ratio["q_status"], "infinite")
        self.assertEqual(gen.overtakes("d1", "race", "classified", 6, 1, 0), 0)

    def test_missing_gain_ratio_borrows_team_then_field_or_uses_empirical_fallback(self):
        gen, _ = make_generator()
        for row in gen.history:
            if row["session"] == "race" and row["status"] == "classified":
                row.update(start_position=row["position"], overtakes=3)
                if row["asset_id"] == "d2":
                    row.update(position=1, start_position=3, overtakes=6)
        self.assertEqual(gen.gain_ratio("d1", "race")["pool"], "constructor")
        self.assertEqual(gen.gain_ratio("d3", "race")["pool"], "field")
        self.assertEqual(gen.overtakes("d1", "race", "classified", 4, 1, 0), 9)
        for row in gen.history:
            if row["session"] == "race" and row["status"] == "classified":
                row["start_position"] = None
        gen.overtake_cache.clear()
        self.assertEqual(gen.gain_ratio("d1", "race")["q_status"], "unavailable")
        self.assertEqual(gen.overtakes("d1", "race", "classified", 4, 1, 0), 3)

    def test_gain_ratio_does_not_mix_race_and_sprint(self):
        gen, _ = make_generator("sprint")
        for row in gen.history:
            if row["asset_id"] == "d1" and row["session"] != "qualifying":
                row.update(position=1, start_position=3, overtakes=2 if row["session"] == "race" else 6)
        self.assertEqual(gen.overtakes("d1", "race", "classified", 3, 1, 0), 2)
        self.assertEqual(gen.overtakes("d1", "sprint", "classified", 3, 1, 0), 6)

    def test_sprint_penalty_scope_and_proxy_records(self):
        gen, _ = make_generator("sprint")
        yes, _ = gen.generate({"fictional-grid-drop"})
        no, _ = gen.generate(set())
        self.assertEqual([s["sprint"] for s in yes["scenarios"]], [s["sprint"] for s in no["scenarios"]])
        self.assertIsNone(yes["metadata"]["pit_record_seconds"])
        self.assertTrue(all(not r["world_record"] for s in yes["scenarios"] for r in s["pit_stops"].values()))
        bad = copy.deepcopy(yes)
        bad["scenarios"][0]["pit_stops"]["c1"]["world_record"] = True
        with self.assertRaises(ValueError):
            core.validate_model(bad, gen.rules)

    def test_measured_record_setters_follow_stop_chronology(self):
        def measured(_, data):
            data["pit_record"] = {"seconds": 2.0, "source_ref": "input", "available_at": "2026-05-01T00:00:00Z"}
            data["pits"] = [{"round": 6, "constructor_id": f"c{i}", "mode": "measured", "had_stop": True,
                             "stationary_seconds": seconds, "source_ref": "input", "stops": [{"order": i, "seconds": seconds}]}
                            for i, seconds in enumerate((1.9, 1.8, 2.2), 1)]
        gen, _ = make_generator(configure=measured)
        model, _ = gen.generate(set())
        normal = next(s for s in model["scenarios"] if all(r["status"] != "dns" for r in s["race"].values()))
        self.assertTrue(normal["pit_stops"]["c1"]["world_record"])
        self.assertTrue(normal["pit_stops"]["c2"]["world_record"])
        self.assertTrue(normal["pit_stops"]["c2"]["fastest_of_race"])
        self.assertFalse(normal["pit_stops"]["c3"]["world_record"])

    def test_unknown_nc_start_state_requires_evidence_or_explicit_prior(self):
        def unknown(_, data):
            for row in data["history"]:
                if row["status"] in {"nc", "dns"}:
                    row["status"] = "nc"
                    row["started"] = None
        with self.assertRaisesRegex(ValueError, "NC/DNS split unavailable"):
            make_generator(configure=unknown)


class CircuitTests(unittest.TestCase):
    def test_fixed_weights_apply_to_both_sessions_without_affecting_qualifying(self):
        gen, _ = make_generator("sprint", lambda c, d: d.update(circuit_id="monaco"))
        self.assertEqual(gen.grid_weights, {"race": 0.8, "sprint": 0.8})
        self.assertEqual(gen.circuit_models["race"]["selected"]["method"], "fixed_table")
        base, _ = make_generator("sprint", lambda c, d: (
            d.update(circuit_id="monaco"), c["model_parameters"].update(circuit_difficulty=0)))
        high, _ = gen.generate(set())
        low, _ = base.generate(set())
        self.assertEqual([s["qualifying"] for s in high["scenarios"]], [s["qualifying"] for s in low["scenarios"]])
        self.assertEqual(base.grid_weights, {"race": 0.2, "sprint": 0.2})
        self.assertEqual(base.circuit_models["race"]["selected"]["table_difficulty"], 1)
        self.assertEqual(base.circuit_models["race"]["selected"]["method"], "configured_scenario")

    def test_fixed_lookup_ignores_recent_circuit_overtaking_totals(self):
        baseline, _ = make_generator(configure=lambda c, d: d.update(circuit_id="singapore"))
        def change_history(config, data):
            data["circuit_id"] = "singapore"
            for row in data["history"]:
                row["circuit_id"] = "singapore"
                if row["session"] != "qualifying" and row["status"] == "classified":
                    row["overtakes"] = 99
        changed, _ = make_generator(configure=change_history)
        self.assertEqual(changed.circuit_models, baseline.circuit_models)
        self.assertEqual(changed.grid_weights["race"], 0.68)

    def test_aliases_endpoints_and_unknown_neutral_fallback(self):
        for alias, expected in (("Bahrain International Circuit", .2), ("las-vegas", .2),
                                ("Autodromo Nazionale Monza", .2), ("Madring", .8),
                                ("Autodromo Hermanos Rodriguez", .44),
                                ("aut\u00f3dromo-hermanos-rodr\u00edguez", .44),
                                ("Circuit de Monaco", .8), ("unseen", .5)):
            with self.subTest(alias=alias):
                gen, _ = make_generator(configure=lambda c, d: d.update(circuit_id=alias))
                self.assertEqual(gen.grid_weights["race"], expected)
        self.assertEqual(gen.circuit_models["race"]["selected"]["method"], "generic_fallback")
        self.assertTrue(any("neutral 50%" in w for w in gen.warnings))
        gen, _ = make_generator(configure=lambda c, d: (d.update(circuit_id="Circuit de Monaco"), c.update(circuit_id="monaco")))
        self.assertEqual(gen.grid_weights["race"], .8)
        with self.assertRaisesRegex(ValueError, "differs"):
            make_generator(configure=lambda c, d: (d.update(circuit_id="monaco"), c.update(circuit_id="suzuka")))

    def test_table_version_audit_and_provisional_values(self):
        gen, _ = make_generator(configure=lambda c, d: d.update(circuit_id="madring"))
        audit = gen.circuit_models["race"]
        self.assertEqual(audit["selected"]["confidence"], "low")
        self.assertEqual(audit["selected"]["grid_weight"], .8)
        self.assertTrue(audit["table_version"])
        self.assertEqual(len(audit["table_content_sha256"]), 64)
        self.assertTrue(audit["sources"])
        self.assertTrue(any("retrospective" in w for w in gen.warnings))
        table = circuits.load_profiles()
        self.assertEqual(len([r for r in table["circuits"] if r["coverage"] == "2026_calendar"]), 23)
        for row in table["circuits"]:
            self.assertTrue(set(row["source_refs"]) <= {s["id"] for s in table["sources"]})
            self.assertGreaterEqual(row["difficulty"], 0)
            self.assertLessEqual(row["difficulty"], 1)

    def test_invalid_table_and_legacy_imports_fail(self):
        table = circuits.load_profiles()
        table["circuits"][0]["aliases"].append("monaco")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            circuits.profile_index(table)
        for key in ("grid_weight", "max_grid_weight", "circuit_density_floor", "circuit_factor", "overtake_bandwidth"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "replaced"):
                make_generator(configure=lambda c, d: c["model_parameters"].update({key: .2}))
        with self.assertRaisesRegex(ValueError, "circuit_history"):
            make_generator(configure=lambda c, d: d.update(circuit_history=[]))


class PriceAndBudgetTests(unittest.TestCase):
    def test_unpriced_sporting_entrant_scores_for_constructor_but_cannot_be_bought(self):
        def unpriced(config, data):
            next(a for a in data["assets"] if a["asset_id"] == "d6").update(price=None, selectable=False)
        gen, teams = make_generator(configure=unpriced)
        model, _ = gen.generate(set())
        e = pipeline.evaluated(model, gen.rules)
        self.assertIn("d6", e["scores"])
        self.assertFalse(e["price_metrics"]["d6"]["available"])
        self.assertTrue(any(r["asset_id"] == "d6" and r["price"] is None for r in e["asset_metrics"]))
        for i, scenario in enumerate(model["scenarios"]):
            race = core.driver_categories(scenario["race"]["d6"], "race", gen.rules)
            mate = core.driver_categories(scenario["race"]["d5"], "race", gen.rules)
            self.assertEqual(e["scenario_categories"][i]["c3"]["race_position"] if "race_position" in e["scenario_categories"][i]["c3"] else 0,
                             race.get("race_position", 0) + mate.get("race_position", 0))
        team = teams["teams"][0]
        result = lineups.optimize(e, team, gen.rules)
        self.assertEqual(result["budget_status"], "available")
        for choice in (result["score_best"], result["budget_best"], result["best_free"]):
            self.assertNotIn("d6", choice["asset_ids"])
        with self.assertRaisesRegex(ValueError, "non-selectable"):
            lineups.optimize(e, {**team, "required_assets": ["d6"]}, gen.rules)
        with self.assertRaisesRegex(ValueError, "selling prices"):
            lineups.optimize(e, {**team, "previous_lineup": ["d1", "d2", "d3", "d4", "d6", "c1", "c2"]}, gen.rules)
        next(a for a in model["assets"] if a["asset_id"] == "d6")["selectable"] = True
        with self.assertRaises(ValueError):
            core.validate_model(model, gen.rules)

    def test_price_expectation_maps_each_scenario_before_averaging(self):
        asset = {"price": 10, "type": "driver", "price_history": [{"round": r, "points": 0,
                 "settled_at": "2026-01-01T00:00:00Z", "source_ref": "test"} for r in (1, 2)]}
        e = {"assets": {"a": asset}, "scores": {"a": [-30, 200]}, "weights": [0.5, 0.5],
             "metadata": {"as_of": "2026-02-01T00:00:00Z", "round_number": 3}}
        result = prices.evaluate_prices(e)["a"]
        self.assertAlmostEqual(result["expected_change"], 0)
        self.assertAlmostEqual(result["p_rise"], 0.5)
        asset["price"] = 3
        result = prices.evaluate_prices(e)["a"]
        self.assertAlmostEqual(result["expected_change"], 0.3)
        self.assertEqual(result["p_fall"], 0)

    def test_global_growth_search_matches_independent_enumeration(self):
        gen, teams = make_generator()
        model, _ = gen.generate(set())
        e = pipeline.evaluated(model, gen.rules)
        team = teams["teams"][0]
        actual = lineups.optimize(e, team, gen.rules, top=1, allow=10)
        candidates = []
        means = {r["asset_id"]: r["mu"] for r in e["asset_metrics"]}
        old = set(team["previous_lineup"])
        budget = team["bank"] + sum(e["assets"][a]["price"] for a in old)
        for ds in combinations(gen.ids, 5):
            for cs in combinations([a["asset_id"] for a in gen.constructors], 2):
                ids = ds+cs
                cost = sum(e["assets"][a]["price"] for a in ids)
                if cost > budget:
                    continue
                changes = len(set(ids)-old)
                mu = sum(means[a] for a in ids)+max(means[a] for a in ds)-10*max(0, changes-team["free_transfers"])
                growth = sum(e["price_metrics"][a]["expected_change"] for a in ids)
                candidates.append((mu, growth, changes, cost, ids))
        best = max(row[0] for row in candidates)
        eligible = [r for r in candidates if r[0] >= best-10-1e-9]
        expected = max(eligible, key=lambda r: (round(r[1], 12), r[0], -r[2], -r[3], r[4]))
        self.assertAlmostEqual(actual["mu_best"], best)
        self.assertEqual(set(actual["budget_best"]["asset_ids"]), set(expected[4]))
        zero = lineups.optimize(e, team, gen.rules, allow=0)
        self.assertAlmostEqual(zero["budget_best"]["mu"], zero["mu_best"])

    def test_missing_price_history_disables_growth_not_score_prediction(self):
        gen, teams = make_generator()
        model, _ = gen.generate(set())
        model["assets"][0]["price_history"] = []
        e = pipeline.evaluated(model, gen.rules)
        result = lineups.optimize(e, teams["teams"][0], gen.rules)
        self.assertEqual(result["budget_status"], "unavailable")
        self.assertIsNone(result["budget_best"])
        self.assertIsNotNone(result["score_best"])

    def test_old_price_history_is_not_used_as_latest_two_rounds(self):
        gen, _ = make_generator()
        model, _ = gen.generate(set())
        model["assets"][0]["price_history"][0]["round"] = 3
        result = pipeline.evaluated(model, gen.rules)
        self.assertFalse(result["price_metrics"][model["assets"][0]["asset_id"]]["available"])

    def test_allow_rejects_negative_nonfinite_and_boolean(self):
        gen, teams = make_generator()
        model, _ = gen.generate(set())
        e = pipeline.evaluated(model, gen.rules)
        for bad in (-1, float("inf"), float("nan"), True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                lineups.optimize(e, teams["teams"][0], gen.rules, allow=bad)


class DataAndRunTests(unittest.TestCase):
    def test_practice_table_retains_reserve_position_and_missing_rank(self):
        _, data, _ = example.example_data()
        html = '<title>2026 Test Practice 2</title><table><tr><th>Pos.</th><th>No.</th><th>Driver</th><th>Team</th></tr><tr><td>1</td><td>99</td><td>Reserve Driver RES</td><td>Team</td></tr><tr><td>2</td><td>1</td><td>Demo Driver 1 DEM</td><td>Team</td></tr><tr><td>NC</td><td>2</td><td>Demo Driver 2 DEM</td><td>Team</td></tr></table>'
        rows = data_module.practice_table(html, {"session": "fp2", "completed_at": "2026-05-31T00:00:00Z", "title_contains": ["2026", "Practice 2"]}, data["assets"], "test")
        self.assertIsNone(rows[0]["asset_id"])
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[1]["field_size"], 3)
        self.assertIsNone(rows[2]["rank"])

    def test_event_sum_sparse_zero_and_unknown_event(self):
        events, total = data_module.event_map([{"Event": "Qualifying Position", "Frequency": "16th", "Value": 0}])
        self.assertEqual(total, 0)
        self.assertEqual(events["qualifying position"]["Frequency"], "16th")
        with self.assertRaisesRegex(ValueError, "unknown"):
            data_module.event_map([{"Event": "New unexplained bonus", "Value": 5}])
        with self.assertRaisesRegex(ValueError, "differs"):
            data_module.event_map([{"Event": "Total", "Value": 1}, {"Event": "Race Position", "Value": 25}])

    def test_public_history_keeps_sparse_zero_and_recognizes_mislabeled_sprint(self):
        config, data, _ = example.example_data()
        config["field_size"] = 22
        raw = {"RaceDayId": "1", "MatchStatus": "4", "IsPlayed": "1", "Season": 2026,
               "CircuitOfficialName": "Synthetic Test Circuit",
               "SessionStartDate": "2026-05-01T00:00:00Z", "SessionType": "Sprint Qualifying",
               "StatsWise": [{"Event": "Sprint Position", "Frequency": "16th", "Value": 0}]}
        game = {"GamedayId": "1", "IsActive": "1", "IsPlayed": "1", "PlayerValue": 10,
                "StatsWise": [{"Event": "Total", "Frequency": "", "Value": 0}]}
        payload = {"Value": {"FixtureWiseStats": [{"GamedayId": "1", "RaceDayWise": [raw]}],
                             "GamedayWiseStats": [game],
                             "MatchWiseStats": [{"GamedayId": "1", "RaceDayWise": [raw]}]}}
        quality = []
        history, _, weekends, _ = data_module.normalize_history(data["assets"][0], payload, config, "input", quality)
        self.assertEqual(history[0]["session"], "sprint")
        self.assertEqual(history[0]["circuit_id"], "synthetic-test-circuit")
        self.assertEqual(history[0]["overtakes"], 0)
        self.assertEqual(history[0]["start_position"], 16)
        self.assertEqual(weekends[0]["points"], 0)
        raw["StatsWise"].append({"Event": "Sprint Position Lost", "Frequency": "10", "Value": -10})
        game["StatsWise"] = []
        history, _, weekends, _ = data_module.normalize_history(data["assets"][0], payload, config, "input", quality)
        self.assertIsNone(history[0]["start_position"])
        self.assertEqual(weekends, [])
        self.assertTrue(any("Empty settled" in message for message in quality))

    def test_snapshot_after_cutoff_and_offline_fetch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "input.json").write_text("{}")
            sources = io_module.Sources(path, path / "output", "2026-01-01T00:00:00Z", offline=True)
            with self.assertRaisesRegex(ValueError, "after cutoff"):
                sources.read({"path": "input.json", "source_ref": "test", "observed_at": "2026-02-01T00:00:00Z"}, "input")
            with self.assertRaisesRegex(ValueError, "offline"):
                sources.read({"url": "https://example.invalid/data"}, "input")

    def test_end_to_end_standard_sprint_and_reproducibility(self):
        for format in ("standard", "sprint"):
            with self.subTest(format=format), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                example.write_run_example(root / "inputs", format)
                config_path = root / "inputs/run_config.json"
                config = core.load_json(config_path)
                config["model_parameters"]["samples"] = 24
                io_module.save_json(config_path, config)
                out = pipeline.run(config_path, root / "one", offline=True)
                self.assertEqual(out["status"], "complete")
                self.assertEqual(len(out["teams"]), 3)
                pipeline.run(config_path, root / "two", offline=True)
                self.assertEqual(core.load_json(root / "one/forecast.json"), core.load_json(root / "two/forecast.json"))
                audit = core.load_json(root / "one/model_parameters.json")
                self.assertEqual(audit["circuit_models"]["race"]["selected"]["method"], "generic_fallback")
                self.assertTrue(audit["overtake_models"])
                self.assertNotIn("conditional_overtakes", audit)
                for name in ("advisor_input.json", "expected_driver_positions.csv", "sources.json", "grid_penalty_impacts.json", "price_distributions.json", "run_manifest.json", "circuit_profiles.json"):
                    self.assertTrue((root / "one" / name).is_file())
                advisor = core.load_json(root / "one/advisor_input.json")
                with (root / "one/expected_driver_positions.csv").open(newline="", encoding="utf-8") as handle:
                    position_rows = list(csv.DictReader(handle))
                self.assertEqual(len(position_rows), 6)
                self.assertEqual(len(advisor["driver_positions"]), 6)
                self.assertEqual("mean_sprint_start_position" in position_rows[0], format == "sprint")
                self.assertEqual(advisor["driver_positions"], pipeline.driver_position_means(core.load_json(root / "one/forecast.json")))
                with self.assertRaisesRegex(ValueError, "not empty"):
                    pipeline.run(config_path, root / "one", offline=True)

    def test_failed_run_preserves_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example.write_run_example(root / "inputs")
            config_path = root / "inputs/run_config.json"
            config = core.load_json(config_path)
            config["model_parameters"]["temperature"] = 0
            io_module.save_json(config_path, config)
            with self.assertRaises(ValueError):
                pipeline.run(config_path, root / "run", offline=True)
            self.assertEqual(core.load_json(root / "run/run_manifest.json")["status"], "failed")

    def test_run_pins_and_snapshots_a_local_circuit_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example.write_run_example(root / "inputs")
            config_path = root / "inputs/run_config.json"
            config = core.load_json(config_path)
            config.update(circuit_id="monaco", circuit_profiles_path="frozen-circuits.json")
            config["model_parameters"]["samples"] = 8
            io_module.save_json(config_path, config)
            table = circuits.load_profiles()
            table["version"] = "test-frozen-revision"
            next(r for r in table["circuits"] if r["circuit_id"] == "monaco")["difficulty"] = .5
            io_module.save_json(root / "inputs/frozen-circuits.json", table)
            pipeline.run(config_path, root / "result", offline=True)
            self.assertEqual(core.load_json(root / "result/circuit_profiles.json"), table)
            audit = core.load_json(root / "result/model_parameters.json")["circuit_models"]["race"]
            self.assertEqual(audit["table_version"], "test-frozen-revision")
            self.assertEqual(audit["selected"]["grid_weight"], .5)
            expected = circuits.circuit_models("monaco", "standard", None, table)["race"]
            self.assertEqual(audit["table_content_sha256"], expected["table_content_sha256"])
            self.assertFalse((root / "result/circuit_history.json").exists())

    def test_probability_weighted_penalty_branches_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example.write_run_example(root / "inputs")
            config_path = root / "inputs/run_config.json"
            config = core.load_json(config_path)
            config["model_parameters"]["samples"] = 16
            io_module.save_json(config_path, config)
            data_path = root / "inputs/inputs.json"
            data = core.load_json(data_path)
            data["grid"]["events"][0].update(status="expected", probability=0.75,
                                               probability_method="Synthetic test assumption", probability_source="input")
            io_module.save_json(data_path, data)
            pipeline.run(config_path, root / "run", offline=True)
            report = core.load_json(root / "run/grid_penalty_impacts.json")
            evaluation = core.load_json(root / "run/evaluation.json")
            advisor = core.load_json(root / "run/advisor_input.json")
            self.assertEqual(advisor["driver_positions"], pipeline.driver_position_means(core.load_json(root / "run/forecast.json")))
            for asset in evaluation["asset_metrics"]:
                expected = sum(b["probability"]*b["assets"][asset["asset_id"]]["mu"] for b in report["branches"])
                self.assertAlmostEqual(asset["mu"], expected)


if __name__ == "__main__":
    unittest.main()
