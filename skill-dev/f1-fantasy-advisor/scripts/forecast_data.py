"""Normalize public Fantasy events and F1 practice tables for the v1 forecast."""

from collections import defaultdict
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

from fetch_fantasy_public import WEB_CONFIG_URL, PLAYER_STATS_URL, resolve_common_statistics_url, fpoints_group
from forecast_core import integer, number, timestamp


def identity(name):
    return "-".join(re.findall(r"\w+", name.casefold()))


def ordinal(value):
    match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", str(value).strip())
    return int(match[1]) if match else None


def feed_flag(value):
    if value in (0, "0", False, None):
        return False
    if value in (1, "1", True):
        return True
    raise ValueError(f"unrecognized public-feed flag: {value!r}")


class ResultTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.links, self.titles = [], [], []
        self.table = self.row = self.cell = None
        self.heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"title", "h1"}:
            self.heading = True
        if tag == "table":
            self.table = []
        if tag == "tr" and self.table is not None:
            self.row = []
        if tag in {"th", "td"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data.strip())
        if self.heading:
            self.titles.append(data)

    def handle_endtag(self, tag):
        if tag in {"title", "h1"}:
            self.heading = False
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(x for x in self.cell if x))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def practice_table(html, spec, assets, source_ref):
    parser = ResultTable()
    parser.feed(html)
    title = " ".join(parser.titles).casefold()
    for token in spec.get("title_contains", []):
        if str(token).casefold() not in title:
            raise ValueError(f"practice page title does not contain {token!r}")
    session = spec["session"]
    if session not in {"fp1", "fp2", "fp3"}:
        raise ValueError("practice session must be fp1/fp2/fp3")
    table = next((t for t in parser.tables if t and "Pos." in t[0] and "Driver" in t[0]), None)
    if table is None:
        raise ValueError("practice page has no result table")
    headers = table[0]
    if not {"Team", "No."} <= set(headers):
        raise ValueError("practice table missing identity columns")
    drivers = [a for a in assets if a["type"] == "driver" and a.get("active", True)]
    rows, seen = [], set()
    for cells in table[1:]:
        if len(cells) != len(headers):
            raise ValueError("incomplete practice result row")
        raw = dict(zip(headers, cells))
        # Responsive pages include the abbreviation after the full name.
        name = re.sub(r"\s+[A-Z]{3}$", "", raw["Driver"]).strip()
        matches = [a for a in drivers if identity(a["name"]) == identity(name)
                   or name in a.get("aliases", [])]
        if len(matches) > 1 or raw["No."] in seen:
            raise ValueError("duplicate practice participant")
        seen.add(raw["No."])
        asset = matches[0] if matches else None
        rank = ordinal(raw["Pos."])
        rows.append({"asset_id": asset["asset_id"] if asset else None,
                     "person_id": asset["person_id"] if asset else identity(name),
                     "name": name, "constructor_id": asset.get("constructor_id") if asset else None,
                     "session": session, "rank": rank, "field_size": len(table)-1,
                     "participation_status": "ranked" if rank else "no_rank",
                     "completed_at": spec["completed_at"], "source_ref": source_ref})
    ranks = [r["rank"] for r in rows if r["rank"] is not None]
    if len(set(ranks)) != len(ranks) or any(r < 1 or r > len(rows) for r in ranks):
        raise ValueError("invalid practice ranks")
    return rows


def event_key(name):
    name = " ".join(str(name).casefold().split())
    known = {"total", "qualifying position", "qf not classified", "driver of day", "fastest pitstop",
             "2nd fastest pitstop", "both driver q3", "one driver q3", "both driver q2", "one driver q2",
             "no driver q2", "dq qualifying", "qualifying disqualified", "dq race", "dq sprint",
             "race dns", "sprint dns", "qualifying dns", "pitstop world record"}
    known |= {f"{s} {e}" for s in ("race", "sprint") for e in
              ("position", "not classified", "position gained", "position lost", "overtake bonus", "fastest lap")}
    if name not in known:
        raise ValueError(f"unknown Fantasy scoring event {name!r}; update the event map explicitly")
    return name


def event_map(stats):
    result = {}
    for entry in stats:
        key = event_key(entry["Event"])
        if key in result:
            raise ValueError(f"duplicate event {key}")
        number(entry.get("Value"), f"{key}.Value")
        result[key] = entry
    total = sum(e["Value"] for k, e in result.items() if k != "total")
    if "total" in result and abs(total-result["total"]["Value"]) > 1e-8:
        raise ValueError("Fantasy event sum differs from Total")
    return result, total


def normalize_history(asset, payload, config, source_ref, quality):
    value = payload["Value"]
    target, season = config["target_round"], config["season"]
    cutoff = timestamp(config["as_of"], "as_of")
    fixtures = {str(g["GamedayId"]): g["RaceDayWise"] for g in value["FixtureWiseStats"]}
    game_states = {int(g["GamedayId"]): g for g in value["GamedayWiseStats"]}
    history, events, weekends, pits = [], [], [], []
    field_size = config["field_size"]
    for game in value["MatchWiseStats"]:
        rnd = int(game["GamedayId"])
        if rnd >= target:
            continue
        if not feed_flag(game_states.get(rnd, {}).get("IsActive")):
            continue
        fixture = {str(r["RaceDayId"]): r for r in fixtures.get(str(rnd), [])}
        for raw in game["RaceDayWise"]:
            if str(raw.get("MatchStatus")) != "4" or not feed_flag(raw.get("IsPlayed")):
                continue
            if int(raw["Season"]) != season or timestamp(raw["SessionStartDate"], "session start") >= cutoff:
                continue
            mapped, total = event_map(raw.get("StatsWise", []))
            label = raw["SessionType"].casefold()
            session = "sprint" if any("sprint" in k for k in mapped) else "qualifying" if label == "qualifying" else "race" if label == "race" else None
            if session is None:
                continue
            sid = str(raw["RaceDayId"])
            info = fixture.get(sid, {})
            common = {"round": rnd, "season": season, "session_id": sid, "session": session,
                      "circuit_id": identity(info.get("CircuitOfficialName") or raw.get("CircuitOfficialName") or "") or None,
                      "asset_id": asset["asset_id"], "person_id": asset.get("person_id"),
                      "constructor_id": str(info.get("TeamId", asset.get("constructor_id", asset["asset_id"]))),
                      "field_size": field_size, "source_ref": source_ref,
                      "completed_at": config["as_of"], "session_start": raw["SessionStartDate"]}
            for key, entry in mapped.items():
                events.append({**common, "event_key": key, "raw_event": entry["Event"],
                               "raw_frequency": entry["Frequency"], "count": ordinal(entry["Frequency"]),
                               "points": entry["Value"]})
            if asset["type"] == "constructor":
                if session == "race":
                    band = mapped.get("fastest pitstop", {}).get("Value", 0)
                    pits.append({**common, "constructor_id": asset["asset_id"], "mode": "band_proxy",
                                 "band_points": band, "had_stop": None, "stationary_seconds": None})
                continue
            position = mapped.get(f"{session} position")
            dsq = f"dq {session}" in mapped or f"{session} disqualified" in mapped
            nc = ("qf not classified" if session == "qualifying" else f"{session} not classified") in mapped
            dns = f"{session} dns" in mapped
            if not (position or nc or dsq or dns):
                quality.append(f"Excluded unknown classification: {asset['asset_id']} round {rnd} {session}")
                continue
            status = "dsq" if dsq else "dns" if dns else "nc" if nc else "classified"
            rank = ordinal(position["Frequency"]) if position and status == "classified" else None
            if status == "classified" and rank is None:
                raise ValueError("classified result missing rank")
            overtakes = mapped.get(f"{session} overtake bonus", {}).get("Value", 0)
            gains = mapped.get(f"{session} position gained", {}).get("Value", 0)
            losses = mapped.get(f"{session} position lost", {}).get("Value", 0)
            # The Sprint loss cap prevents reconstructing a grid from a capped -10.
            grid = rank + gains + losses if rank is not None and not (session == "sprint" and losses <= -10) else None
            fl = mapped.get(f"{session} fastest lap", {}).get("Value", 0) > 0
            started = False if dns else True if status == "classified" or overtakes > 0 or fl else None
            history.append({**common, "status": status, "position": rank, "start_position": grid,
                            "started": started, "overtakes": overtakes, "fastest_lap": fl,
                            "driver_of_day": mapped.get("driver of day", {}).get("Value", 0) > 0,
                            "events_complete": True, "raw_total_points": total})
    games = sorted(value["GamedayWiseStats"], key=lambda r: int(r["GamedayId"]))
    for index, game in enumerate(games):
        rnd = int(game["GamedayId"])
        sessions = fixtures.get(str(rnd), [])
        if rnd >= target or not sessions or not all(str(s.get("MatchStatus")) == "4" for s in sessions):
            continue
        if any(int(s["Season"]) != season or timestamp(s["SessionStartDate"], "start") >= cutoff for s in sessions):
            continue
        if not feed_flag(game.get("IsActive")) or not feed_flag(game.get("IsPlayed")):
            continue
        if not game.get("StatsWise"):
            quality.append(f"Empty settled weekend event list: {asset['asset_id']} round {rnd}; price input unavailable")
            continue
        _, total = event_map(game.get("StatsWise", []))
        weekends.append({"round": rnd, "asset_id": asset["asset_id"], "points": total,
                         "price_before": game["PlayerValue"],
                         "price_after": games[index+1]["PlayerValue"] if index+1 < len(games) else asset["price"],
                         "settled_at": config["as_of"], "source_ref": source_ref})
    return history, events, weekends, pits


def collect_public(config, sources):
    spec = config["public"]
    assets = []
    if "assets" in spec:
        assets = sources.read(spec["assets"], "assets")
    else:
        web = sources.read(spec.get("web_config", {"url": WEB_CONFIG_URL}), "web_config")
        common = sources.read(spec.get("statistics", {"url": resolve_common_statistics_url(web)}), "statistics")
        if int(common["Data"]["season"]) != config["season"]:
            raise ValueError("public season differs from target")
        for kind in ("driver", "constructor"):
            for row in fpoints_group(common["Data"][kind], kind)["participants"]:
                name = row.get("playername") or row["teamname"]
                asset = {"asset_id": str(row["playerid"]), "type": kind, "name": name,
                         "price": float(row["curvalue"]), "person_id": identity(name) if kind == "driver" else None,
                         "source_ref": "statistics"}
                if kind == "driver":
                    asset["constructor_id"] = str(row["teamid"])
                assets.append(asset)
    quality, histories, events, weekends, pits = [], [], [], [], []
    target_circuit = None
    for asset in assets:
        aid = asset["asset_id"]
        asset.setdefault("person_id", identity(asset["name"]) if asset["type"] == "driver" else None)
        descriptor = spec.get("histories", {}).get(aid)
        if descriptor is None:
            template = spec.get("history_template")
            descriptor = {k: v.format(asset_id=aid) if isinstance(v, str) else v for k, v in template.items()} if template else {"url": PLAYER_STATS_URL.format(asset_id=aid)}
        payload = sources.read(descriptor, "history_" + aid)
        target_fixture = next((g for g in payload["Value"]["FixtureWiseStats"] if int(g["GamedayId"]) == config["target_round"]), None)
        if target_fixture:
            is_sprint = any("sprint" in r["SessionType"].casefold() for r in target_fixture["RaceDayWise"])
            if is_sprint != (config["format"] == "sprint"):
                raise ValueError("configured weekend format differs from public target fixture")
            circuit_ids = {identity(r["CircuitOfficialName"]) for r in target_fixture["RaceDayWise"] if r.get("CircuitOfficialName")}
            if len(circuit_ids) > 1 or (target_circuit and circuit_ids and target_circuit not in circuit_ids):
                raise ValueError("public target fixtures disagree on circuit identity")
            if circuit_ids:
                target_circuit = next(iter(circuit_ids))
        target = next((g for g in payload["Value"]["GamedayWiseStats"] if int(g["GamedayId"]) == config["target_round"]), None)
        if target is None and "active" not in asset:
            raise ValueError(f"{aid}: target-round active status unavailable")
        if target is not None:
            asset["active"] = feed_flag(target["IsActive"])
        snapshot_config = {**config, "as_of": sources.rows[-1]["observed_at"]}
        h, e, w, p = normalize_history(asset, payload, snapshot_config, "history_" + aid, quality)
        histories.extend(h); events.extend(e); weekends.extend(w); pits.extend(p)
        asset["price_history"] = [{k: r[k] for k in ("round", "points", "settled_at", "source_ref")} for r in w[-2:]]
    practice = []
    for index, page in enumerate(spec.get("practice", [])):
        label = f"practice_{index}"
        if "discover" in page:
            landing = sources.read(page["discover"], label + "_index", False)
            parser = ResultTable(); parser.feed(landing)
            links = sorted(set(urljoin(page["discover"]["url"], link) for link in parser.links if page["link_suffix"] in link))
            if len(links) != 1:
                raise ValueError("practice link discovery must identify exactly one session")
            descriptor = {"url": links[0]}
        else:
            descriptor = page["source"]
        html = sources.read(descriptor, label, False)
        practice.extend(practice_table(html, page, assets, label))
    return {"assets": assets, "history": histories, "events": events, "weekends": weekends,
            "circuit_id": target_circuit,
            "pits": pits, "practice": practice, "news": [], "grid": {},
            "quality": quality + ["Historical completion timestamps are snapshot upper bounds; derived grids omit capped Sprint losses",
                                  "Inactive asset weeks are excluded from sporting-history samples"]}
