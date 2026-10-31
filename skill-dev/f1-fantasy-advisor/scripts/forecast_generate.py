"""Historical power priors, practice evidence, and reproducible full-field draws."""

from collections import Counter, defaultdict
import copy
import hashlib
import math

from forecast_core import PROBABILITY_COMPONENTS, SPRINT_COMPONENTS, integer, number, timestamp, validate_model
from forecast_circuits import canonical_circuit, circuit_models, load_profiles
from forecast_grid import allocate_grid, penalty_events

DEFAULTS = {"window": 4, "decay_mode": "linear", "half_life": 2, "prior_strength": 8, "practice_weight": 0.4,
            "fp_weights": {"fp1": 0.2, "fp2": 0.3, "fp3": 0.5}, "incident_bonus": 2,
            "instability_penalty": 2, "temperature": 3, "circuit_difficulty": None,
            "min_effective_samples": 3, "samples": 8192, "seed": 42}


def ess(weights):
    return math.fsum(weights)**2 / math.fsum(w*w for w in weights) if any(weights) else 0.0


def uniform(seed, sample, *keys):
    raw = "|".join(map(str, (seed, sample, *keys))).encode()
    value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return (value + 0.5) / (2**64 + 1)


def pick(values, weights, u):
    total = math.fsum(weights)
    if not values or total <= 0:
        raise ValueError("cannot draw from an empty probability distribution")
    boundary = u * total
    running = 0.0
    for value, weight in zip(values, weights):
        running += weight
        if running > boundary:
            return value
    return values[-1]


def rank_score(position, historical_size, field_size):
    return 1 + (field_size-1) * (historical_size-position) / (historical_size-1)


class Generator:
    def __init__(self, data, config, rules, grid_rules, sources, circuit_profile_path=None):
        self.data, self.config, self.rules, self.grid_rules = data, config, rules, grid_rules
        self.parameters = copy.deepcopy(DEFAULTS)
        if set(config.get("model_parameters", {})) & {"circuit_factor", "overtake_bandwidth", "circuit_density_floor", "grid_weight", "max_grid_weight"}:
            raise ValueError("legacy circuit parameters were replaced by the fixed circuit table and gain-ratio overtakes; remove them and use circuit_difficulty in [0,1] for sensitivity analysis (grid weight=0.2+0.6*d)")
        if "circuit_history_input" in config or "circuit_history" in data:
            raise ValueError("circuit_history imports were replaced by references/circuit-profiles.json; remove the legacy import")
        unknown = set(config.get("model_parameters", {})) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown model parameters: {sorted(unknown)}")
        self.parameters.update(config.get("model_parameters", {}))
        p = self.parameters
        if p["decay_mode"] not in {"linear", "exponential"}:
            raise ValueError("decay_mode must be linear or exponential")
        for key in ("window", "samples"):
            integer(p[key], key, 1)
        integer(p["seed"], "seed", 0)
        for key in ("half_life", "prior_strength", "temperature", "min_effective_samples"):
            if number(p[key], key, 0) == 0:
                raise ValueError(f"{key} must be positive")
        for key in ("incident_bonus", "instability_penalty"):
            number(p[key], key, 0)
        number(p["practice_weight"], "practice_weight", 0, 1)
        if p["circuit_difficulty"] is not None:
            number(p["circuit_difficulty"], "circuit_difficulty", 0, 1)
        if set(p["fp_weights"]) != {"fp1", "fp2", "fp3"}:
            raise ValueError("fp_weights must specify fp1/fp2/fp3")
        for value in p["fp_weights"].values():
            number(value, "fp_weight", 0)
        if not sum(p["fp_weights"].values()):
            raise ValueError("at least one positive FP weight required")
        self.cutoff = timestamp(config["as_of"], "as_of")
        self.target = integer(config["target_round"], "target_round", 1)
        self.sessions = ["qualifying", "race"] + (["sprint"] if config["format"] == "sprint" else [])
        self.assets = data["assets"]
        self.drivers = sorted((a for a in self.assets if a["type"] == "driver" and a.get("active", True)), key=lambda a: a["asset_id"])
        self.constructors = sorted((a for a in self.assets if a["type"] == "constructor" and a.get("active", True)), key=lambda a: a["asset_id"])
        self.by_id = {a["asset_id"]: a for a in self.drivers}
        self.ids = list(self.by_id)
        self.size = len(self.ids)
        self.sources = sources
        self.source_ids = {s["id"] for s in sources}
        self.source_times = {s["id"]: timestamp(s["observed_at"], "source observed_at") for s in sources}
        if len(self.source_ids) != len(sources):
            raise ValueError("duplicate evidence source ids")
        self.warnings = set(data.get("quality", []))
        if len({a["asset_id"] for a in self.assets}) != len(self.assets):
            raise ValueError("duplicate asset ids")
        if len({a["person_id"] for a in self.drivers}) != len(self.drivers):
            raise ValueError("two active assets represent the same real driver")
        if not config.get("synthetic") and self.size != rules["field_size"]:
            raise ValueError("real forecasts require the full field")
        if not self.constructors or any(sum(d["constructor_id"] == c["asset_id"] for d in self.drivers) != 2 for c in self.constructors):
            raise ValueError("every active constructor must have exactly two active drivers")
        if any(d["constructor_id"] not in {c["asset_id"] for c in self.constructors} for d in self.drivers):
            raise ValueError("driver has an unknown active constructor")
        if data.get("priors"):
            prior = data["priors"]
            self.check_evidence(prior, "available_at", "prior availability")
        for asset in self.assets:
            for row in asset.get("price_history", []):
                self.check_evidence(row, "settled_at", "price settlement")
        self.audit, self.adjustments, self.overtake_audit = {}, [], {}
        self.history = self.validate_history(data.get("history", []))
        circuit_id = config.get("circuit_id") or data.get("circuit_id")
        if circuit_id is not None and (not isinstance(circuit_id, str) or not circuit_id.strip()):
            raise ValueError("circuit_id must be a nonempty string")
        self.circuit_profiles = load_profiles(circuit_profile_path)
        if (config.get("circuit_id") and data.get("circuit_id") and
                canonical_circuit(config["circuit_id"], self.circuit_profiles) != canonical_circuit(data["circuit_id"], self.circuit_profiles)):
            raise ValueError("configured circuit_id differs from public target")
        self.circuit_models = circuit_models(circuit_id, config["format"], p["circuit_difficulty"], self.circuit_profiles)
        self.grid_weights = {s: model["selected"]["grid_weight"] for s, model in self.circuit_models.items()}
        for session, model in self.circuit_models.items():
            if model["selected"]["method"] == "generic_fallback":
                weight = model["selected"]["grid_weight"]
                self.warnings.add(f"{session}: circuit absent from fixed table; table fallback (default neutral 50%) used, actual grid weight {weight:.0%}")
            if model["selected"]["confidence"] == "low":
                self.warnings.add(f"{session}: circuit difficulty has low evidence confidence; inspect the fixed-table rationale")
        if self.circuit_profiles["assessed_on"] > self.cutoff.date().isoformat():
            self.warnings.add("Circuit table assessed after forecast cutoff: retrospective model revision, not a frozen pre-lock prediction")
        for event in data.get("grid", {}).get("events", []):
            self.check_evidence(event, "published_at", "penalty publication")
        self.events = penalty_events(data.get("grid", {}), set(self.ids), self.cutoff, self.source_ids, self.sessions)
        self.validate_grid()
        self.practice = self.practice_scores()
        self.status, self.strength, self.started, self.awards, self.overtake_cache = {}, {}, {}, {}, {}
        for session in self.sessions:
            self.status[session], self.strength[session], self.started[session] = {}, {}, {}
            for asset in self.drivers:
                aid = asset["asset_id"]
                rows = [r for r in self.history if r["session"] == session and r["person_id"] == asset["person_id"]]
                recent = self.recent(rows)
                pool = [r for r in self.history if r["session"] == session and r["person_id"] != asset["person_id"]]
                counts = Counter("nc" if r["status"] == "dns" else r["status"] for r in pool)
                if pool:
                    prior = {k: (counts[k]+0.5)/(len(pool)+1.5) for k in ("classified", "nc", "dsq")}
                else:
                    prior = data.get("priors", {}).get(session, {}).get("status")
                    if not prior or set(prior) != {"classified", "nc", "dsq"} or abs(sum(prior.values())-1) > 1e-8:
                        raise ValueError(f"no historical status prior for {session}")
                    for value in prior.values():
                        number(value, "status prior", 0, 1)
                    self.warnings.add(f"{session}: explicit prior used without same-season field observations")
                weights = self.weights(recent)
                numerator = {k: p["prior_strength"]*prior[k] for k in prior}
                for row, weight in zip(recent, weights):
                    numerator["nc" if row["status"] == "dns" else row["status"]] += weight
                probs = {k: v/(p["prior_strength"]+sum(weights)) for k, v in numerator.items()}
                self.status[session][aid] = probs
                pace_history = self.history_model(asset, session)
                h, fallback = pace_history["score"], pace_history["fallback"]
                f = self.practice[session].get(aid)
                a = h if f is None else (1-p["practice_weight"])*h + p["practice_weight"]*f
                self.strength[session][aid] = math.exp((a-self.size)/p["temperature"])
                self.audit[f"{session}:{aid}"] = {"status_probabilities": probs, "prior": prior,
                    "prior_sample_count": len(pool), "sample_count": len(recent), "effective_sample_size": ess(weights),
                    "sample_weights": weights,
                    "history_score": h, "practice_score": f, "combined_score": a, "rank_fallback": fallback,
                    "pace_history": pace_history, "practice_weight": 0 if f is None else p["practice_weight"],
                    "strength": self.strength[session][aid],
                    "source_refs": sorted({r["source_ref"] for r in rows+pool}), "rounds": [r["round"] for r in recent]}
                if session != "qualifying":
                    nc = [r for r in rows if r["status"] in {"nc", "dns"} and r.get("started") is not None]
                    if not nc:
                        nc = [r for r in pool if r["status"] in {"nc", "dns"} and r.get("started") is not None]
                    nc = self.recent(nc)
                    if nc:
                        nc_weights = self.weights(nc)
                        self.started[session][aid] = sum(w*r["started"] for r, w in zip(nc, nc_weights))/sum(nc_weights)
                    else:
                        prior_started = data.get("priors", {}).get(session, {}).get("nc_started_probability")
                        if prior_started is None:
                            raise ValueError(f"{session}: NC/DNS split unavailable; import classification/start evidence or an explicit prior")
                        self.started[session][aid] = number(prior_started, "nc_started_probability", 0, 1)
                    self.audit[f"{session}:{aid}"].update(nc_started_probability=self.started[session][aid],
                                                          nc_start_evidence_count=len(nc))
            if session != "qualifying":
                for award in (["fastest_lap", "driver_of_day"] if session == "race" else ["fastest_lap"]):
                    self.awards[session, award] = self.award_probabilities(session, award)
        self.pit_pools, self.pit_mode = self.prepare_pits()
        self.pit_weights = {cid: self.weights(rows) for cid, rows in self.pit_pools.items()}

    def check_evidence(self, row, field, label):
        moment = timestamp(row.get(field), label)
        if row.get("source_ref") not in self.source_ids:
            raise ValueError(f"{label} requires a registered source")
        if moment > self.cutoff:
            raise ValueError(f"{label} after cutoff")
        if moment > self.source_times[row["source_ref"]]:
            raise ValueError(f"{label} after source snapshot")

    def weights(self, rows, target=None):
        target = target or self.target
        if any(row["round"] >= target for row in rows):
            raise ValueError("weighted observations must precede the target round")
        half_life = self.parameters["half_life"]
        if self.parameters["decay_mode"] == "exponential":
            return [2**(-(target-1-row["round"])/half_life) for row in rows]
        # Each valid round has one age, including when a fallback pool has two drivers.
        ages = {rnd: age for age, rnd in enumerate(sorted({r["round"] for r in rows}, reverse=True))}
        return [max(0.0, 1-ages[row["round"]]/(2*half_life)) for row in rows]

    def recent(self, rows):
        rounds = sorted({r["round"] for r in rows}, reverse=True)[:self.parameters["window"]]
        return sorted((r for r in rows if r["round"] in rounds), key=lambda r: (r["round"], r.get("asset_id", "")))

    def validate_history(self, rows):
        seen, result = {}, []
        for original in rows:
            row = dict(original)
            integer(row.get("round"), "history.round", 1, self.target-1)
            if row.get("season", self.config["season"]) != self.config["season"]:
                raise ValueError("history season mismatch; previous seasons belong in explicit priors")
            self.check_evidence(row, "completed_at", "history completion")
            if row.get("session") not in {"qualifying", "race", "sprint"} or row.get("status") not in {"classified", "nc", "dns", "dsq"}:
                raise ValueError("invalid historical session/status")
            if not row.get("person_id") or not row.get("constructor_id"):
                raise ValueError("history needs real person and historical constructor identities")
            if row.get("circuit_id") is not None and (not isinstance(row["circuit_id"], str) or not row["circuit_id"].strip()):
                raise ValueError("historical circuit_id must be a nonempty string or null")
            integer(row.get("field_size"), "historical field size", 2)
            if row["status"] == "classified":
                integer(row.get("position"), "history.position", 1, row["field_size"])
            elif row.get("position") is not None:
                raise ValueError("nonclassified history cannot have a finishing position")
            if row.get("start_position") is not None:
                integer(row["start_position"], "history.start_position", 1, row["field_size"])
            if row.get("started") is not None and not isinstance(row["started"], bool):
                raise ValueError("history.started must be boolean or null")
            if (row["status"] == "dns" and row.get("started") is not False) or (row["status"] == "classified" and row.get("started") is False):
                raise ValueError("historical started flag contradicts classification")
            if row["session"] != "qualifying":
                integer(row.get("overtakes"), "historical overtakes", 0)
                for award in ("fastest_lap", "driver_of_day"):
                    if not isinstance(row.get(award), bool):
                        raise ValueError("historical awards must be boolean")
                if row["status"] in {"dns", "dsq"} and (row["overtakes"] or row["fastest_lap"] or row["driver_of_day"]):
                    raise ValueError("historical DNS/DSQ retains ineligible rewards")
            key = (row["person_id"], row["round"], row["session"])
            if key in seen:
                raise ValueError(f"duplicate historical person/session (including old asset cards): {key}")
            seen[key] = row
            result.append(row)
        return result

    def validate_grid(self):
        grid = self.data.get("grid", {})
        if any(r.get("status") == "unverified" for r in grid.get("events", [])):
            self.warnings.add("Unverified penalty reports retained in grid input but not applied")
        for session, record in grid.get("official_orders", {}).items():
            if session not in self.sessions or record.get("source_ref") not in self.source_ids:
                raise ValueError("official grid has invalid session/source")
            self.check_evidence(record, "published_at", "grid publication")
            ids = record.get("asset_ids", [])
            if len(ids) != self.size or set(ids) != set(self.ids):
                raise ValueError("official grid must cover full active field")
        if grid.get("joint_probability_source") and grid["joint_probability_source"] not in self.source_ids:
            raise ValueError("unknown joint penalty probability source")
        if grid.get("pit_lane_convention"):
            if grid["pit_lane_convention"].get("source_ref") not in self.source_ids:
                raise ValueError("pit-lane convention requires registered source")
            self.warnings.add("Pit-lane order is normalized; extra pit-exit delay is not modeled")
        if self.events and self.grid_rules.get("season") != self.config["season"]:
            raise ValueError("grid rules season mismatch")

    def history_model(self, asset, session, target=None):
        target = target or self.target
        own = sorted((r for r in self.history if r["person_id"] == asset["person_id"] and r["session"] == session and r["round"] < target), key=lambda r: r["round"], reverse=True)
        spell = []
        for row in own:
            if row["constructor_id"] != asset["constructor_id"]:
                break
            spell.append(row)
        rows = self.recent([r for r in spell if r["status"] == "classified"])
        fallback = "own_current_spell"
        if not rows:
            rows = self.recent([r for r in self.history if r["session"] == session and r["round"] < target
                                and r["constructor_id"] == asset["constructor_id"] and r["status"] == "classified"])
            fallback = "constructor"
        if not rows:
            fallback = "midfield"
        weights = self.weights(rows, target)
        score = (sum(w*rank_score(r["position"], r["field_size"], self.size) for w, r in zip(weights, rows))/sum(weights)
                 if rows else (self.size+1)/2)
        return {"session": session, "score": score, "fallback": fallback, "sample_count": len(rows),
                "effective_sample_size": ess(weights), "rounds": [r["round"] for r in rows],
                "sample_weights": weights, "source_refs": sorted({r["source_ref"] for r in rows})}

    def history_score(self, asset, session, target=None):
        model = self.history_model(asset, session, target)
        return model["score"], model["fallback"]

    def practice_scores(self):
        tags = defaultdict(set)
        for news in self.data.get("news", []):
            if news.get("tag") not in {"incident_compensation", "handling_instability"}:
                raise ValueError("practice news supports incident_compensation/handling_instability; use grid.events for penalties")
            if news.get("source_ref") not in self.source_ids or not news.get("quote") or not news.get("incident_id"):
                raise ValueError("practice news requires a fact id, source and original quote")
            self.check_evidence(news, "published_at", "news publication")
            persons = news.get("person_ids", [])
            if not persons and news.get("constructor_id"):
                persons = [a["person_id"] for a in self.drivers if a["constructor_id"] == news["constructor_id"]]
            if not persons or not set(persons) <= {a["person_id"] for a in self.drivers}:
                raise ValueError("news targets unknown drivers")
            if not news.get("affected_sessions") or not set(news["affected_sessions"]) <= {"fp1", "fp2", "fp3"}:
                raise ValueError("news must identify affected practice sessions")
            for person in persons:
                for session in news["affected_sessions"]:
                    tags[person, session, news["tag"]].add(news["incident_id"])
        rows = {session: defaultdict(list) for session in self.sessions}
        seen, ranks = set(), set()
        for row in self.data.get("practice", []):
            self.check_evidence(row, "completed_at", "practice completion")
            key = (row["person_id"], row["session"])
            if key in seen or row["session"] not in {"fp1", "fp2", "fp3"}:
                raise ValueError("duplicate/invalid practice session")
            seen.add(key)
            integer(row.get("field_size"), "practice field size", 2)
            rank = row.get("rank")
            if rank is not None:
                integer(rank, "practice rank", 1, row["field_size"])
                if (row["session"], rank) in ranks:
                    raise ValueError("duplicate practice rank")
                ranks.add((row["session"], rank))
            aid = row.get("asset_id")
            if aid is None:
                continue  # Reserve drivers keep their own row and never replace a regular's FP.
            if aid not in self.by_id or self.by_id[aid]["person_id"] != row["person_id"]:
                raise ValueError("practice identity/asset mismatch")
            incident = bool(tags[key + ("incident_compensation",)])
            instability = bool(tags[key + ("handling_instability",)])
            raw, observed_score = None, None
            if rank is not None:
                raw = rank_score(rank, row["field_size"], self.size)
                observed_score = max(1, min(self.size, raw + incident*self.parameters["incident_bonus"] - instability*self.parameters["instability_penalty"]))
            weight = self.parameters["fp_weights"][row["session"]]
            for session in self.sessions:
                adjusted, fallback = observed_score, None
                if rank is None and incident:
                    # Missing FP ranks must not leak qualifying history into race pace.
                    adjusted, fallback = self.history_score(self.by_id[aid], session)
                record = {**row, "forecast_session": session, "raw_score": raw,
                          "adjusted_score": adjusted, "fallback": fallback,
                          "incident_ids": sorted(tags[key + ("incident_compensation",)]),
                          "instability_ids": sorted(tags[key + ("handling_instability",)])}
                self.adjustments.append(record)
                if adjusted is not None and weight > 0:
                    rows[session][aid].append((adjusted, weight))
        for person, session, tag in tags:
            if (person, session) not in seen:
                self.warnings.add(f"{person}/{session}/{tag}: no practice observation; supply a sourced rank:null row for an unranked participant")
        return {session: {aid: sum(v*w for v, w in pairs)/sum(w for _, w in pairs)
                          for aid, pairs in by_driver.items()} for session, by_driver in rows.items()}

    def award_probabilities(self, session, award):
        games = defaultdict(list)
        for row in self.history:
            if row["session"] == session:
                games[row["round"]].append(row)
        by_person = {a["person_id"]: a["asset_id"] for a in self.drivers}
        observations = []
        for rnd, rows in sorted(games.items()):
            winners = [r["person_id"] for r in rows if r[award]]
            if len(winners) > 1:
                raise ValueError("multiple historical award winners")
            if len(rows) != rows[0]["field_size"]:
                continue
            if winners and winners[0] not in by_person:
                continue
            observations.append({"round": rnd, "winner": by_person[winners[0]] if winners else "none"})
        recent = self.recent(observations)
        recent_rounds = {r["round"] for r in recent}
        older = [r for r in observations if r["round"] not in recent_rounds]
        support = self.ids + ["none"]
        counts = Counter(r["winner"] for r in older)
        values = {aid: self.parameters["prior_strength"]*(counts[aid]+0.5)/(len(older)+0.5*len(support)) for aid in support}
        weights = self.weights(recent)
        for row, weight in zip(recent, weights):
            values[row["winner"]] += weight
        total = sum(values.values())
        self.audit[f"{session}:{award}"] = {"sample_count": len(recent), "prior_sample_count": len(older),
                                             "uniform_prior": not older, "effective_sample_size": ess(weights),
                                             "rounds": [r["round"] for r in recent], "sample_weights": weights,
                                             "probabilities": {aid: v/total for aid, v in values.items()}}
        return {aid: v/total for aid, v in values.items()}

    def prepare_pits(self):
        rows = self.data.get("pits", [])
        for row in rows:
            integer(row.get("round"), "pit.round", 1, self.target-1)
            if row.get("source_ref") not in self.source_ids:
                raise ValueError("pit history source missing")
            if row.get("mode") not in {"measured", "band_proxy"}:
                raise ValueError("invalid pit input mode")
            if row.get("had_stop") is not None and not isinstance(row["had_stop"], bool):
                raise ValueError("pit had_stop must be boolean/null")
            if row["mode"] == "band_proxy" and row.get("band_points") not in {0, 2, 5, 10, 20}:
                raise ValueError("unknown pit scoring band")
            if row["mode"] == "measured" and row.get("had_stop") is not False:
                if number(row.get("stationary_seconds"), "stationary_seconds", 0) == 0:
                    raise ValueError("pit time must be positive")
                if "stops" in row:
                    if not row["stops"]:
                        raise ValueError("a measured stop list cannot be empty when had_stop is true")
                    for stop in row["stops"]:
                        number(stop.get("order"), "pit stop order", 0)
                        if number(stop.get("seconds"), "pit seconds", 0) == 0:
                            raise ValueError("pit seconds must be positive")
                    if min(stop["seconds"] for stop in row["stops"]) != row["stationary_seconds"]:
                        raise ValueError("fastest stationary time disagrees with full stop list")
        measured = all(any(r["constructor_id"] == c["asset_id"] and r["mode"] == "measured" for r in rows) for c in self.constructors)
        mode = "measured" if measured else "band_proxy"
        pools = {}
        for asset in self.constructors:
            cid = asset["asset_id"]
            pool = [r for r in rows if r["constructor_id"] == cid and r["mode"] == mode]
            if not pool:
                pool = [r for r in rows if r["mode"] == mode]
                self.warnings.add(f"{cid}: pit history borrowed from field")
            if not pool:
                raise ValueError("pit input unavailable after field fallback")
            pools[cid] = self.recent(pool)
            self.audit[f"pit:{cid}"] = {"mode": mode, "sample_count": len(pools[cid]),
                                         "effective_sample_size": ess(self.weights(pools[cid])),
                                         "sample_weights": self.weights(pools[cid]),
                                         "rounds": [r["round"] for r in pools[cid]],
                                         "source_refs": sorted({r["source_ref"] for r in pools[cid]})}
        record = self.data.get("pit_record")
        self.record_seconds = self.record_source = None
        if record:
            self.check_evidence(record, "available_at", "pit record availability")
            if number(record.get("seconds"), "pit record seconds", 0) == 0:
                raise ValueError("pit record seconds must be positive")
            if mode == "measured" and all(r.get("had_stop") is False or r.get("stops") for rows in pools.values() for r in rows):
                self.record_seconds = record["seconds"]
                self.record_source = next(s["source"] for s in self.sources if s["id"] == record["source_ref"])
        if self.record_seconds is None:
            self.warnings.add("World-record probability unavailable without measured full stop chronology and pre-weekend record; no record bonus generated")
        else:
            self.warnings.add("Record estimation reuses historical stop chronology; unseen faster stops are outside empirical support")
        if mode == "band_proxy":
            self.warnings.add("Pit seconds are scoring-band proxies, not measured stationary times; zero bands may include no stops")
        return pools, mode

    def overtake_pools(self, aid, session, status):
        asset = self.by_id[aid]
        pool = [r for r in self.history if r["session"] == session and r["status"] == status
                and (status != "nc" or r.get("started") is True)]
        return [("driver", [r for r in pool if r["person_id"] == asset["person_id"]]),
                ("constructor", [r for r in pool if r["constructor_id"] == asset["constructor_id"]]),
                ("field", pool)]

    def gain_ratio(self, aid, session):
        key = (aid, session, "gain_ratio")
        if key not in self.overtake_cache:
            attempts = []
            selected = None
            for label, pool in self.overtake_pools(aid, session, "classified"):
                # A positive-gain model has its own four valid-round estimation pool.
                rows = self.recent([r for r in pool if r.get("start_position") is not None
                                    and r["start_position"] > r["position"]])
                weights = self.weights(rows)
                gains = math.fsum(w*(r["start_position"]-r["position"]) for r, w in zip(rows, weights))
                passes = math.fsum(w*r["overtakes"] for r, w in zip(rows, weights))
                record = {"method": "gain_ratio", "pool": label, "sample_count": len(rows),
                          "effective_sample_size": ess(weights), "rounds": [r["round"] for r in rows],
                          "sample_weights": weights, "weighted_gains": gains, "weighted_overtakes": passes,
                          "q": gains/passes if passes else None,
                          "q_status": "finite" if passes else "infinite" if gains else "unavailable",
                          "overtakes_per_position": passes/gains if gains else None,
                          "max_observed_gain": max((r["start_position"]-r["position"] for r in rows), default=0),
                          "source_refs": sorted({r["source_ref"] for r in rows})}
                attempts.append(record)
                if gains > 0 and ess(weights) >= self.parameters["min_effective_samples"]:
                    selected = record
                    break
            if selected is None:
                selected = {"method": "gain_ratio_unavailable", "q": None, "q_status": "unavailable",
                            "overtakes_per_position": None, "max_observed_gain": 0}
                self.warnings.add(f"{aid}/{session}: insufficient positive-gain history; empirical overtakes fallback used")
            self.overtake_cache[key] = selected
            self.overtake_audit["/".join(key)] = {**selected, "attempts": attempts, "extrapolated_gain": False}
        return self.overtake_cache[key]

    def historical_overtakes(self, aid, session, status, condition, sample):
        key = (aid, session, status, condition)
        if key not in self.overtake_cache:
            options = self.overtake_pools(aid, session, status)
            candidates = []
            if condition == "non_gaining":
                candidates += [(label, [r for r in rows if r.get("start_position") is not None
                                       and r["start_position"] <= r["position"]], "non_gaining")
                               for label, rows in options]
            candidates += [(label, rows, "same_status") for label, rows in options]
            for label, pool, used_condition in candidates:
                rows = self.recent(pool)
                if rows:
                    weights = self.weights(rows)
                    break
            else:
                raise ValueError(f"{session}/{status}: no eligible overtaking history after fallback")
            self.overtake_cache[key] = ([r["overtakes"] for r in rows], weights)
            self.overtake_audit["/".join(key)] = {"method": "empirical_fallback", "pool": label,
                "requested_condition": condition, "used_condition": used_condition,
                "sample_count": len(rows), "effective_sample_size": ess(weights),
                "rounds": [r["round"] for r in rows], "sample_weights": weights,
                "source_refs": sorted({r["source_ref"] for r in rows})}
        counts, weights = self.overtake_cache[key]
        return pick(counts, weights, self.u(sample, session, aid, "overtake_count"))

    def overtakes(self, aid, session, status, start, finish, sample):
        if status in {"dns", "dsq"}:
            return 0
        if status == "classified":
            gain = max(start-finish, 0)
            if gain:
                ratio = self.gain_ratio(aid, session)
                if ratio["overtakes_per_position"] is not None:
                    if gain > ratio["max_observed_gain"]:
                        self.overtake_audit[f"{aid}/{session}/gain_ratio"]["extrapolated_gain"] = True
                    mean = gain*ratio["overtakes_per_position"]
                    lower = math.floor(mean)
                    return lower + int(self.u(sample, session, aid, "overtake_round") < mean-lower)
            condition = "non_gaining" if not gain else "ratio_unavailable"
        else:
            condition = "started_nc"
        return self.historical_overtakes(aid, session, status, condition, sample)

    def u(self, sample, *keys):
        return uniform(self.parameters["seed"], sample, *keys)

    def pace_order(self, session, sample, namespace=None):
        return sorted(self.ids, key=lambda aid: (-math.log(max(1e-16, min(1-1e-16, self.u(sample, namespace or session, aid, "pace"))))/self.strength[session][aid], aid))

    def generate(self, active_events, use_official=True):
        events = [r for r in self.events if r["event_id"] in active_events]
        p = self.parameters
        scenarios, traffic_totals = [], defaultdict(float)
        for sample in range(p["samples"]):
            states = {}
            for session in self.sessions:
                states[session] = {}
                for aid in self.ids:
                    probs = self.status[session][aid]
                    status = pick(list(probs), list(probs.values()), self.u(sample, session, aid, "status"))
                    if session != "qualifying" and status == "nc" and self.u(sample, session, aid, "started") >= self.started[session][aid]:
                        status = "dns"
                    states[session][aid] = status
            qpace = self.pace_order("qualifying", sample)
            qorder = [a for a in qpace if states["qualifying"][a] == "classified"]
            qorder += [a for a in qpace if states["qualifying"][a] != "classified"]
            qualifying = {aid: {"status": states["qualifying"][aid],
                               "position": rank if states["qualifying"][aid] == "classified" else None,
                               "q2": rank <= self.rules["max_q2"] and states["qualifying"][aid] == "classified",
                               "q3": rank <= self.rules["max_q3"] and states["qualifying"][aid] == "classified"}
                          for rank, aid in enumerate(qorder, 1)}
            scenario = {"id": f"s{sample}", "probability": 1/p["samples"], "qualifying": qualifying}
            for session in self.sessions[1:]:
                start_order = qorder if session == "race" else self.pace_order("qualifying", sample, "sprint_grid")
                q = qualifying if session == "race" else {}
                grid = allocate_grid(start_order, q, events, session, self.data.get("grid", {}), self.grid_rules, use_official)
                pace = {aid: rank for rank, aid in enumerate(self.pace_order(session, sample), 1)}
                classified = [aid for aid in self.ids if states[session][aid] == "classified"]
                grid_weight = self.grid_weights[session]
                classified.sort(key=lambda aid: (round(grid_weight*grid[aid]+(1-grid_weight)*pace[aid], 12), grid[aid]))
                finishes = {aid: rank for rank, aid in enumerate(classified, 1)}
                results = {}
                for aid in self.ids:
                    status = states[session][aid]
                    traffic = sum(states[session][other] != "dns" and grid[other] < grid[aid] and pace[other] > pace[aid] for other in self.ids)
                    traffic_totals[session, aid] += traffic/p["samples"]
                    passes = self.overtakes(aid, session, status, grid[aid], finishes.get(aid), sample)
                    results[aid] = {"status": status, "position": finishes.get(aid), "start_position": grid[aid],
                                    "overtakes": passes, "fastest_lap": False, "driver_of_day": False}
                for award in (["fastest_lap", "driver_of_day"] if session == "race" else ["fastest_lap"]):
                    distribution = self.awards[session, award]
                    eligible = [aid for aid in self.ids if states[session][aid] not in {"dns", "dsq"}] + ["none"]
                    winner = pick(eligible, [distribution[a] for a in eligible], self.u(sample, session, award))
                    if winner != "none":
                        results[winner][award] = True
                scenario[session] = results
            pits, stop_sequence = {}, []
            representatives = {0: 3.10, 2: 2.75, 5: 2.35, 10: 2.10, 20: 1.90}
            for asset in self.constructors:
                cid = asset["asset_id"]
                rows = self.pit_pools[cid]
                row = pick(rows, self.pit_weights[cid], self.u(sample, "pit", cid))
                all_dns = all(states["race"][a["asset_id"]] == "dns" for a in self.drivers if a["constructor_id"] == cid)
                seconds = None if all_dns or row.get("had_stop") is False else row["stationary_seconds"] if self.pit_mode == "measured" else representatives[row["band_points"]] + self.u(sample, "pit_tie", cid)*0.001
                pits[cid] = {"fastest_stop_seconds": seconds, "fastest_of_race": False, "world_record": False}
                if seconds is not None and self.record_seconds is not None:
                    for index, stop in enumerate(row["stops"]):
                        stop_sequence.append((stop["order"], self.u(sample, "stop_order_tie", cid, index), cid, stop["seconds"]))
            current_record = self.record_seconds
            for _, _, cid, seconds in sorted(stop_sequence):
                if seconds < current_record:
                    pits[cid]["world_record"] = True
                    current_record = seconds
            stopped = [cid for cid in pits if pits[cid]["fastest_stop_seconds"] is not None]
            if stopped:
                if stop_sequence:
                    winner = min(stop_sequence, key=lambda stop: (stop[3], stop[0], stop[1]))[2]
                else:
                    winner = min(stopped, key=lambda cid: (pits[cid]["fastest_stop_seconds"], self.u(sample, "pit_winner_tie", cid)))
                pits[winner]["fastest_of_race"] = True
            scenario["pit_stops"] = pits
            scenarios.append(scenario)
        components = PROBABILITY_COMPONENTS | (SPRINT_COMPONENTS if "sprint" in self.sessions else set())
        evidence = [{"source": s["source"], "observed_at": s["observed_at"]} for s in self.sources]
        audits = {}
        for component in sorted(components):
            session = "qualifying" if component == "qualifying" else "sprint" if component.startswith("sprint") else "race"
            rows = self.data.get("pits", []) if component == "pit_stops" else [r for r in self.history if r["session"] == session]
            audits[component] = {"method": "v1; see model_parameters.json for per-driver, circuit and gain-ratio audit",
                                "source_refs": sorted({s["source"] for s in self.sources}),
                                "sample_count": len(rows), "effective_sample_size": ess(self.weights(rows)),
                                "parameters": p}
        if any(a.get("extrapolated_gain") for a in self.overtake_audit.values()):
            self.warnings.add("Some simulated position gains exceed the gain-ratio training range; extrapolation is flagged in model_parameters.json")
        metadata = {"season": self.config["season"], "target_round": str(self.target), "round_number": self.target,
            "format": self.config["format"], "as_of": self.config["as_of"], "lock_at": self.config["lock_at"],
            "previous_rounds": self.config.get("previous_rounds", [r for r in (self.target-2, self.target-1) if r > 0]),
            "prices_observed_at": self.config.get("prices_observed_at", self.config["as_of"]),
            "rules_version": self.rules["version"], "model_status": "scenario" if any(self.practice.values()) or self.events or self.config.get("synthetic") else "baseline",
            "method": "v1 session pace, fixed-table circuit grid influence, gain-ratio overtakes and empirical non-gaining/NC fallback",
            "circuit_models": self.circuit_models,
            "synthetic": self.config.get("synthetic", False), "evidence": evidence,
            "pit_mode": self.pit_mode, "pit_record_seconds": self.record_seconds, "pit_record_source": self.record_source,
            "pit_record_status": "unavailable" if self.record_seconds is None else "historical_chronology",
            "model_parameters": p, "active_penalties": sorted(active_events), "grid_rules_version": self.grid_rules.get("version"),
            "limitations": sorted(self.warnings | {"Uncalibrated defaults; no joint weather/reliability or lap-by-lap traffic model",
                "Fixed circuit difficulty and its 20%-80% grid-weight mapping are uncalibrated assessments; Race and Sprint share a coefficient",
                "Positive gains use an empirical overtakes/gain ratio with stochastic rounding; within-gain overtake variability is not fitted",
                "Race/Sprint pace uses classified finishing ranks, not lap times; observed practice ranks are shared across session models",
                "NC/DNS split excludes historical records without start evidence; fallback pools are documented"}),
            "probability_models": audits}
        model = {"schema_version": 1, "metadata": metadata, "assets": self.assets, "scenarios": scenarios}
        validate_model(model, self.rules)
        return model, [{"session": session, "asset_id": aid, "expected_slower_ahead": value} for (session, aid), value in sorted(traffic_totals.items())]
