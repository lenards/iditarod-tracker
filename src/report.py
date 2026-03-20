"""Builds the structured race report sections from state."""

from __future__ import annotations

from .state import total_dropped

# Expedition Class mushers run alongside competitive mushers but are not
# racing for a placement.  They skip mandatory rests, can rotate dogs, and
# travel with a support team.  They should be reported separately.
# This set is kept as a fallback for older state data that lacks a "status"
# field; new logs populate status directly from the HTML section headings.
EXPEDITION_CLASS: set[str] = {
    "Thomas Waerner",
    "Kjell Rokke",
    "Steve Curtis",
}


def is_expedition(name: str, data: dict | None = None) -> bool:
    """Check if a musher is Expedition Class, using status field if available."""
    if data and data.get("status") == "expedition":
        return True
    return name in EXPEDITION_CLASS


def _musher_status(name: str, data: dict) -> str:
    """Return the canonical status for a musher, with fallback for old state."""
    status = data.get("status", "")
    if status:
        return status
    # Fallback: infer from hardcoded set
    if name in EXPEDITION_CLASS:
        return "expedition"
    return "racing"


def build_report(state: dict) -> dict:
    """
    Returns a dict with:
      - finished: mushers who reached Nome, sorted by finish position
      - standings: racing mushers sorted by position
      - at_checkpoint: racing mushers currently resting
      - out_of_race: scratched/withdrawn mushers
      - dog_report: per-musher dropped dog history (competitive only)
      - expedition: Expedition Class mushers
    """
    mushers = state["mushers"]

    # Categorize each musher
    finished = []
    racing = []
    out_of_race = []
    expedition = []

    for name, data in mushers.items():
        status = _musher_status(name, data)
        if status == "finished":
            finished.append((name, data))
        elif status == "out_of_race":
            out_of_race.append((name, data))
        elif status == "expedition":
            expedition.append((name, data))
        else:
            racing.append((name, data))

    # Sort each group
    finished.sort(key=lambda x: x[1].get("current_pos", 999))
    racing.sort(key=lambda x: x[1].get("current_pos", 999))
    out_of_race.sort(key=lambda x: x[1].get("current_pos", 999))
    expedition.sort(key=lambda x: x[1].get("current_pos", 999))

    at_checkpoint = [
        (name, data) for name, data in racing
        if data.get("at_checkpoint")
    ]

    # Dog report: only competitive mushers (racing + finished) who dropped dogs
    dog_report = []
    for name, data in finished + racing:
        drops = [
            h for h in data.get("checkpoint_history", []) if h["dropped"] > 0
        ]
        if drops:
            history = data.get("checkpoint_history", [])
            if history:
                last = history[-1]
                cur_dogs = last["in_dogs"] if data.get("at_checkpoint") else last["out_dogs"]
            else:
                cur_dogs = None
            dog_report.append({
                "name": name,
                "bib": data["bib"],
                "rookie": data["rookie"],
                "total_dropped": total_dropped(data),
                "current_dogs": cur_dogs,
                "drops": drops,
            })

    return {
        "finished": finished,
        "standings": racing,
        "at_checkpoint": at_checkpoint,
        "out_of_race": out_of_race,
        "dog_report": dog_report,
        "expedition": expedition,
    }


def format_report_markdown(report: dict, state: dict) -> str:
    """Formats the report as a markdown string for GitHub issue body."""
    lines = []

    # -- Finished --
    if report["finished"]:
        lines.append("## 🏁 Finished\n")
        lines.append("| Pos | Musher | Bib | Race Time | Avg Speed | Dogs In |")
        lines.append("|-----|--------|-----|-----------|-----------|---------|")
        for name, data in report["finished"]:
            pos = data["current_pos"]
            bib = data["bib"]
            rookie_tag = " (r)" if data.get("rookie") else ""
            race_time = data.get("total_race_time", "")
            avg_speed = data.get("avg_speed", "")
            in_dogs = ""
            history = data.get("checkpoint_history", [])
            if history:
                in_dogs = str(history[-1].get("in_dogs", ""))
            elif data.get("in_dogs") is not None:
                in_dogs = ""
            lines.append(f"| {pos} | 🏁 {name}{rookie_tag} | Bib #{bib} | {race_time} | {avg_speed} | {in_dogs} |")
        lines.append("")

    # -- Racing Standings --
    if report["standings"]:
        lines.append("## 🏃 Racing\n")
        lines.append("| Pos | Musher | Bib | Checkpoint | Status | Dogs Out |")
        lines.append("|-----|--------|-----|------------|--------|----------|")

        for name, data in report["standings"]:
            pos = data["current_pos"]
            bib = data["bib"]
            checkpoint = data["current_checkpoint"]
            rookie_tag = " (r)" if data.get("rookie") else ""
            at = "🛑 resting" if data["at_checkpoint"] else "🏃 en route"
            out_dogs = ""
            history = data.get("checkpoint_history", [])
            if history:
                last = history[-1]
                out_dogs = str(last["out_dogs"]) if not data["at_checkpoint"] else str(last.get("in_dogs", ""))
            lines.append(f"| {pos} | {name}{rookie_tag} | Bib #{bib} | {checkpoint} | {at} | {out_dogs} |")

        lines.append("")

    # -- Out of Race --
    if report["out_of_race"]:
        lines.append("## ❌ Out of Race\n")
        for name, data in report["out_of_race"]:
            rookie_tag = " (r)" if data.get("rookie") else ""
            checkpoint = data["current_checkpoint"]
            reason = data.get("withdrawal_reason", "Scratched")
            lines.append(f"- **{name}**{rookie_tag} (Bib #{data['bib']}) — {reason} at **{checkpoint}**")
        lines.append("")

    # -- At Checkpoint --
    if report["at_checkpoint"]:
        lines.append("## ⛺ Currently at Checkpoint\n")
        for name, data in report["at_checkpoint"]:
            checkpoint = data["current_checkpoint"]
            rookie_tag = " (r)" if data.get("rookie") else ""
            lines.append(f"- **{name}**{rookie_tag} (Bib #{data['bib']}) — resting at **{checkpoint}**")
        lines.append("")

    # -- Dog Report --
    lines.append("## 🐕 Dog Report\n")

    if not report["dog_report"]:
        lines.append("_No dogs dropped yet._\n")
    else:
        for entry in report["dog_report"]:
            rookie_tag = " (r)" if entry.get("rookie") else ""
            cur = entry["current_dogs"]
            dogs_str = f"{cur} dogs running - " if cur is not None else ""
            lines.append(f"**{entry['name']}**{rookie_tag} (Bib #{entry['bib']}) — {dogs_str}{entry['total_dropped']} dropped")
            for drop in entry["drops"]:
                lines.append(f"  - Dropped **{drop['dropped']}** at {drop['checkpoint']} "
                             f"(in: {drop['in_dogs']}, out: {drop['out_dogs']})")
            lines.append("")

    # -- Expedition Class --
    if report.get("expedition"):
        lines.append("## 🧭 Expedition Class\n")
        lines.append("_These mushers are not competing for placement. They travel with support "
                      "teams, may rotate dogs, and are not subject to mandatory rest rules._\n")
        for name, data in report["expedition"]:
            checkpoint = data["current_checkpoint"]
            rookie_tag = " (r)" if data.get("rookie") else ""
            if checkpoint.lower() == "nome":
                at = "finished"
            elif data["at_checkpoint"]:
                at = "resting"
            else:
                at = "en route"
            lines.append(f"- **{name}**{rookie_tag} (Bib #{data['bib']}) — {checkpoint} ({at})")
        lines.append("")

    # -- Footer --
    lines.append(f"\n---\n_Data from log #{state['last_log']}. "
                 f"Standings reflect most recent log processed._")

    return "\n".join(lines)


def format_summary_prompt(report: dict, state: dict) -> str:
    """
    Builds the text prompt for Claude to write a narrative summary.
    Includes key facts about standings, who's resting, finished, out of race, and dog drops.
    """
    finished = report["finished"]
    standings = report["standings"]
    at_chk = report["at_checkpoint"]
    out_of_race = report["out_of_race"]
    dog_report = report["dog_report"]

    parts = []

    # Finished mushers
    if finished:
        parts.append(f"MUSHERS WHO HAVE FINISHED ({len(finished)}):")
        for name, data in finished:
            race_time = data.get("total_race_time", "")
            time_str = f" in {race_time}" if race_time else ""
            parts.append(f"  {data['current_pos']}. {name}{time_str}")
        parts.append("")

    # Top 5 still racing
    if standings:
        top_n = min(5, len(standings))
        parts.append(f"TOP {top_n} RACING:")
        for name, data in standings[:top_n]:
            chk = data["current_checkpoint"]
            status = "resting" if data["at_checkpoint"] else "en route"
            parts.append(f"  {data['current_pos']}. {name} — {chk} ({status})")

    # Who's resting
    if at_chk:
        parts.append(f"\nMUSHERS CURRENTLY AT CHECKPOINT ({len(at_chk)}):")
        for name, data in at_chk:
            parts.append(f"  - {name} at {data['current_checkpoint']}")

    # Out of Race
    if out_of_race:
        parts.append(f"\nOUT OF RACE ({len(out_of_race)}):")
        for name, data in out_of_race:
            reason = data.get("withdrawal_reason", "Scratched")
            parts.append(f"  - {name} — {reason} at {data['current_checkpoint']}")

    # Total field size
    total_competitive = len(finished) + len(standings)
    parts.append(f"\nTOTAL COMPETITIVE MUSHERS: {total_competitive} ({len(finished)} finished, {len(standings)} racing, {len(out_of_race)} out of race)")

    # Dog drops
    if dog_report:
        parts.append("\nDOG DROPS:")
        for entry in dog_report:
            for drop in entry["drops"]:
                parts.append(f"  - {entry['name']} dropped {drop['dropped']} dog(s) at {drop['checkpoint']}")

    # Race leader (first racer still on trail)
    if standings:
        leader_name, leader_data = standings[0]
        parts.append(f"\nRACE LEADER (on trail): {leader_name} at {leader_data['current_checkpoint']}")

    # Expedition class — separate from competitive field
    expedition = report.get("expedition", [])
    if expedition:
        parts.append("\nEXPEDITION CLASS (not competing for placement — they travel with support "
                     "teams, may rotate dogs, and skip mandatory rests):")
        for name, data in expedition:
            chk = data["current_checkpoint"]
            if chk.lower() == "nome":
                status = "finished"
            elif data["at_checkpoint"]:
                status = "resting"
            else:
                status = "en route"
            parts.append(f"  - {name} — {chk} ({status})")

    return "\n".join(parts)
