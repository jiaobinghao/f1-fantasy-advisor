"""Fictional, portable end-to-end inputs; never actual race advice."""

from pathlib import Path

from forecast_io import save_json


def example_data(format="standard"):
    cutoff = "2026-06-01T00:00:00Z"
    assets = [{"asset_id": f"d{i}", "person_id": f"person{i}", "name": f"Demo Driver {i}", "type": "driver",
               "constructor_id": f"c{(i+1)//2}", "price": price} for i, price in enumerate((28, 22, 18, 10, 8, 3), 1)]
    assets += [{"asset_id": f"c{i}", "name": f"Demo Constructor {i}", "type": "constructor", "price": price}
               for i, price in enumerate((18, 16, 12), 1)]
    for asset in assets:
        asset["price_history"] = [{"round": r, "points": 10 if asset["asset_id"] in {"d1", "c1"} else 30,
                                    "settled_at": "2026-05-10T00:00:00Z", "source_ref": "input"} for r in (5, 6)]
    rows, pits = [], []
    for rnd in range(1, 7):
        for session in ["qualifying", "race"] + (["sprint"] if format == "sprint" else []):
            order = [f"d{i}" for i in (range(1, 7) if rnd % 2 else (2, 1, 3, 4, 6, 5))]
            position = 0
            for grid, aid in enumerate(order, 1):
                asset = next(a for a in assets if a["asset_id"] == aid)
                status = "nc" if session != "qualifying" and rnd == 2 and aid == "d6" else "dns" if session != "qualifying" and rnd == 4 and aid == "d5" else "classified"
                if status == "classified":
                    position += 1
                rows.append({"asset_id": aid, "person_id": asset["person_id"], "constructor_id": asset["constructor_id"],
                             "round": rnd, "session": session, "field_size": 6, "status": status,
                             "position": position if status == "classified" else None, "start_position": grid,
                             "started": status != "dns", "overtakes": 0 if status == "dns" else (rnd+grid)%4,
                             "fastest_lap": aid == "d1" and session != "qualifying", "driver_of_day": aid == "d2" and session == "race",
                             "completed_at": f"2026-05-{rnd:02d}T20:00:00Z", "source_ref": "input"})
        for index in range(1, 4):
            pits.append({"round": rnd, "constructor_id": f"c{index}", "mode": "band_proxy",
                         "band_points": [2, 5, 10][(rnd+index)%3], "had_stop": True, "source_ref": "input"})
    practice = [{"asset_id": f"d{i}", "person_id": f"person{i}", "session": "fp1" if format == "sprint" else "fp2",
                 "rank": i, "field_size": 6, "completed_at": "2026-05-31T20:00:00Z", "source_ref": "input"} for i in range(1, 7)]
    news = [{"incident_id": "fictional-instability", "tag": "handling_instability", "person_ids": ["person2"],
             "affected_sessions": [practice[0]["session"]], "quote": "Synthetic example: car is difficult to drive",
             "published_at": "2026-05-31T21:00:00Z", "source_ref": "input"}]
    grid = {"events": [{"event_id": "fictional-grid-drop", "asset_id": "d1", "session": "race",
                        "penalty_type": "grid_places", "places": 5, "status": "confirmed", "rule_ref": "synthetic decision",
                        "quote": "Synthetic example: five-place grid penalty", "published_at": "2026-05-31T21:00:00Z", "source_ref": "input"}]}
    data = {"assets": assets, "history": rows, "practice": practice, "pits": pits, "news": news, "grid": grid}
    config = {"schema_version": 1, "season": 2026, "target_round": 7, "format": format, "synthetic": True,
              "as_of": cutoff, "lock_at": "2026-06-01T18:00:00Z", "teams": "teams.json",
              "input": {"path": "inputs.json", "source_ref": "Synthetic example; not real F1 observations", "observed_at": cutoff},
              "model_parameters": {"samples": 256, "seed": 42}}
    teams = {"schema_version": 1, "teams": [{"team_id": f"DemoT{i}", "previous_lineup": ["d1", "d2", "d3", "d4", "d5", "c1", "c2"],
                                              "bank": i, "free_transfers": 2} for i in range(1, 4)]}
    return config, data, teams


def write_run_example(output, format="standard"):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("example directory must be empty")
    config, data, teams = example_data(format)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("run_config.json", config), ("inputs.json", data), ("teams.json", teams)):
        save_json(output / name, value)
    return {"example_directory": str(output), "warning": "All data are synthetic; use only to exercise the pipeline"}
