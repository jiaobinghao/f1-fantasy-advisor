"""Look up fixed, versioned circuit assessments; no race-week fitting or fetching."""

import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from forecast_core import number

PROFILE_PATH = Path(__file__).resolve().parent.parent / "references" / "circuit-profiles.json"


def circuit_key(value):
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))


def profile_index(table):
    index = {}
    for row in table["circuits"]:
        number(row["difficulty"], "circuit difficulty", 0, 1)
        for alias in [row["circuit_id"], row["name_en"], *row["aliases"]]:
            key = circuit_key(alias)
            if not key or (key in index and index[key] is not row):
                raise ValueError(f"empty or ambiguous circuit alias: {alias}")
            index[key] = row
    return index


def load_profiles(path=None):
    table = json.loads(Path(path or PROFILE_PATH).read_text(encoding="utf-8"))
    if table.get("schema_version") != 1 or not table.get("version") or not table.get("circuits"):
        raise ValueError("circuit profiles require schema_version=1, version and circuits")
    number(table["unknown_difficulty"], "unknown circuit difficulty", 0, 1)
    date.fromisoformat(table["assessed_on"])
    source_ids = {s["id"] for s in table["sources"]}
    if len(source_ids) != len(table["sources"]):
        raise ValueError("duplicate circuit source ids")
    for row in table["circuits"]:
        if not row["source_refs"] or not set(row["source_refs"]) <= source_ids:
            raise ValueError("circuit profile requires known source_refs")
        if row["confidence"] not in {"low", "medium", "high"}:
            raise ValueError("invalid circuit evidence confidence")
    profile_index(table)
    return table


def canonical_circuit(value, table):
    row = profile_index(table).get(circuit_key(value))
    return row["circuit_id"] if row else circuit_key(value)


def circuit_models(circuit_id, format, override, table):
    row = profile_index(table).get(circuit_key(circuit_id))
    selected = copy.deepcopy(row) if row else {
        "circuit_id": circuit_id, "difficulty": table["unknown_difficulty"],
        "confidence": "low", "source_refs": [], "rationale_en": "Unknown circuit: table fallback."
    }
    selected["method"] = "fixed_table" if row else "generic_fallback"
    selected["table_difficulty"] = row["difficulty"] if row else None
    if override is not None:
        selected.update(difficulty=number(override, "circuit_difficulty", 0, 1), method="configured_scenario")
    selected["grid_weight"] = round(0.2 + 0.6 * selected["difficulty"], 12)
    selected["pace_weight"] = round(1 - selected["grid_weight"], 12)
    raw = json.dumps(table, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    audit = {"circuit_id": circuit_id, "selected": selected,
             "table_version": table["version"], "assessed_on": table["assessed_on"],
             "table_content_sha256": hashlib.sha256(raw).hexdigest(),
             "sources": [s for s in table["sources"] if s["id"] in selected["source_refs"]],
             "calibration_status": "uncalibrated", "formula": "g=0.2+0.6*d; pace_weight=1-g",
             "session_assumption": "Race and Sprint share the fixed circuit difficulty."}
    return {s: copy.deepcopy(audit) for s in ["race"] + (["sprint"] if format == "sprint" else [])}
