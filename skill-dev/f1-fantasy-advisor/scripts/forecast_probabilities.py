#!/usr/bin/env python3
"""Auditable categorical probability estimation and out-of-sample diagnostics."""

from __future__ import annotations

import math

from forecast_core import integer, mapping, number, timestamp


def distribution(values, label, positive=False):
    if not isinstance(values, dict) or not values:
        raise ValueError(f"{label} must be a nonempty mapping")
    for outcome, probability in values.items():
        if not isinstance(outcome, str) or not outcome:
            raise ValueError("outcome labels must be nonempty strings")
        number(probability, f"{label}.{outcome}", 0, 1)
        if positive and probability == 0:
            raise ValueError("Dirichlet priors must be positive for every possible outcome")
    if not math.isclose(math.fsum(values.values()), 1, abs_tol=1e-8, rel_tol=0):
        raise ValueError(f"{label} probabilities must sum to 1")


def estimate_categorical(spec):
    """Power-prior Dirichlet estimate; parameters are explicit, not tuned here."""
    mapping(spec, "probability input")
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported probability schema_version")
    target = spec.get("target", {})
    target_round = integer(target.get("round"), "target.round", 1)
    as_of = timestamp(target.get("as_of"), "target.as_of")
    prior = spec.get("prior", {})
    base = prior.get("probabilities")
    distribution(base, "prior", positive=True)
    strength = number(prior.get("strength"), "prior.strength", 0)
    half_life = number(spec.get("half_life_rounds"), "half_life_rounds", 0)
    if strength <= 0 or half_life <= 0:
        raise ValueError("prior strength and half-life must be positive")
    if not prior.get("source") or timestamp(prior.get("available_at"), "prior.available_at") > as_of:
        raise ValueError("prior requires a source available before the cutoff")
    observations = spec.get("observations")
    if not isinstance(observations, list):
        raise ValueError("observations must be a list, possibly empty for a prior-only estimate")
    counts = dict.fromkeys(base, 0.0)
    weights, observation_ids = [], set()
    for row in observations:
        mapping(row, "observation")
        oid = row.get("id")
        if not isinstance(oid, str) or not oid or oid in observation_ids:
            raise ValueError("observation ids must be nonempty and unique")
        observation_ids.add(oid)
        rnd = integer(row.get("round"), "observation.round", 1)
        if rnd >= target_round or timestamp(row.get("observed_at"), "observation.observed_at") > as_of:
            raise ValueError("historical observations must precede target round and information cutoff")
        if not row.get("source"):
            raise ValueError("every observation requires a source")
        outcome = row.get("outcome")
        if outcome not in base:
            raise ValueError(f"unknown outcome {outcome!r}; explicitly define its prior")
        reliability = number(row.get("weight", 1.0), "observation.weight", 0, 1)
        weight = reliability * 2 ** (-(target_round - 1 - rnd) / half_life)
        counts[outcome] += weight
        weights.append(weight)
    exposure = math.fsum(weights)
    concentration = strength + exposure
    probabilities = {label: (strength * base[label] + count) / concentration for label, count in counts.items()}
    squared = math.fsum(w * w for w in weights)
    return {
        "schema_version": 1, "status": "prior_only" if exposure == 0 else "uncalibrated_baseline",
        "formula": "p_k=(kappa*pi_k+sum(w_j*I[y_j=k]))/(kappa+sum(w_j)); w_j=r_j*2^(-age_rounds/H)",
        "target": target, "prior_source": prior["source"], "prior_strength": strength,
        "half_life_rounds": half_life, "sample_count": len(observations),
        "weighted_exposure": exposure, "effective_sample_size": exposure ** 2 / squared if squared else 0,
        "weighted_counts": counts, "probabilities": probabilities,
        "posterior_sd": {label: math.sqrt(p * (1 - p) / (concentration + 1)) for label, p in probabilities.items()},
        "observations": observations,
        "warnings": ["Fractional/decayed counts define a power-prior baseline, not proof of calibration.",
                     "posterior_sd is parameter uncertainty under the prior, not race-score volatility.",
                     "Marginal probabilities alone cannot produce lineup tails or Autopilot value."]}


def calibration_report(spec):
    """Evaluate frozen pre-lock categorical predictions against later outcomes."""
    mapping(spec, "calibration input")
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported calibration schema_version")
    rows = spec.get("predictions")
    if not isinstance(rows, list) or not rows:
        raise ValueError("predictions must be nonempty")
    briers, losses, seen, labels = [], [], set(), None
    buckets = {}
    impossible = 0
    for row in rows:
        mapping(row, "prediction")
        pid = row.get("id")
        if not isinstance(pid, str) or not pid or pid in seen:
            raise ValueError("prediction ids must be unique")
        seen.add(pid)
        if not row.get("source") or not row.get("round"):
            raise ValueError("each prediction needs a source and round")
        as_of = timestamp(row.get("as_of"), "prediction.as_of")
        if not (timestamp(row.get("trained_through"), "trained_through") <= as_of
                < timestamp(row.get("lock_at"), "lock_at")
                < timestamp(row.get("outcome_known_at"), "outcome_known_at")):
            raise ValueError("require trained_through <= as_of < lock_at < outcome_known_at")
        probabilities = row.get("probabilities")
        distribution(probabilities, "prediction")
        if labels is None:
            labels = set(probabilities)
        if set(probabilities) != labels or row.get("actual") not in labels:
            raise ValueError("use a consistent categorical support and valid actual outcomes")
        actual = row["actual"]
        briers.append(sum((p - (label == actual)) ** 2 for label, p in probabilities.items()))
        likelihood = probabilities[actual]
        if likelihood == 0:
            impossible += 1
        else:
            losses.append(-math.log(likelihood))
        for label, p in probabilities.items():
            key = (label, min(int(p * 10), 9))
            bucket = buckets.setdefault(key, {"count": 0, "sum_probability": 0.0, "hits": 0})
            bucket["count"] += 1
            bucket["sum_probability"] += p
            bucket["hits"] += label == actual
    return {"prediction_count": len(rows), "test_rounds": len({str(row['round']) for row in rows}),
            "multiclass_brier": math.fsum(briers) / len(rows),
            "mean_log_loss": None if impossible else math.fsum(losses) / len(rows),
            "zero_probability_actuals": impossible,
            "log_loss_infinite": bool(impossible),
            "reliability": [{"outcome": label, "bin": index, "count": b["count"],
                             "mean_probability": b["sum_probability"] / b["count"],
                             "observed_frequency": b["hits"] / b["count"]}
                            for (label, index), b in sorted(buckets.items())],
            "warning": "Diagnostics do not certify calibration; inspect sample sizes and held-out folds. No epsilon hides impossible actual events."}
