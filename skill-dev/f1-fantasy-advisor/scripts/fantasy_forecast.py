#!/usr/bin/env python3
"""Evaluate auditable race forecasts, component probabilities, and legal lineups."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
from pathlib import Path

from forecast_core import (DEFAULT_RULES, PROBABILITY_COMPONENTS, SPRINT_COMPONENTS,
                           evaluate_model, load_json, load_rules, validate_model)
from forecast_lineups import optimize
from forecast_probabilities import calibration_report, estimate_categorical
from forecast_run import evaluated, load_teams, run, write_evaluation


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def demo_model(sprint=False):
    """Small coherent field for exercising the tool, never a real forecast."""
    assets = []
    for index, price in enumerate((28, 22, 18, 10, 8, 5), 1):
        assets.append({"asset_id": f"d{index}", "name": f"Demo Driver {index}", "type": "driver",
                       "price": price, "constructor_id": f"c{(index + 1) // 2}"})
    for index, price in enumerate((18, 16, 12), 1):
        assets.append({"asset_id": f"c{index}", "name": f"Demo Constructor {index}",
                       "type": "constructor", "price": price})
    metadata = {"season": 2026, "rules_version": "f1-fantasy-2026-v1", "target_round": "SYNTHETIC_DEMO",
                "synthetic": True, "prices_observed_at": "2026-01-01T00:00:00Z",
                "pit_record_seconds": 1.8, "pit_record_source": "Synthetic example, not race data",
                "format": "sprint" if sprint else "standard", "as_of": "2026-01-01T00:00:00Z",
                "lock_at": "2026-01-02T00:00:00Z", "model_status": "scenario",
                "method": "Synthetic tutorial; probabilities are invented for demonstration only.",
                "evidence": [{"source": "Synthetic example, not race data", "observed_at": "2026-01-01T00:00:00Z"}]}
    components = PROBABILITY_COMPONENTS | (SPRINT_COMPONENTS if sprint else set())
    metadata["probability_models"] = {
        component: {"method": "manual_scenario", "source_refs": [metadata["evidence"][0]["source"]],
                    "sample_count": 0, "effective_sample_size": 0,
                    "parameters": {"weights": [0.65, 0.25, 0.10], "reason": "Fictional tutorial only"}}
        for component in sorted(components)}
    scenarios = []
    for n, probability in enumerate((0.65, 0.25, 0.10)):
        order = [f"d{i}" for i in ([1, 2, 3, 4, 5, 6] if n != 1 else [3, 2, 1, 5, 4, 6])]
        qualifying = {aid: {"status": "classified", "position": rank, "q2": True, "q3": rank <= 4}
                      for rank, aid in enumerate(order, 1)}
        classified = [aid for aid in order if not (n == 2 and aid == "d1")]
        race = {}
        for rank, aid in enumerate(order, 1):
            nc = aid not in classified
            race[aid] = {"status": "nc" if nc else "classified", "start_position": rank,
                         "position": None if nc else classified.index(aid) + 1,
                         "overtakes": 1 if nc else (rank + n) % 4,
                         "fastest_lap": aid == classified[0], "driver_of_day": aid == classified[1]}
        scenario = {"id": f"s{n + 1}", "probability": probability, "qualifying": qualifying, "race": race,
                    "pit_stops": {f"c{i}": {"fastest_stop_seconds": t, "fastest_of_race": i == 1,
                                             "world_record": False}
                                  for i, t in enumerate((2.1, 2.3, 2.6), 1)}}
        if sprint:
            scenario["sprint"] = copy.deepcopy(race)
            for result in scenario["sprint"].values():
                result["driver_of_day"] = False
        scenarios.append(scenario)
    return {"schema_version": 1, "metadata": metadata, "assets": assets, "scenarios": scenarios}


def write_example(path, sprint=False):
    path.mkdir(parents=True, exist_ok=True)
    names = ("forecast.json", "teams.json", "probability_input.json", "calibration_input.json")
    if any((path / name).exists() for name in names):
        raise ValueError("example files already exist; choose a new output directory")
    save_json(path / names[0], demo_model(sprint))
    save_json(path / names[1], {"schema_version": 1, "teams": [
        {"team_id": "DemoT1", "previous_lineup": ["d1", "d2", "d3", "d4", "d5", "c1", "c2"], "bank": 1, "free_transfers": 2},
        {"team_id": "DemoT2", "previous_lineup": ["d2", "d3", "d4", "d5", "d6", "c1", "c3"], "bank": 4, "free_transfers": 2},
        {"team_id": "DemoT3", "previous_lineup": ["d1", "d3", "d4", "d5", "d6", "c2", "c3"], "bank": 2, "free_transfers": 3}]})
    save_json(path / names[2], {
        "schema_version": 1, "target": {"round": 4, "as_of": "2026-04-01T00:00:00Z"}, "half_life_rounds": 4,
        "prior": {"probabilities": {"classified": 0.90, "nc": 0.09, "dsq": 0.01}, "strength": 5,
                  "source": "Synthetic demonstration prior, NOT an F1 base rate", "available_at": "2026-01-01T00:00:00Z"},
        "observations": [
            {"id": "demo1", "round": 1, "observed_at": "2026-03-01T00:00:00Z", "source": "synthetic", "outcome": "classified"},
            {"id": "demo2", "round": 2, "observed_at": "2026-03-10T00:00:00Z", "source": "synthetic", "outcome": "nc"},
            {"id": "demo3", "round": 3, "observed_at": "2026-03-20T00:00:00Z", "source": "synthetic", "outcome": "classified"}]})
    save_json(path / names[3], {"schema_version": 1, "predictions": [
        {"id": "demo1", "round": 1, "source": "Synthetic frozen prediction",
         "trained_through": "2026-01-01T00:00:00Z", "as_of": "2026-03-01T00:00:00Z",
         "lock_at": "2026-03-02T00:00:00Z", "outcome_known_at": "2026-03-03T00:00:00Z",
         "probabilities": {"classified": 0.8, "nc": 0.2}, "actual": "classified"}]})
    return {"example_directory": str(path), "warning": "Synthetic data only; not recommendations or calibrated priors."}


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    example = commands.add_parser("example", help="Generate synthetic runnable inputs; no real predictions")
    example.add_argument("--out-dir", type=Path, required=True)
    example.add_argument("--format", choices=("standard", "sprint"), default="standard")
    example_run = commands.add_parser("example-run", help="Generate synthetic raw statistical inputs for the full v1 pipeline")
    example_run.add_argument("--out-dir", type=Path, required=True)
    example_run.add_argument("--format", choices=("standard", "sprint"), default="standard")
    pipeline = commands.add_parser("run", help="Acquire/normalize evidence, generate scenarios and optimize points plus budget")
    pipeline.add_argument("--config", type=Path, required=True)
    pipeline.add_argument("--out-dir", type=Path, required=True)
    pipeline.add_argument("--teams", type=Path)
    pipeline.add_argument("--allow", type=float)
    pipeline.add_argument("--offline", action="store_true")
    for command in ("validate", "evaluate", "optimize"):
        sub = commands.add_parser(command)
        sub.add_argument("forecast", type=Path)
        sub.add_argument("--rules", type=Path, default=DEFAULT_RULES)
        if command == "evaluate":
            sub.add_argument("--out-dir", type=Path)
        if command == "optimize":
            sub.add_argument("--teams", type=Path, required=True)
            sub.add_argument("--top", type=int, default=5)
            sub.add_argument("--out", type=Path)
            sub.add_argument("--allow", type=float, default=10)
    for command in ("estimate", "calibrate"):
        sub = commands.add_parser(command)
        sub.add_argument("input", type=Path)
        sub.add_argument("--out", type=Path)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "example":
            output = write_example(args.out_dir, args.format == "sprint")
        elif args.command == "example-run":
            from forecast_example import write_run_example
            output = write_run_example(args.out_dir, args.format)
        elif args.command == "run":
            output = run(args.config, args.out_dir, args.teams, args.allow, args.offline)
        elif args.command in {"estimate", "calibrate"}:
            output = (estimate_categorical if args.command == "estimate" else calibration_report)(load_json(args.input))
        else:
            model, rules = load_json(args.forecast), load_rules(args.rules)
            if args.command == "validate":
                _, drivers, constructors = validate_model(model, rules)
                output = {"valid": True, "drivers": len(drivers), "constructors": len(constructors),
                          "scenarios": len(model["scenarios"]), "model_status": model["metadata"]["model_status"],
                          "warning": "Validation checks coherence and provenance fields, not predictive accuracy."}
            else:
                evaluation = evaluated(model, rules)
                if args.command == "evaluate":
                    output = {key: evaluation[key] for key in ("metadata", "asset_metrics", "component_distributions", "score_distributions", "price_metrics", "warnings")}
                    if args.out_dir:
                        args.out_dir.mkdir(parents=True, exist_ok=True)
                        write_evaluation(args.out_dir, evaluation)
                else:
                    teams = load_teams(args.teams)
                    output = {"metadata": model["metadata"], "teams": [optimize(evaluation, team, rules, args.top, args.allow) for team in teams]}
        if getattr(args, "out", None):
            save_json(args.out, output)
        print(json.dumps(output, ensure_ascii=True, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
