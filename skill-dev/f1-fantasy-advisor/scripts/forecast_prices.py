"""Scenario-wise local price estimates, independent of boosts and transfer fees."""

from collections import defaultdict
from decimal import Decimal
import math

from fantasy_state import price_change_for
from forecast_core import integer, number, timestamp

PRICE_MODEL_VERSION = "local-avgppm-18.5-floor3-v1"


def evaluate_prices(evaluation):
    results = {}
    cutoff = timestamp(evaluation["metadata"]["as_of"], "as_of")
    target = evaluation["metadata"].get("round_number")
    for aid, scores in evaluation["scores"].items():
        asset = evaluation["assets"][aid]
        if not asset.get("selectable", True):
            results[aid] = {"available": False, "reason": "Sporting entrant has no selectable Fantasy card; no price forecast"}
            continue
        history = asset.get("price_history", [])
        if not isinstance(history, list):
            raise ValueError(f"{aid}.price_history must be a list")
        if len(history) != 2:
            results[aid] = {"available": False, "reason": "Two settled previous weekend scores required"}
            continue
        rounds = []
        for row in history:
            rnd = integer(row.get("round"), "price_history.round", 1)
            if target is None or rnd >= target:
                raise ValueError("price history requires round_number and must precede target round")
            if timestamp(row.get("settled_at"), "price_history.settled_at") > cutoff or not row.get("source_ref"):
                raise ValueError("price history needs pre-cutoff settlement and source")
            number(row.get("points"), "price_history.points")
            rounds.append(rnd)
        if len(set(rounds)) != 2:
            raise ValueError("duplicate price-history round")
        expected_rounds = evaluation["metadata"].get("previous_rounds", [r for r in (target-2, target-1) if r > 0])
        if set(rounds) != set(expected_rounds) or len(expected_rounds) != 2:
            results[aid] = {"available": False, "reason": "Price history does not cover the two latest settled weekends"}
            continue
        rolling = sum((Decimal(str(row["points"])) for row in history), Decimal(0))
        price = Decimal(str(asset["price"]))
        if asset["type"] == "driver" and price < Decimal("3"):
            raise ValueError("driver price below 3.0M floor")
        # Price is a step function. Aggregate identical raw scores before mapping.
        score_mass = defaultdict(float)
        for score, weight in zip(scores, evaluation["weights"]):
            score_mass[score] += weight
        movement = defaultdict(float)
        for score, probability in score_mass.items():
            _, change = price_change_for(price, rolling + Decimal(str(score)), asset["type"])
            movement[float(change)] += probability
        results[aid] = {"available": True, "model_version": PRICE_MODEL_VERSION,
                        "expected_change": math.fsum(x*p for x, p in movement.items()),
                        "p_rise": math.fsum(p for x, p in movement.items() if x > 0),
                        "p_fall": math.fsum(p for x, p in movement.items() if x < 0),
                        "distribution": [{"change": x, "probability": p} for x, p in sorted(movement.items())]}
    return results
