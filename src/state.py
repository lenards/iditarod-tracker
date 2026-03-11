"""Loads and saves persistent race state to state.json."""

import json
import os
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "state.json"

DEFAULT_STATE = {
    "last_log": 0,
    "last_report_log": 0,
    "mushers": {},
    # mushers[name] = {
    #   "bib": str,
    #   "rookie": bool,
    #   "current_pos": int,
    #   "current_checkpoint": str,
    #   "at_checkpoint": bool,
    #   "checkpoint_history": [
    #     {
    #       "checkpoint": str,
    #       "in_time": str, "in_dogs": int,
    #       "out_time": str, "out_dogs": int,
    #       "dropped": int
    #     },
    #     ...
    #   ]
    # }
}


def load() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            data = json.load(f)
        # Merge with defaults in case new keys were added
        for k, v in DEFAULT_STATE.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULT_STATE)


def save(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_from_log(state: dict, log_data: dict) -> None:
    """
    Merge parsed log data into state.
    Tracks checkpoint history per musher to compute cumulative dropped dogs.
    """
    for m in log_data["mushers"]:
        name = m["name"]
        if not name:
            continue

        if name not in state["mushers"]:
            state["mushers"][name] = {
                "bib": m["bib"],
                "rookie": m["rookie"],
                "current_pos": m["pos"],
                "current_checkpoint": m["checkpoint"],
                "at_checkpoint": m["at_checkpoint"],
                "checkpoint_history": [],
            }

        entry = state["mushers"][name]
        entry["bib"] = m["bib"]
        entry["rookie"] = m["rookie"]
        entry["current_pos"] = m["pos"]
        entry["current_checkpoint"] = m["checkpoint"]
        entry["at_checkpoint"] = m["at_checkpoint"]

        # Record checkpoint passage if we have complete in+out data
        # and haven't recorded this checkpoint yet (or data changed)
        if not m["at_checkpoint"] and m["in_dogs"] is not None and m["out_dogs"] is not None:
            checkpoint = m["checkpoint"]
            history = entry["checkpoint_history"]

            # Check if this checkpoint is already recorded
            existing = next((h for h in history if h["checkpoint"] == checkpoint), None)
            if existing is None:
                history.append({
                    "checkpoint": checkpoint,
                    "in_time": m["in_time"],
                    "in_dogs": m["in_dogs"],
                    "out_time": m["out_time"],
                    "out_dogs": m["out_dogs"],
                    "dropped": m["dropped"],
                })
            else:
                # Update in case the record was corrected
                existing.update({
                    "in_time": m["in_time"],
                    "in_dogs": m["in_dogs"],
                    "out_time": m["out_time"],
                    "out_dogs": m["out_dogs"],
                    "dropped": m["dropped"],
                })


def total_dropped(musher_state: dict) -> int:
    return sum(h["dropped"] for h in musher_state.get("checkpoint_history", []))
