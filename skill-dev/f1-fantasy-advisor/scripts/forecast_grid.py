"""Grid penalty facts, joint uncertainty branches, and full-field grid allocation."""

from itertools import product

from forecast_core import integer, number, timestamp


def penalty_events(grid, drivers, cutoff, source_ids, sessions):
    latest, revisions = {}, set()
    for row in grid.get("events", []):
        event = row.get("event_id")
        revision = row.get("revision_id", event)
        if not isinstance(event, str) or not event or not revision:
            raise ValueError("penalty needs event_id and revision_id")
        key = (event, revision)
        if key in revisions:
            if latest.get(event) != row:
                raise ValueError("conflicting duplicate penalty revision")
            continue
        revisions.add(key)
        if timestamp(row.get("published_at"), "penalty.published_at") > cutoff:
            raise ValueError("penalty news after cutoff")
        if row.get("source_ref") not in source_ids or not row.get("quote"):
            raise ValueError("penalty needs an evidence source and quote")
        if event in latest:
            if row.get("supersedes") != latest[event].get("revision_id", event):
                raise ValueError("penalty revisions need an explicit supersedes chain")
        latest[event] = row
    result = []
    for row in latest.values():
        if not isinstance(row.get("active", True), bool):
            raise ValueError("penalty.active must be boolean")
        if not row.get("active", True):
            continue
        if row.get("asset_id") not in drivers or row.get("session") not in sessions:
            raise ValueError("penalty driver/session not in target weekend")
        if row.get("status") not in {"confirmed", "expected", "unverified"}:
            raise ValueError("unknown penalty confirmation status")
        if row["status"] == "unverified":
            continue
        if row.get("penalty_type") not in {"grid_places", "back_of_grid", "pit_lane"}:
            raise ValueError("unsupported penalty type")
        if row["penalty_type"] == "grid_places":
            integer(row.get("places"), "penalty.places", 1)
        if not row.get("rule_ref"):
            raise ValueError("penalty requires applicable rule_ref")
        if "probability" in row:
            number(row["probability"], "penalty.probability", 0, 1)
            if not row.get("probability_method") or row.get("probability_source") not in source_ids:
                raise ValueError("penalty probability needs method and source")
        result.append(row)
    return sorted(result, key=lambda r: r["event_id"])


def branches(grid, events):
    confirmed = {r["event_id"] for r in events if r["status"] == "confirmed"}
    expected = [r for r in events if r["status"] == "expected"]
    explicit = grid.get("joint_branches")
    if explicit is not None:
        rows = []
        allowed = {r["event_id"] for r in expected}
        for index, item in enumerate(explicit):
            active = item.get("active_events", [])
            if len(active) != len(set(active)) or not set(active) <= allowed:
                raise ValueError("joint branch contains invalid penalty events")
            p = number(item.get("probability"), "joint probability", 0, 1)
            rows.append({"id": f"branch_{index}", "active": confirmed | set(active), "probability": p})
        if not rows or abs(sum(r["probability"] for r in rows)-1) > 1e-8:
            raise ValueError("joint penalty probabilities must sum to one")
        if not grid.get("joint_probability_method") or not grid.get("joint_probability_source"):
            raise ValueError("joint penalty probabilities require method and source")
        return rows, True
    if len(expected) > 6:
        raise ValueError("more than six uncertain penalties: supply explicit joint branches")
    weighted = len(expected) == 1 and "probability" in expected[0]
    rows = []
    for index, flags in enumerate(product((False, True), repeat=len(expected))):
        active = confirmed | {r["event_id"] for r, flag in zip(expected, flags) if flag}
        p = (expected[0]["probability"] if flags[0] else 1-expected[0]["probability"]) if weighted else 1.0
        rows.append({"id": f"branch_{index}", "active": active, "probability": p})
    return rows, weighted or not expected


def allocate_grid(order, qualifying, events, session, grid, rules, use_official=True):
    official = grid.get("official_orders", {}).get(session)
    if use_official and official is not None:
        applied = set(official.get("applied_event_ids", []))
        relevant = {r["event_id"] for r in events if r["session"] == session}
        if relevant != applied:
            raise ValueError("official grid applied_event_ids differ from this penalty branch; supply a matching grid or simulate from qualifying")
        supplied = official["asset_ids"]
        if len(supplied) != len(order) or set(supplied) != set(order):
            raise ValueError("official grid must contain every active driver exactly once")
        return {aid: rank for rank, aid in enumerate(supplied, 1)}
    active = [r for r in events if r["session"] == session]
    if not active:
        return {aid: rank for rank, aid in enumerate(order, 1)}
    if rules.get("algorithm") != "fia_temporary_positions":
        raise ValueError("unsupported or missing grid-rules algorithm")
    limit = integer(rules.get("back_of_grid_above"), "back_of_grid_above", 1)
    places = dict.fromkeys(order, 0)
    backs, pits = set(), set()
    for event in active:
        aid = event["asset_id"]
        if event["penalty_type"] == "grid_places":
            places[aid] += event["places"]
        elif event["penalty_type"] == "back_of_grid":
            backs.add(aid)
        else:
            pits.add(aid)
    backs.update(aid for aid, n in places.items() if n > limit)
    unclassified = {aid for aid in order if qualifying.get(aid, {}).get("status", "classified") != "classified"}
    regular = [aid for aid in order if aid not in backs | pits | unclassified]
    qpos = {aid: n for n, aid in enumerate(order, 1)}
    temporary = {}
    # Work backwards so a tied slower qualifier retains the nominal slot.
    penalized = sorted((aid for aid in regular if places[aid]), key=lambda aid: (qpos[aid]+places[aid], qpos[aid]), reverse=True)
    for aid in penalized:
        slot = qpos[aid]+places[aid]
        while slot in temporary:
            slot -= 1
        if slot < 1:
            raise ValueError("grid collision requires official adjudication")
        temporary[slot] = aid
    slot = 1
    for aid in regular:
        if places[aid]:
            continue
        while slot in temporary:
            slot += 1
        temporary[slot] = aid
    result = [temporary[k] for k in sorted(temporary)]
    result += [aid for aid in order if aid in backs and aid not in unclassified | pits]
    result += [aid for aid in order if aid in unclassified and aid not in pits]
    if pits:
        convention = grid.get("pit_lane_convention", {})
        if convention.get("method") != "ordered_after_grid" or not convention.get("source_ref"):
            raise ValueError("pit-lane starters need a sourced Fantasy starting-position convention")
        pit_order = grid.get("pit_lane_order", [next(iter(pits))] if len(pits) == 1 else [])
        if set(pit_order) != pits or len(pit_order) != len(pits):
            raise ValueError("multiple pit-lane starters require official relative order")
        result += pit_order
    if len(result) != len(order) or len(set(result)) != len(order):
        raise ValueError("grid allocation failed to produce a full permutation")
    return {aid: rank for rank, aid in enumerate(result, 1)}
