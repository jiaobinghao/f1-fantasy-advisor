#!/usr/bin/env python3
"""Validated joint scenarios and deterministic F1 Fantasy scoring."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parents[1] / "references/scoring-2026.json"
STATUSES = {"classified", "nc", "dns", "dsq"}
PROBABILITY_COMPONENTS = {"qualifying", "race_classification", "race_order", "race_overtakes",
                          "race_fastest_lap", "driver_of_day", "pit_stops"}
SPRINT_COMPONENTS = {"sprint_classification", "sprint_order", "sprint_overtakes", "sprint_fastest_lap"}


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def number(value, label, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{label} outside [{minimum}, {maximum}]")
    return value


def integer(value, label, minimum=0, maximum=None):
    number(value, label, minimum, maximum)
    if not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def timestamp(value, label):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{label} needs a timezone")
    return result


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_rules(path=DEFAULT_RULES):
    rules = load_json(path)
    for key in ("version", "season", "verified_on", "sources", "qualifying_progress", "pit_bands"):
        if not rules.get(key):
            raise ValueError(f"rules missing {key}")
    integer(rules["season"], "rules.season", 2000)
    for key in ("field_size", "max_q2", "max_q3"):
        integer(rules.get(key), f"rules.{key}", 1)
    if not rules["max_q3"] <= rules["max_q2"] <= rules["field_size"]:
        raise ValueError("qualifying capacities must fit the field")
    for session in ("qualifying", "race", "sprint"):
        values = rules.get(f"{session}_points")
        if not isinstance(values, list) or not values:
            raise ValueError(f"rules missing {session}_points")
        for value in values:
            number(value, f"rules.{session}_points", 0)
        number(rules[f"{session}_nc"], f"rules.{session}_nc", maximum=0)
        number(rules[f"{session}_constructor_dsq_extra"], f"rules.{session}_dsq", maximum=0)
    for key in ("race_fastest_lap", "sprint_fastest_lap", "driver_of_day", "fastest_pit_bonus",
                "pit_record_bonus", "extra_transfer_penalty"):
        number(rules[key], f"rules.{key}", 0)
    integer(rules["sprint_positions_lost_cap"], "sprint_positions_lost_cap", 0)
    for key in ("none_q2", "one_q2", "both_q2", "one_q3", "both_q3"):
        number(rules["qualifying_progress"][key], f"qualifying_progress.{key}")
    previous = 0
    for band in rules["pit_bands"]:
        boundary = number(band["below_seconds"], "pit boundary", 0)
        if boundary <= previous:
            raise ValueError("pit boundaries must be increasing")
        previous = boundary
        number(band["points"], "pit points", 0)
    return rules


def metadata_check(meta, rules):
    mapping(meta, "metadata")
    required = ("season", "target_round", "format", "as_of", "lock_at", "model_status",
                "method", "evidence", "rules_version", "prices_observed_at", "probability_models",
                "pit_record_seconds", "pit_record_source")
    if any(key not in meta for key in required):
        raise ValueError("metadata requires " + ", ".join(required))
    if meta["season"] != rules["season"] or meta["rules_version"] != rules["version"]:
        raise ValueError("season/rules_version mismatch; review a season-specific rules file")
    if meta["format"] not in {"standard", "sprint"}:
        raise ValueError("format must be standard or sprint")
    as_of = timestamp(meta["as_of"], "as_of")
    if timestamp(meta["prices_observed_at"], "prices_observed_at") > as_of:
        raise ValueError("prices cannot be observed after the forecast cutoff")
    if not isinstance(meta.get("synthetic", False), bool):
        raise ValueError("synthetic must be boolean")
    if meta.get("synthetic") and meta["model_status"] != "scenario":
        raise ValueError("synthetic examples must be labeled scenario")
    if as_of >= timestamp(meta["lock_at"], "lock_at"):
        raise ValueError("pre-lock forecasts require as_of < lock_at; Final Fix is a separate workflow")
    if meta["model_status"] not in {"baseline", "scenario", "calibrated"}:
        raise ValueError("model_status must be baseline, scenario or calibrated")
    if not isinstance(meta["method"], str) or not meta["method"].strip():
        raise ValueError("method must describe how probabilities were estimated")
    if not meta["target_round"] or not isinstance(meta["evidence"], list) or not meta["evidence"]:
        raise ValueError("target_round and probability evidence are required")
    for item in meta["evidence"]:
        mapping(item, "evidence item")
        if not isinstance(item.get("source"), str) or not item["source"].strip():
            raise ValueError("each evidence item needs a source")
        if timestamp(item.get("observed_at"), "evidence.observed_at") > as_of:
            raise ValueError("evidence is later than the forecast cutoff")
    sources = {item["source"] for item in meta["evidence"]}
    if meta.get("pit_mode", "measured") not in {"measured", "band_proxy"}:
        raise ValueError("pit_mode must be measured or band_proxy")
    if meta["pit_record_seconds"] is None:
        if meta.get("pit_record_status") != "unavailable" or meta["pit_record_source"] is not None:
            raise ValueError("missing pit record requires explicit unavailable status and null source")
    else:
        if number(meta["pit_record_seconds"], "pit_record_seconds", 0) <= 0:
            raise ValueError("pit_record_seconds must be positive")
        if meta["pit_record_source"] not in sources:
            raise ValueError("pit_record_source must be documented in evidence")
    if meta.get("pit_mode") == "band_proxy" and meta["pit_record_seconds"] is not None:
        raise ValueError("band proxies cannot estimate world records")
    audits = mapping(meta["probability_models"], "probability_models")
    components = PROBABILITY_COMPONENTS | (SPRINT_COMPONENTS if meta["format"] == "sprint" else set())
    if set(audits) != components:
        raise ValueError("probability_models requires exactly: " + ", ".join(sorted(components)))
    for component, audit in audits.items():
        mapping(audit, f"probability_models.{component}")
        if not isinstance(audit.get("method"), str) or not audit["method"].strip():
            raise ValueError(f"{component} requires an estimation method")
        refs = audit.get("source_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or s not in sources for s in refs):
            raise ValueError(f"{component} requires source_refs found in evidence")
        n = integer(audit.get("sample_count"), f"{component}.sample_count", 0)
        number(audit.get("effective_sample_size"), f"{component}.effective_sample_size", 0, n)
        mapping(audit.get("parameters"), f"{component}.parameters")
    if meta["model_status"] == "calibrated":
        audit = meta.get("calibration", {})
        if not audit.get("report") or not audit.get("method"):
            raise ValueError("calibrated forecasts require an out-of-sample report and method")
        integer(audit.get("test_rounds"), "calibration.test_rounds", 1)
        if timestamp(audit.get("evaluated_at"), "calibration.evaluated_at") > as_of:
            raise ValueError("calibration report is from after the forecast cutoff")


def validate_model(model, rules):
    mapping(model, "forecast")
    if model.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    metadata_check(model.get("metadata", {}), rules)
    assets = model.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a nonempty list")
    by_id = {}
    for asset in assets:
        mapping(asset, "asset")
        aid = asset.get("asset_id")
        if not isinstance(aid, str) or not aid.strip() or aid in by_id:
            raise ValueError("asset ids must be nonempty, unique strings")
        if asset.get("type") not in {"driver", "constructor"} or not asset.get("name"):
            raise ValueError(f"invalid asset {aid}")
        if not isinstance(asset.get("selectable", True), bool):
            raise ValueError("selectable must be a boolean")
        # A sporting entrant without a Fantasy card still affects the field and constructor.
        if asset.get("price") is None and not asset.get("selectable", True) and asset["type"] == "driver":
            pass
        else:
            price = number(asset.get("price"), f"{aid}.price", 0)
            if price <= 0 or abs(price * 10 - round(price * 10)) > 1e-8:
                raise ValueError("prices must be positive and use 0.1M increments")
        if not isinstance(asset.get("active", True), bool):
            raise ValueError("active must be a boolean")
        by_id[aid] = asset
    drivers = [a for a in assets if a["type"] == "driver" and a.get("active", True)]
    constructors = [a for a in assets if a["type"] == "constructor" and a.get("active", True)]
    cids = {a["asset_id"] for a in constructors}
    members = defaultdict(list)
    for driver in drivers:
        if driver.get("constructor_id") not in cids:
            raise ValueError(f"invalid constructor_id for {driver['asset_id']}")
        members[driver["constructor_id"]].append(driver["asset_id"])
    if not constructors or any(len(members[c]) != 2 for c in cids):
        raise ValueError("every active constructor must have exactly two active drivers")
    if not model["metadata"].get("synthetic") and len(drivers) != rules["field_size"]:
        raise ValueError("real forecasts require the full field; partial fields distort points and awards")
    scenarios = model.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("scenarios must be a nonempty joint distribution")
    total, seen = 0.0, set()
    driver_ids = {a["asset_id"] for a in drivers}
    sessions = ["qualifying", "race"] + (["sprint"] if model["metadata"]["format"] == "sprint" else [])
    for scenario in scenarios:
        mapping(scenario, "scenario")
        sid = scenario.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("scenario ids must be unique strings")
        seen.add(sid)
        total += number(scenario.get("probability"), f"{sid}.probability", 0, 1)
        if "sprint" in scenario and "sprint" not in sessions:
            raise ValueError("standard weekends must not contain Sprint scores")
        for session in sessions:
            entries = scenario.get(session)
            if not isinstance(entries, dict) or set(entries) != driver_ids:
                raise ValueError(f"{sid}.{session} must contain every active driver exactly once")
            validate_session(entries, session, sid, rules)
        pits = scenario.get("pit_stops")
        if not isinstance(pits, dict) or set(pits) != cids:
            raise ValueError("pit_stops must contain every active constructor")
        fastest = []
        times = []
        for cid, pit in pits.items():
            mapping(pit, f"pit_stops.{cid}")
            for key in ("fastest_of_race", "world_record"):
                if not isinstance(pit.get(key), bool):
                    raise ValueError(f"pit_stops.{cid}.{key} must be boolean")
            value = pit.get("fastest_stop_seconds")
            if value is None:
                if pit["fastest_of_race"] or pit["world_record"]:
                    raise ValueError("no-stop constructors cannot receive pit bonuses")
            else:
                number(value, "pit time", 0)
                if value <= 0:
                    raise ValueError("pit time must be positive")
                times.append(value)
                if pit["world_record"]:
                    record = number(model["metadata"].get("pit_record_seconds"), "pit_record_seconds", 0)
                    if record <= 0 or value >= record:
                        raise ValueError("world-record stops must beat the documented pre-weekend record")
                if pit["fastest_of_race"]:
                    fastest.append(value)
        if times and (len(fastest) != 1 or fastest[0] != min(times)):
            raise ValueError("one constructor with a minimum pit time must win fastest pitstop")
        if not times and fastest:
            raise ValueError("fastest pitstop without a stop")
        record = model["metadata"].get("pit_record_seconds")
        if record is not None:
            number(record, "pit_record_seconds", 0)
            if record <= 0:
                raise ValueError("pit_record_seconds must be positive")
            if times and min(times) < record and not any(p["world_record"] and p["fastest_of_race"] for p in pits.values()):
                raise ValueError("the fastest stop below the previous record must receive the record bonus")
    if not math.isclose(total, 1, abs_tol=1e-8, rel_tol=0):
        raise ValueError(f"scenario probabilities must sum to 1, got {total}; no silent normalization")
    return by_id, drivers, constructors


def validate_session(entries, session, sid, rules):
    size = len(entries)
    positions, starts = [], []
    fastest = dotd = 0
    for aid, result in entries.items():
        label = f"{sid}.{session}.{aid}"
        mapping(result, label)
        fields = ({"status", "position", "q2", "q3"} if session == "qualifying" else
                  {"status", "position", "start_position", "overtakes", "fastest_lap", "driver_of_day"})
        if set(result) != fields:
            raise ValueError(f"{label} requires exactly these fields: {sorted(fields)}")
        status = result.get("status")
        if status not in STATUSES:
            raise ValueError(f"{label}: invalid status")
        position = result.get("position")
        if status == "classified":
            integer(position, f"{label}.position", 1, size)
            positions.append(position)
        elif position is not None:
            raise ValueError(f"{label}: NC/DNS/DSQ must have position=null")
        if session == "qualifying":
            for key in ("q2", "q3"):
                if not isinstance(result.get(key), bool):
                    raise ValueError(f"{label}.{key} must be boolean")
            if result["q3"] and not result["q2"]:
                raise ValueError("Q3 requires Q2")
            if status != "classified" and (result["q2"] or result["q3"]):
                raise ValueError("unclassified qualifying drivers cannot earn progression bonuses")
            continue
        start = result.get("start_position")
        if start is None:
            if status != "dns":
                raise ValueError(f"{label}: official normalized start_position required")
        else:
            integer(start, f"{label}.start_position", 1, size)
            starts.append(start)
        integer(result.get("overtakes"), f"{label}.overtakes", 0)
        for key in ("fastest_lap", "driver_of_day"):
            if not isinstance(result.get(key), bool):
                raise ValueError(f"{label}.{key} must be boolean")
        if status in {"dns", "dsq"} and any(result[k] for k in ("overtakes", "fastest_lap", "driver_of_day")):
            raise ValueError("DNS/DSQ cannot retain rewards from that session")
        if session == "sprint" and result["driver_of_day"]:
            raise ValueError("Sprint has no DOTD")
        fastest += result["fastest_lap"]
        dotd += result["driver_of_day"]
    if len(set(positions)) != len(positions) or len(set(starts)) != len(starts):
        raise ValueError("joint scenarios cannot duplicate finishing or grid positions")
    if session != "qualifying" and set(positions) != set(range(1, len(positions) + 1)):
        raise ValueError("classified race/Sprint positions must be contiguous from 1")
    if fastest > 1 or dotd > 1:
        raise ValueError("joint scenarios cannot have multiple FL or DOTD winners")
    if session == "qualifying":
        ordered = sorted((r for r in entries.values() if r["status"] == "classified"), key=lambda r: r["position"])
        for flag in ("q2", "q3"):
            flags = [r[flag] for r in ordered]
            if sum(flags) > rules[f"max_{flag}"]:
                raise ValueError(f"too many drivers reach {flag}")
            if flags != sorted(flags, reverse=True):
                raise ValueError("qualifying progression must agree with classified order")


def driver_categories(result, session, rules):
    out = defaultdict(float)
    status = result["status"]
    if status != "classified":
        out[f"{session}_nc"] = rules[f"{session}_nc"]
    else:
        table = rules[f"{session}_points"]
        position = result["position"]
        out[f"{session}_position"] = table[position - 1] if position <= len(table) else 0
    if session == "qualifying" or status in {"dns", "dsq"}:
        return dict(out)
    if status == "classified":
        difference = result["start_position"] - result["position"]
        if difference >= 0:
            out[f"{session}_positions_gained"] = difference
        else:
            out[f"{session}_positions_lost"] = max(difference, -rules["sprint_positions_lost_cap"]) if session == "sprint" else difference
    out[f"{session}_overtakes"] = result["overtakes"]
    out[f"{session}_fastest_lap"] = rules[f"{session}_fastest_lap"] * result["fastest_lap"]
    if session == "race":
        out["race_dotd"] = rules["driver_of_day"] * result["driver_of_day"]
    return dict(out)


def score_scenario(scenario, drivers, constructors, rules, sprint=False):
    scores = {a["asset_id"]: defaultdict(float) for a in drivers + constructors}
    sessions = ["qualifying", "race"] + (["sprint"] if sprint else [])
    for driver in drivers:
        aid, cid = driver["asset_id"], driver["constructor_id"]
        for session in sessions:
            result = scenario[session][aid]
            for category, value in driver_categories(result, session, rules).items():
                scores[aid][category] += value
                if category != "race_dotd":
                    scores[cid][category] += value
            if result["status"] == "dsq":
                scores[cid][f"{session}_constructor_dsq"] += rules[f"{session}_constructor_dsq_extra"]
    for constructor in constructors:
        cid = constructor["asset_id"]
        qs = [scenario["qualifying"][d["asset_id"]] for d in drivers if d["constructor_id"] == cid]
        q3, q2 = sum(q["q3"] for q in qs), sum(q["q2"] for q in qs)
        tier = "both_q3" if q3 == 2 else "one_q3" if q3 else "both_q2" if q2 == 2 else "one_q2" if q2 else "none_q2"
        scores[cid]["qualifying_progress"] = rules["qualifying_progress"][tier]
        pit = scenario["pit_stops"][cid]
        value = pit["fastest_stop_seconds"]
        scores[cid]["pit_time"] = next((b["points"] for b in rules["pit_bands"] if value is not None and value < b["below_seconds"]), 0)
        scores[cid]["pit_fastest"] = rules["fastest_pit_bonus"] * pit["fastest_of_race"]
        scores[cid]["pit_record"] = rules["pit_record_bonus"] * pit["world_record"]
    return {aid: dict(categories) for aid, categories in scores.items()}


def weighted_quantile(values, weights, probability):
    cumulative = 0.0
    for value, weight in sorted(zip(values, weights)):
        if weight <= 0:
            continue
        cumulative += weight
        if cumulative + 1e-12 >= probability:
            return value
    return max(value for value, weight in zip(values, weights) if weight > 0)


def summarize(values, weights):
    mu = math.fsum(p * value for p, value in zip(weights, values))
    variance = math.fsum(p * (value - mu) ** 2 for p, value in zip(weights, values))
    return {"mu": mu, "sd": math.sqrt(max(variance, 0)),
            "p10": weighted_quantile(values, weights, 0.1),
            "p50": weighted_quantile(values, weights, 0.5),
            "p90": weighted_quantile(values, weights, 0.9),
            "p_negative": math.fsum(p for p, value in zip(weights, values) if value < 0)}


def evaluate_model(model, rules):
    by_id, drivers, constructors = validate_model(model, rules)
    weights = [s["probability"] for s in model["scenarios"]]
    categories = [score_scenario(s, drivers, constructors, rules, model["metadata"]["format"] == "sprint") for s in model["scenarios"]]
    totals, protected, breakdown, metrics, total_pmfs = {}, {}, [], [], {}
    for asset in drivers + constructors:
        aid = asset["asset_id"]
        totals[aid] = [sum(s[aid].values()) for s in categories]
        protected[aid] = [sum(max(value, 0) for value in s[aid].values()) for s in categories]
        keys = {key for s in categories for key in s[aid]}
        for session in ["qualifying", "race"] + (["sprint"] if model["metadata"]["format"] == "sprint" else []):
            keys.update(f"{session}_{suffix}" for suffix in ("position", "nc"))
            if session != "qualifying":
                keys.update(f"{session}_{suffix}" for suffix in ("positions_gained", "positions_lost", "overtakes", "fastest_lap"))
            if asset["type"] == "constructor":
                keys.add(f"{session}_constructor_dsq")
        keys.update(("qualifying_progress", "pit_time", "pit_fastest", "pit_record") if asset["type"] == "constructor" else ("race_dotd",))
        keys = sorted(keys)
        for key in keys:
            pmf = defaultdict(float)
            for probability, scenario in zip(weights, categories):
                pmf[scenario[aid].get(key, 0)] += probability
            for points, probability in sorted(pmf.items()):
                if probability > 0:
                    breakdown.append({"asset_id": aid, "category": key, "points": points,
                                      "probability": probability, "mu_contribution": probability * points})
        metrics.append({"asset_id": aid, "type": asset["type"], "name": asset["name"],
                        "price": asset["price"], **summarize(totals[aid], weights),
                        "mu_no_negative": summarize(protected[aid], weights)["mu"]})
        mass = defaultdict(float)
        for value, probability in zip(totals[aid], weights):
            mass[value] += probability
        total_pmfs[aid] = [{"points": value, "probability": p} for value, p in sorted(mass.items())]
    return {"metadata": model["metadata"], "assets": by_id, "weights": weights,
            "scenario_categories": categories, "scores": totals, "protected_scores": protected,
            "asset_metrics": metrics, "component_distributions": breakdown, "score_distributions": total_pmfs,
            "warnings": ["Statistics are conditional on the supplied joint scenario distribution, not guaranteed outcomes.",
                         "Evidence and calibration metadata are audited structurally, not independently verified."]
                        + (["SYNTHETIC tutorial field: not an actual race forecast or recommendation."] if model["metadata"].get("synthetic") else [])
                        + model["metadata"].get("limitations", [])
                        + ([] if model["metadata"]["model_status"] == "calibrated" else
                           ["Uncalibrated probabilities: report as baseline/scenario, not a validated forecast."])}
