"""Builds the structured race report sections from state."""

from .state import total_dropped

# Expedition Class mushers run alongside competitive mushers but are not
# racing for a placement.  They skip mandatory rests, can rotate dogs, and
# travel with a support team.  They should be reported separately.
EXPEDITION_CLASS: set[str] = {
    "Thomas Waerner",
    "Kjell Rokke",
    "Steve Curtis",
}


def is_expedition(name: str) -> bool:
    return name in EXPEDITION_CLASS


def build_report(state: dict) -> dict:
    """
    Returns a dict with:
      - standings: list of mushers sorted by position
      - at_checkpoint: mushers currently resting at a checkpoint
      - dog_report: per-musher dropped dog history
      - scratched: any scratched mushers (dogs = 0 or flagged)
    """
    mushers = state["mushers"]

    # Sort by current position
    all_sorted = sorted(mushers.items(), key=lambda x: x[1].get("current_pos", 999))

    # Separate competitive vs expedition class
    standings = [(n, d) for n, d in all_sorted if not is_expedition(n)]
    expedition = [(n, d) for n, d in all_sorted if is_expedition(n)]

    at_checkpoint = [
        (name, data) for name, data in standings
        if data.get("at_checkpoint")
    ]

    # Dog report: only competitive mushers who have dropped at least 1 dog
    dog_report = []
    for name, data in standings:
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
        "standings": standings,
        "at_checkpoint": at_checkpoint,
        "dog_report": dog_report,
        "expedition": expedition,
    }


def format_report_markdown(report: dict, state: dict) -> str:
    """Formats the report as a markdown string for GitHub issue body."""
    lines = []

    # -- Standings --
    lines.append("## 🏁 Current Standings\n")
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

    # -- At Checkpoint --
    if report["at_checkpoint"]:
        lines.append("## ⛺ Currently at Checkpoint\n")
        for name, data in report["at_checkpoint"]:
            checkpoint = data["current_checkpoint"]
            history = data.get("checkpoint_history", [])
            # Find the in_dogs for the current checkpoint
            in_dogs = "?"
            # Last history entry might be the previous checkpoint; current checkpoint in-progress
            # We stored this in current state from the log
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
            at = "resting" if data["at_checkpoint"] else "en route"
            lines.append(f"- **{name}**{rookie_tag} (Bib #{data['bib']}) — {checkpoint} ({at})")
        lines.append("")

    # -- Footer --
    lines.append(f"\n---\n_Data from log #{state['last_log']}. "
                 f"Standings reflect most recent log processed._")

    return "\n".join(lines)


def format_summary_prompt(report: dict, state: dict) -> str:
    """
    Builds the text prompt for Claude to write a narrative summary.
    Includes key facts about standings, who's resting, and dog drops.
    """
    standings = report["standings"]
    at_chk = report["at_checkpoint"]
    dog_report = report["dog_report"]

    parts = []

    # Top 5
    parts.append("TOP 5 STANDINGS:")
    for name, data in standings[:5]:
        chk = data["current_checkpoint"]
        status = "resting" if data["at_checkpoint"] else "en route"
        parts.append(f"  {data['current_pos']}. {name} — {chk} ({status})")

    # Who's resting
    if at_chk:
        parts.append(f"\nMUSHERS CURRENTLY AT CHECKPOINT ({len(at_chk)}):")
        for name, data in at_chk:
            parts.append(f"  - {name} at {data['current_checkpoint']}")

    # Total field size (competitive only)
    total = len(standings)
    parts.append(f"\nTOTAL ACTIVE COMPETITIVE MUSHERS: {total}")

    # Dog drops
    if dog_report:
        parts.append("\nDOG DROPS:")
        for entry in dog_report:
            for drop in entry["drops"]:
                parts.append(f"  - {entry['name']} dropped {drop['dropped']} dog(s) at {drop['checkpoint']}")

    # Last checkpoint reached by leader
    if standings:
        leader_name, leader_data = standings[0]
        parts.append(f"\nRACE LEADER: {leader_name} at {leader_data['current_checkpoint']}")

    # Expedition class — separate from competitive field
    expedition = report.get("expedition", [])
    if expedition:
        parts.append("\nEXPEDITION CLASS (not competing for placement — they travel with support "
                     "teams, may rotate dogs, and skip mandatory rests):")
        for name, data in expedition:
            chk = data["current_checkpoint"]
            status = "resting" if data["at_checkpoint"] else "en route"
            parts.append(f"  - {name} — {chk} ({status})")

    return "\n".join(parts)
