"""Versioned input snapshots and deterministic report serialization."""

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from forecast_core import timestamp


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


class Sources:
    def __init__(self, base, output, cutoff, offline=False):
        self.base, self.output = Path(base), Path(output)
        self.cutoff, self.offline = timestamp(cutoff, "as_of"), offline
        self.rows = []

    def read(self, descriptor, label, json_data=True):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", label):
            raise ValueError("source ids may contain only letters, numbers, underscores and hyphens")
        if not isinstance(descriptor, dict):
            raise ValueError(f"{label}: source needs path/url, observed_at and source_ref")
        if any(row["id"] == label for row in self.rows):
            raise ValueError(f"duplicate source id: {label}")
        url = descriptor.get("url")
        fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if descriptor.get("path"):
            path = (self.base / descriptor["path"]).resolve()
            raw = path.read_bytes()
            observed = descriptor.get("observed_at")
            ref = descriptor.get("source_ref") or url
            if not observed or not ref:
                raise ValueError(f"{label}: cached inputs require observed_at and source_ref")
        elif url:
            if self.offline:
                raise ValueError(f"offline mode: no cached path for {label}")
            if timestamp(fetched, "fetch time") > self.cutoff:
                raise ValueError("cannot fetch new evidence for a past information cutoff; use a snapshot")
            request = Request(url, headers={"User-Agent": "f1-fantasy-advisor/1.0"})
            with urlopen(request, timeout=30) as response:
                raw = response.read()
            fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
            observed, ref = fetched, url
        else:
            raise ValueError(f"{label}: source requires path or url")
        if timestamp(observed, f"{label}.observed_at") > self.cutoff:
            raise ValueError(f"{label}: evidence after cutoff")
        suffix = ".json" if json_data else ".html"
        destination = self.output / "raw" / (label + suffix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        self.rows.append({"id": label, "source": ref, "observed_at": observed,
                          "copied_at": fetched, "sha256": hashlib.sha256(raw).hexdigest(),
                          "raw_path": str(destination.relative_to(self.output)),
                          "timestamp_basis": "declared_snapshot" if descriptor.get("path") else "fetched"})
        return json.loads(raw) if json_data else raw.decode("utf-8")
