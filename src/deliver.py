"""Delivers race reports via GitHub Issues and Discord webhook."""

import os
import requests
from datetime import datetime, timezone

from .report import is_expedition


REPO = "lenards/iditarod-tracker"
LABEL = "race-report"


def _gh_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN or GH_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_label_exists() -> None:
    """Create the 'race-report' label if it doesn't exist."""
    url = f"https://api.github.com/repos/{REPO}/labels"
    headers = _gh_headers()

    resp = requests.get(url, headers=headers, timeout=15)
    existing = {lbl["name"] for lbl in resp.json()} if resp.ok else set()

    if LABEL not in existing:
        requests.post(
            url,
            headers=headers,
            json={"name": LABEL, "color": "0075ca", "description": "Automated Iditarod race report"},
            timeout=15,
        )


def post_issue(title: str, body: str) -> str:
    """Creates a GitHub issue and returns the issue URL."""
    ensure_label_exists()

    url = f"https://api.github.com/repos/{REPO}/issues"
    payload = {
        "title": title,
        "body": body,
        "labels": [LABEL],
    }

    resp = requests.post(url, headers=_gh_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["html_url"]


def build_issue_title(state: dict) -> str:
    now = datetime.now(timezone.utc)
    # Format in a human-friendly way
    date_str = now.strftime("%B %-d, %Y %-I:%M %p UTC")

    mushers = state.get("mushers", {})
    # Find race leader — first competitive racer still racing
    competitive_racing = {
        n: d for n, d in mushers.items()
        if not is_expedition(n, d) and d.get("status", "racing") == "racing"
    }
    # Find latest finisher
    competitive_finished = {
        n: d for n, d in mushers.items()
        if not is_expedition(n, d) and d.get("status") == "finished"
    }

    if competitive_finished:
        # Show winner or latest finisher count
        winner = min(competitive_finished.items(), key=lambda x: x[1].get("current_pos", 999))
        total_finished = len(competitive_finished)
        if competitive_racing:
            leader = min(competitive_racing.items(), key=lambda x: x[1].get("current_pos", 999))
            return f"Race Report — {date_str} | {total_finished} finished, {leader[0]} leading on trail"
        return f"Race Report — {date_str} | {total_finished} mushers finished, Winner: {winner[0]}"

    if competitive_racing:
        leader = min(competitive_racing.items(), key=lambda x: x[1].get("current_pos", 999))
        return f"Race Report — {date_str} | Leader: {leader[0]} at {leader[1].get('current_checkpoint', '')}"

    return f"Race Report — {date_str}"


def build_full_body(summary: str, report_md: str) -> str:
    return f"## Race Summary\n\n{summary}\n\n---\n\n{report_md}"


def _build_finished_text(state: dict) -> str:
    """Compact list of finished competitive mushers for Discord."""
    mushers = state.get("mushers", {})
    finished = sorted(
        ((n, d) for n, d in mushers.items()
         if not is_expedition(n, d) and d.get("status") == "finished"),
        key=lambda x: x[1].get("current_pos", 999),
    )

    if not finished:
        return ""

    lines = []
    for name, data in finished:
        pos = data["current_pos"]
        rookie = " (r)" if data.get("rookie") else ""
        race_time = data.get("total_race_time", "")
        time_str = f" — {race_time}" if race_time else ""
        lines.append(f"`{pos:>2}.` 🏁 **{name}**{rookie} (Bib #{data['bib']}){time_str}")

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text


def _build_standings_text(state: dict, max_mushers: int = 37) -> str:
    """Compact standings list for Discord (no markdown tables). Only racing mushers."""
    mushers = state.get("mushers", {})
    sorted_mushers = sorted(
        ((n, d) for n, d in mushers.items()
         if not is_expedition(n, d) and d.get("status", "racing") == "racing"),
        key=lambda x: x[1].get("current_pos", 999),
    )

    lines = []
    for name, data in sorted_mushers[:max_mushers]:
        pos = data["current_pos"]
        checkpoint = data["current_checkpoint"]
        status = "🛑" if data["at_checkpoint"] else "🏃"
        rookie = " (r)" if data.get("rookie") else ""
        lines.append(f"`{pos:>2}.` {status} **{name}**{rookie} (Bib #{data['bib']}) — {checkpoint}")

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text or "_No mushers currently racing._"


def _build_out_of_race_text(state: dict) -> str:
    """Mushers who scratched or were withdrawn."""
    mushers = state.get("mushers", {})
    out = sorted(
        ((n, d) for n, d in mushers.items()
         if not is_expedition(n, d) and d.get("status") == "out_of_race"),
        key=lambda x: x[1].get("current_pos", 999),
    )

    if not out:
        return ""

    lines = []
    for name, data in out:
        rookie = " (r)" if data.get("rookie") else ""
        reason = data.get("withdrawal_reason", "Scratched")
        checkpoint = data["current_checkpoint"]
        lines.append(f"❌ **{name}**{rookie} (Bib #{data['bib']}) — {reason} at {checkpoint}")

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text


def _build_dog_report_text(state: dict) -> str:
    """Compact dog drop summary for Discord. Excludes expedition class."""
    mushers = state.get("mushers", {})
    sorted_mushers = sorted(
        ((n, d) for n, d in mushers.items()
         if not is_expedition(n, d) and d.get("status") in ("racing", "finished", None)),
        key=lambda x: x[1].get("current_pos", 999),
    )

    lines = []
    for name, data in sorted_mushers:
        drops = [h for h in data.get("checkpoint_history", []) if h["dropped"] > 0]
        if drops:
            total = sum(h["dropped"] for h in drops)
            detail = ", ".join(f"{h['dropped']} @ {h['checkpoint']}" for h in drops)
            rookie = " (r)" if data.get("rookie") else ""
            history = data.get("checkpoint_history", [])
            cur_dogs = None
            if history:
                last = history[-1]
                cur_dogs = last["in_dogs"] if data.get("at_checkpoint") else last["out_dogs"]
            dogs_str = f"{cur_dogs} dogs - " if cur_dogs is not None else ""
            lines.append(f"**{name}**{rookie} (Bib #{data['bib']}) — {dogs_str}{total} dropped ({detail})")

    if not lines:
        return "_No dogs dropped yet._"

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text


def _build_resting_text(state: dict) -> str:
    """Competitive mushers currently resting at a checkpoint, sorted by position."""
    mushers = state.get("mushers", {})
    sorted_mushers = sorted(
        ((n, d) for n, d in mushers.items()
         if not is_expedition(n, d) and d.get("status", "racing") == "racing"),
        key=lambda x: x[1].get("current_pos", 999),
    )

    lines = []
    for name, data in sorted_mushers:
        if data.get("at_checkpoint"):
            pos = data["current_pos"]
            checkpoint = data["current_checkpoint"]
            rookie = " (r)" if data.get("rookie") else ""
            lines.append(f"`{pos:>2}.` **{name}**{rookie} (Bib #{data['bib']}) — {checkpoint}")

    if not lines:
        return "_No mushers currently resting._"

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text


def _build_expedition_text(state: dict) -> str:
    """Expedition Class mushers — shown separately from competitive field."""
    mushers = state.get("mushers", {})
    expedition = sorted(
        ((n, d) for n, d in mushers.items() if is_expedition(n, d)),
        key=lambda x: x[1].get("current_pos", 999),
    )
    if not expedition:
        return ""

    lines = ["_Not competing for placement — traveling with support teams._\n"]
    for name, data in expedition:
        checkpoint = data["current_checkpoint"]
        if checkpoint.lower() == "nome":
            status = "🏁"
        elif data["at_checkpoint"]:
            status = "🛑"
        else:
            status = "🏃"
        lines.append(f"{status} **{name}** (Bib #{data['bib']}) — {checkpoint}")

    text = "\n".join(lines)
    if len(text) > 1020:
        text = text[:1020] + "\n…"
    return text


def post_discord(summary: str, issue_url: str, state: dict) -> None:
    """
    Posts embeds to Discord:
      1. Narrative summary
      2. Finished (if any)
      3. Current standings (racing)
      4. Out of Race (if any)
      5. Resting at checkpoint
      6. Dog report
      7. Expedition class (if any)
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord.")
        return

    mushers = state.get("mushers", {})

    # Find the race leader on trail
    competitive_racing = {
        n: d for n, d in mushers.items()
        if not is_expedition(n, d) and d.get("status", "racing") == "racing"
    }
    leader_name = ""
    leader_checkpoint = ""
    if competitive_racing:
        leader = min(competitive_racing.items(), key=lambda x: x[1].get("current_pos", 999))
        leader_name = leader[0]
        leader_checkpoint = leader[1].get("current_checkpoint", "")

    # Find finisher count
    competitive_finished = {
        n: d for n, d in mushers.items()
        if not is_expedition(n, d) and d.get("status") == "finished"
    }

    if competitive_finished and leader_name:
        title = f"🐕 Iditarod Update — {len(competitive_finished)} finished, {leader_name} leads on trail"
    elif competitive_finished:
        winner = min(competitive_finished.items(), key=lambda x: x[1].get("current_pos", 999))
        title = f"🐕 Iditarod Update — {len(competitive_finished)} finished, Winner: {winner[0]}"
    elif leader_name:
        title = f"🐕 Iditarod Update — {leader_name} leads at {leader_checkpoint}"
    else:
        title = "🐕 Iditarod Update"

    summary_text = summary
    if issue_url:
        summary_text += f"\n\n[📋 Full report on GitHub]({issue_url})"

    embed_summary = {
        "title": title,
        "description": summary_text,
        "color": 0x1a6bbd,
    }

    embeds = [embed_summary]

    # Finished
    finished_text = _build_finished_text(state)
    if finished_text:
        embeds.append({
            "title": "🏁 Finished",
            "description": finished_text,
            "color": 0x1a6bbd,
        })

    # Racing standings
    standings_text = _build_standings_text(state)
    if standings_text and standings_text != "_No mushers currently racing._":
        embeds.append({
            "title": "🏃 Racing",
            "description": standings_text,
            "color": 0x1a6bbd,
        })

    # Out of Race
    out_text = _build_out_of_race_text(state)
    if out_text:
        embeds.append({
            "title": "❌ Out of Race",
            "description": out_text,
            "color": 0x1a6bbd,
        })

    # Resting
    embeds.append({
        "title": "⛺ Resting at Checkpoint",
        "description": _build_resting_text(state),
        "color": 0x1a6bbd,
    })

    # Dog report
    embeds.append({
        "title": "🐕 Dog Report",
        "description": _build_dog_report_text(state),
        "color": 0x1a6bbd,
    })

    # Expedition class
    expedition_text = _build_expedition_text(state)
    if expedition_text:
        embeds.append({
            "title": "🧭 Expedition Class",
            "description": expedition_text,
            "color": 0x1a6bbd,
        })

    # Put footer on the last embed
    embeds[-1]["footer"] = {"text": f"Log #{state['last_log']} · iditarod.com"}

    # Discord allows max 10 embeds per message
    payload = {"embeds": embeds[:10]}
    resp = requests.post(webhook_url, json=payload, timeout=15)
    resp.raise_for_status()
    print("Discord notification sent.")
