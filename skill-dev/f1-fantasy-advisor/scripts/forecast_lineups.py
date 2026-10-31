#!/usr/bin/env python3
"""Exact expected-score lineup search with joint scenario risk reporting."""

from __future__ import annotations

import heapq
import math
from itertools import combinations

from forecast_core import integer, number, summarize

CHIPS = {"none", "autopilot", "no_negative", "3x", "wildcard", "limitless"}


def money(value, label):
    number(value, label, 0)
    units = round(value * 10)
    if abs(units - value * 10) > 1e-8:
        raise ValueError(f"{label} must use 0.1M increments")
    return units


def boosts(driver_ids, means, chip):
    ranked = sorted(driver_ids, key=lambda aid: (means[aid], aid), reverse=True)
    if chip == "autopilot":
        return None, None
    if chip == "3x":
        return ranked[1], ranked[0]
    return ranked[0], None


def lineup_values(ids, drivers, scores, weights, chip, penalty):
    means = {aid: math.fsum(p * value for p, value in zip(weights, scores[aid])) for aid in drivers}
    boost, triple = boosts(drivers, means, chip)
    values = []
    for index in range(len(weights)):
        base = sum(scores[aid][index] for aid in ids)
        bonus = max(scores[aid][index] for aid in drivers) if chip == "autopilot" else scores[boost][index]
        if triple:
            bonus += 2 * scores[triple][index]
        values.append(base + bonus - penalty)
    return values, boost, triple


def optimize(evaluation, team, rules, top=5, allow=10):
    integer(top, "top", 1)
    number(allow, "allow", 0)
    assets, weights = evaluation["assets"], evaluation["weights"]
    chip = team.get("chip", "none")
    if chip not in CHIPS:
        raise ValueError("unsupported chip; Final Fix/post-lock transfers need a separate session-aware workflow")
    scores = evaluation["protected_scores"] if chip == "no_negative" else evaluation["scores"]
    means = {aid: math.fsum(p * value for p, value in zip(weights, values)) for aid, values in scores.items()}
    prices = {aid: money(a["price"], f"{aid}.price") for aid, a in assets.items() if a.get("price") is not None}
    previous = team.get("previous_lineup", [])
    if not isinstance(previous, list) or any(not isinstance(aid, str) for aid in previous):
        raise ValueError("previous_lineup must be a list of asset ids")
    if previous:
        if len(previous) != 7 or len(set(previous)) != 7 or any(aid not in assets for aid in previous):
            raise ValueError("previous_lineup requires seven distinct known assets, including current selling prices")
        if sum(assets[aid]["type"] == "driver" for aid in previous) != 5:
            raise ValueError("previous_lineup must contain five drivers and two constructors")
        if any(aid not in prices for aid in previous):
            raise ValueError("previous_lineup requires known selling prices; unpriced sporting entrants cannot be account holdings")
        if "budget" in team:
            raise ValueError("use previous_lineup + bank OR budget, not both")
        budget = sum(prices[aid] for aid in previous) + money(team.get("bank"), "bank")
        free = integer(team.get("free_transfers"), "free_transfers", 0, 3)
    else:
        if "bank" in team:
            raise ValueError("bank requires previous_lineup")
        budget = money(team.get("budget"), "budget")
        free = 7
    incurred = number(team.get("penalty_already_incurred", 0), "penalty_already_incurred", 0)
    max_transfers = team.get("max_transfers", 7)
    integer(max_transfers, "max_transfers", 0, 7)
    if budget <= 0:
        raise ValueError("budget must be positive")
    selectable = {aid for aid in scores if assets[aid].get("selectable", True)}
    drivers = [aid for aid in scores if assets[aid]["type"] == "driver" and aid in selectable]
    constructors = [aid for aid in scores if assets[aid]["type"] == "constructor" and aid in selectable]
    constraints = {}
    for key in ("required_assets", "excluded_assets"):
        ids = team.get(key, [])
        if (not isinstance(ids, list) or any(not isinstance(aid, str) or aid not in scores for aid in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError(f"{key} must contain distinct active asset ids")
        constraints[key] = set(ids)
    required, excluded = constraints["required_assets"], constraints["excluded_assets"]
    if not required <= selectable:
        raise ValueError("required_assets cannot include non-selectable sporting entrants")
    if required & excluded:
        raise ValueError("required_assets and excluded_assets cannot overlap")
    drivers = [aid for aid in drivers if aid not in excluded]
    constructors = [aid for aid in constructors if aid not in excluded]
    if len(drivers) < 5 or len(constructors) < 2:
        raise ValueError("need at least five active drivers and two active constructors")
    old = set(previous)
    cps = [(cs, sum(prices[aid] for aid in cs), sum(means[aid] for aid in cs), len(set(cs) - old))
           for cs in combinations(constructors, 2) if required.intersection(constructors) <= set(cs)]
    def candidates():
        for ds in combinations(drivers, 5):
            if not required.intersection(drivers) <= set(ds):
                continue
            driver_cost = sum(prices[aid] for aid in ds)
            driver_changes = len(set(ds) - old)
            boost, triple = boosts(ds, means, chip)
            bonus = (math.fsum(p * max(scores[aid][s] for aid in ds) for s, p in enumerate(weights))
                     if chip == "autopilot" else means[boost] + (2 * means[triple] if triple else 0))
            driver_mu = sum(means[aid] for aid in ds) + bonus
            for cs, constructor_cost, constructor_mu, constructor_changes in cps:
                cost = driver_cost + constructor_cost
                if cost > budget and chip != "limitless":
                    continue
                transfers = driver_changes + constructor_changes if previous else 0
                if transfers > max_transfers:
                    continue
                extra = 0 if chip in {"wildcard", "limitless"} else max(0, transfers - free)
                penalty = extra * rules["extra_transfer_penalty"] + incurred
                mu = driver_mu + constructor_mu - penalty
                yield (mu, -transfers, -cost, ds + cs, penalty), extra

    from forecast_prices import evaluate_prices
    growth = evaluation.get("price_metrics")
    if growth is None:
        growth = evaluate_prices(evaluation)
    heap, free_heap, missing_growth = [], [], set()
    for item, extra in candidates():
        missing_growth.update(aid for aid in item[3] if not growth.get(aid, {}).get("available"))
        for selected_heap in ([heap, free_heap] if extra == 0 else [heap]):
            if len(selected_heap) < top:
                heapq.heappush(selected_heap, item)
            elif item > selected_heap[0]:
                heapq.heapreplace(selected_heap, item)
    if not heap:
        raise ValueError("no legal lineup fits the budget and transfer constraint")
    baseline = None
    baseline_values = None
    if previous and all(aid in scores for aid in previous):
        bd = [aid for aid in previous if assets[aid]["type"] == "driver"]
        baseline_values, b2, b3 = lineup_values(previous, bd, scores, weights, chip, incurred)
        baseline = {**summarize(baseline_values, weights), "boost_2x": b2, "boost_3x": b3,
                    "chip": chip, "note": "Same-chip, no-transfer baseline with its boost reoptimized before lock."}
    free_mu = max((item[0] for item in free_heap), default=None)

    best_mu = max(item[0] for item in heap)
    budget_item = None
    budget_key = None
    growth_available = not missing_growth and chip == "none"
    if growth_available:
        for item, _ in candidates():
            if item[0] < best_mu - allow - 1e-9:
                continue
            gain = math.fsum(growth[aid]["expected_change"] for aid in item[3])
            key = (round(gain, 12), item[0], item[1], item[2], item[3])
            if budget_key is None or key > budget_key:
                budget_item, budget_key = item, key

    def growth_detail(ids):
        if chip != "none" or any(not growth.get(aid, {}).get("available") for aid in ids):
            return {"expected_budget_change": None, "expected_total_value": None}
        gain = math.fsum(growth[aid]["expected_change"] for aid in ids)
        return {"expected_budget_change": gain, "expected_total_value": budget / 10 + gain}

    if baseline is not None:
        baseline.update(growth_detail(previous))

    def detail(item):
        expected, negative_n, negative_cost, ids, penalty = item
        ds = [aid for aid in ids if assets[aid]["type"] == "driver"]
        values, b2, b3 = lineup_values(ids, ds, scores, weights, chip, penalty)
        stats = summarize(values, weights)
        if not math.isclose(expected, stats["mu"], abs_tol=1e-8):
            raise ValueError("internal expected-score reconciliation failed")
        return {"asset_ids": list(ids), "names": [assets[aid]["name"] for aid in ids],
                "cost": -negative_cost / 10,
                "bank": None if chip == "limitless" else (budget + negative_cost) / 10,
                "transfers": -negative_n, "transfer_penalty": penalty,
                "boost_2x": b2, "boost_3x": b3, **stats, **growth_detail(ids),
                "loss_vs_best": max(0.0, best_mu - stats["mu"]),
                "gain_vs_no_transfers": None if baseline is None else stats["mu"] - baseline["mu"],
                "gain_vs_best_free": None if free_mu is None else stats["mu"] - free_mu,
                "p_beat_no_transfers": None if baseline_values is None else
                    math.fsum(p for p, value, old_value in zip(weights, values, baseline_values) if value > old_value),
                "transfers_in": [aid for aid in ids if aid not in old] if previous else [],
                "transfers_out": [aid for aid in previous if aid not in ids]}

    score_choice = detail(max(heap))
    budget_choice = detail(budget_item) if budget_item else None
    return {"allow": allow, "mu_best": best_mu, "score_best": score_choice,
            "budget_best": budget_choice, "recommended": budget_choice or score_choice,
            "budget_status": "available" if growth_available else "unavailable",
            "budget_unavailable_assets": sorted(missing_growth),
            "team_id": team.get("team_id", "team"), "state_status": team.get("state_status", "provided"),
            "state_notes": team.get("notes", ""), "chip": chip, "budget": budget / 10,
            "required_assets": sorted(required), "excluded_assets": sorted(excluded),
            "free_transfers": free if previous else None, "baseline": baseline,
            "baseline_unavailable": bool(previous) and baseline is None,
            "top": [detail(item) for item in sorted(heap, reverse=True)],
            "best_free": detail(max(free_heap)) if free_heap else None,
            "warnings": evaluation["warnings"] +
                ["Chip availability and future opportunity cost are not inferred; this is a single-round objective."] +
                (["Inactive holdings are excluded from new lineups; the optimum assumes they are replaced, and no retention baseline is scored."]
                 if previous and baseline is None else []) +
                (["Limitless is temporary; shadow-team price changes are outside this score optimizer."] if chip == "limitless" else [])}
