"""End-to-end v1 forecasts with cached evidence and per-team budget optimization."""

from collections import defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from forecast_core import evaluate_model, integer, load_json, load_rules, number, timestamp
from forecast_data import collect_public, identity
from forecast_generate import Generator
from forecast_grid import branches
from forecast_io import Sources, save_csv, save_json
from forecast_lineups import optimize
from forecast_prices import PRICE_MODEL_VERSION, evaluate_prices

REFERENCES = Path(__file__).resolve().parents[1] / "references"


def load_teams(path, v1=False):
    if path is None:
        return []
    data = load_json(path)
    rows = data.get("teams")
    if data.get("schema_version") != 1 or not isinstance(rows, list) or not rows:
        raise ValueError("teams file requires schema_version=1 and a nonempty teams list")
    ids = [r.get("team_id") for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("team ids must be nonempty and unique")
    if v1 and any(r.get("chip", "none") != "none" for r in rows):
        raise ValueError("v1 run supports ordinary 2x only; active chips require the separate scenario workflow")
    return rows


def evaluated(model, rules):
    result = evaluate_model(model, rules)
    result["price_metrics"] = evaluate_prices(result)
    for row in result["asset_metrics"]:
        price = result["price_metrics"][row["asset_id"]]
        row.update(expected_price_change=price.get("expected_change"), p_rise=price.get("p_rise"),
                   p_fall=price.get("p_fall"), price_available=price["available"])
    return result


def write_evaluation(output, result):
    save_csv(output / "expected_assets.csv", result["asset_metrics"])
    save_csv(output / "component_probabilities.csv", result["component_distributions"])
    save_json(output / "asset_score_distributions.json", result["score_distributions"])
    save_json(output / "price_distributions.json", result["price_metrics"])
    save_json(output / "evaluation.json", {k: result[k] for k in
              ("metadata", "asset_metrics", "component_distributions", "score_distributions", "price_metrics", "warnings")})


def optimize_teams(result, teams, rules, allow):
    return [optimize(result, team, rules, allow=allow) for team in teams]


def outcome_summary(model, evaluation):
    result = {}
    for asset in model["assets"]:
        aid = asset["asset_id"]
        if aid not in evaluation["scores"]:
            continue
        row = {"mu": next(r["mu"] for r in evaluation["asset_metrics"] if r["asset_id"] == aid),
               "expected_price_change": evaluation["price_metrics"][aid].get("expected_change")}
        contributions = defaultdict(float)
        for component in evaluation["component_distributions"]:
            if component["asset_id"] == aid:
                contributions[component["category"]] += component["mu_contribution"]
        row["contributions"] = dict(contributions)
        if asset["type"] == "driver":
            for session in ("race", "sprint"):
                if session not in model["scenarios"][0]:
                    continue
                starts, finishes = defaultdict(float), defaultdict(float)
                top5 = top10 = 0.0
                for s in model["scenarios"]:
                    r, p = s[session][aid], s["probability"]
                    starts[str(r["start_position"])] += p
                    finishes[str(r["position"]) if r["position"] else r["status"]] += p
                    top5 += p*(r["position"] is not None and r["position"] <= 5)
                    top10 += p*(r["position"] is not None and r["position"] <= 10)
                row[session] = {"start_distribution": dict(starts), "finish_distribution": dict(finishes),
                                "p_top5": top5, "p_top10": top10}
        result[aid] = row
    return result


def impact_difference(with_penalty, without_penalty):
    result = {}
    for aid, row in with_penalty.items():
        old = without_penalty[aid]
        keys = row["contributions"].keys() | old["contributions"].keys()
        result[aid] = {"mu_change": row["mu"]-old["mu"],
                       "price_change_difference": None if row["expected_price_change"] is None or old["expected_price_change"] is None else row["expected_price_change"]-old["expected_price_change"],
                       "contribution_changes": {k: row["contributions"].get(k, 0)-old["contributions"].get(k, 0) for k in sorted(keys)}}
    return result


def run(config_path, out_dir, teams_path=None, allow=None, offline=False):
    config_path, output = Path(config_path).resolve(), Path(out_dir).resolve()
    config = load_json(config_path)
    if config.get("schema_version") != 1:
        raise ValueError("run config requires schema_version=1")
    integer(config.get("season"), "season", 2000)
    integer(config.get("target_round"), "target_round", 1)
    if config.get("format") not in {"standard", "sprint"}:
        raise ValueError("format must be standard or sprint")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory is not empty; choose a new run directory")
    output.mkdir(parents=True, exist_ok=True)
    base = config_path.parent
    live_cutoff = "as_of" not in config
    if live_cutoff:
        if datetime.now(timezone.utc) >= timestamp(config.get("lock_at"), "lock_at"):
            raise ValueError("cannot start a live forecast after lock")
        config["as_of"] = config["lock_at"]  # Freeze to the acquisition end time below.
    elif timestamp(config["as_of"], "as_of") >= timestamp(config.get("lock_at"), "lock_at"):
        raise ValueError("as_of must precede lock_at")
    sources = Sources(base, output, config["as_of"], offline)
    manifest = {"status": "running", "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest()}
    try:
        rules = load_rules(base / config["rules_path"] if config.get("rules_path") else REFERENCES / f"scoring-{config['season']}.json")
        if config["season"] != rules["season"]:
            raise ValueError("target and scoring rule seasons differ")
        config["field_size"] = rules["field_size"]
        grid_path = base / config["grid_rules_path"] if config.get("grid_rules_path") else REFERENCES / f"grid-rules-{config['season']}.json"
        grid_rules = load_json(grid_path) if grid_path.exists() else {}
        for source_id, descriptor in config.get("sources", {}).items():
            sources.read(descriptor, source_id, descriptor.get("format", "html") == "json")
        if ("input" in config) == ("public" in config):
            raise ValueError("choose exactly one normalized input or public collection config")
        data = sources.read(config["input"], "input") if "input" in config else collect_public(config, sources)
        if "circuit_history_input" in config:
            raise ValueError("circuit_history_input was replaced by references/circuit-profiles.json; remove the legacy import")
        for key, target_key in (("news_input", "news"), ("grid_input", "grid"), ("history_prior_input", "priors")):
            if key in config:
                data[target_key] = sources.read(config[key], key)
        if live_cutoff:
            config["as_of"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if timestamp(config["as_of"], "as_of") >= timestamp(config["lock_at"], "lock_at"):
            raise ValueError("data acquisition finished after lock")
        for asset in data["assets"]:
            asset.setdefault("person_id", identity(asset["name"]) if asset["type"] == "driver" else None)
        if data.get("weekends"):
            config["previous_rounds"] = sorted({row["round"] for row in data["weekends"]})[-2:]
        config["allow"] = number(config.get("allow", 10) if allow is None else allow, "allow", 0)
        teams = load_teams(teams_path or (base / config["teams"] if config.get("teams") else None), v1=True)
        circuit_path = base / config["circuit_profiles_path"] if config.get("circuit_profiles_path") else None
        generator = Generator(data, config, rules, grid_rules, sources.rows, circuit_path)
        plan, weighted = branches(data.get("grid", {}), generator.events)
        if not weighted:
            generator.warnings.add("Expected penalties have no joint probability; main result includes confirmed penalties only, inspect conditional branches")
        if any(team.get("state_status") == "simulation_only" for team in teams):
            generator.warnings.add("Replay team states are simulation inputs, not the user's current submitted lineups")
        branch_reports, models = [], []
        summaries = {}
        for branch in plan:
            model, traffic = generator.generate(branch["active"])
            result = evaluated(model, rules)
            lineups = optimize_teams(result, teams, rules, config["allow"])
            summary = outcome_summary(model, result)
            summaries[frozenset(branch["active"])] = summary
            report = {"id": branch["id"], "active_events": sorted(branch["active"]),
                      "probability": branch["probability"] if weighted else None,
                      "assets": summary, "teams": lineups, "traffic": traffic}
            branch_reports.append(report)
            if len(plan) > 1:
                save_json(output / "branches" / branch["id"] / "summary.json", report)
            if weighted:
                models.append((model, branch["probability"]))
            elif branch == plan[0]:
                main_model, main_result, main_lineups = model, result, lineups
        if weighted:
            main_model = models[0][0]
            if len(models) > 1:
                combined = []
                for index, (model, weight) in enumerate(models):
                    if weight == 0:
                        continue
                    for scenario in model["scenarios"]:
                        scenario["id"] = f"b{index}_{scenario['id']}"
                        scenario["probability"] *= weight
                        combined.append(scenario)
                main_model["scenarios"] = combined
                main_model["metadata"]["penalty_mixture"] = [{"active_events": r["active_events"], "probability": r["probability"]} for r in branch_reports]
                main_model["metadata"]["active_penalties"] = None
            main_result = evaluated(main_model, rules)
            main_lineups = optimize_teams(main_result, teams, rules, config["allow"])
        confirmed = {r["event_id"] for r in generator.events if r["status"] == "confirmed"}
        impacts = []
        for event in generator.events:
            if data.get("grid", {}).get("official_orders"):
                impacts.append({"event_id": event["event_id"], "status": "unavailable",
                                "reason": "Official fixed grid cannot be inverted into an unpenalized grid; supply a pre-penalty simulation input for paired attribution"})
                continue
            yes, no = frozenset(confirmed | {event["event_id"]}), frozenset(confirmed - {event["event_id"]})
            for active in (yes, no):
                if active not in summaries:
                    model, _ = generator.generate(active, use_official=False)
                    summaries[active] = outcome_summary(model, evaluated(model, rules))
            impacts.append({"event_id": event["event_id"], "asset_id": event["asset_id"], "session": event["session"],
                            "status": event["status"], "source_ref": event["source_ref"],
                            "with_penalty": summaries[yes], "without_penalty": summaries[no],
                            "changes": impact_difference(summaries[yes], summaries[no])})
        save_json(output / "forecast.json", main_model)
        write_evaluation(output, main_result)
        save_json(output / "lineups.json", {"metadata": main_model["metadata"], "teams": main_lineups})
        save_json(output / "grid_penalty_impacts.json", {"weighted_branches": weighted, "branches": branch_reports, "impacts": impacts})
        save_json(output / "model_parameters.json", {"parameters": generator.parameters, "models": generator.audit,
                                                     "circuit_models": generator.circuit_models,
                                                     "overtake_models": generator.overtake_audit})
        save_json(output / "circuit_profiles.json", generator.circuit_profiles)
        save_csv(output / "practice_adjustments.csv", generator.adjustments)
        save_json(output / "assets.json", data["assets"])
        for filename, rows in (("history_sessions.csv", generator.history), ("history_events.csv", data.get("events", [])),
                               ("history_weekends.csv", data.get("weekends", [])), ("practice_results.csv", data.get("practice", [])),
                               ("pit_stops.csv", data.get("pits", []))):
            save_csv(output / filename, rows)
        save_json(output / "news_adjustments.json", data.get("news", []))
        save_json(output / "grid_adjustments.json", data.get("grid", {}))
        quality = sorted(generator.warnings)
        if len(teams) < 3:
            quality.append("Fewer than three team states supplied; no missing account state was inferred")
        brief = {"metadata": main_model["metadata"], "allow": config["allow"], "assets": main_result["asset_metrics"],
                 "teams": main_lineups, "practice_adjustments": generator.adjustments,
                 "penalties": generator.events, "penalty_impacts": [{"event_id": r["event_id"], "status": r["status"], "changes": r.get("changes"), "reason": r.get("reason")} for r in impacts],
                 "news": data.get("news", []), "sources": sources.rows, "warnings": quality,
                 "files": {name: str(output / name) for name in ("forecast.json", "component_probabilities.csv", "model_parameters.json", "grid_penalty_impacts.json")}}
        save_json(output / "advisor_input.json", brief)
        save_json(output / "data_quality.json", {"status": "complete", "warnings": quality})
        save_json(output / "run_config.json", config)
        save_json(output / "scoring_rules.json", rules)
        save_json(output / "grid_rules.json", grid_rules)
        if teams:
            save_json(output / "teams.json", {"schema_version": 1, "teams": teams})
        manifest.update(status="complete", parameters=generator.parameters, rules_version=rules["version"],
                        grid_rules_version=grid_rules.get("version"), price_model_version=PRICE_MODEL_VERSION,
                        code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))})
        return {"status": "complete", "output_directory": str(output), "model_status": main_model["metadata"]["model_status"],
                "scenarios": len(main_model["scenarios"]), "teams": [{"team_id": t["team_id"], "mu_best": t["mu_best"],
                "budget_status": t["budget_status"], "recommended": t["recommended"]} for t in main_lineups],
                "advisor_input": str(output / "advisor_input.json"), "warnings": quality}
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        save_json(output / "data_quality.json", {"status": "failed", "error": str(exc)})
        raise
    finally:
        save_json(output / "sources.json", sources.rows)
        save_json(output / "run_manifest.json", manifest)
