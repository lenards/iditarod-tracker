"""Delivers race reports via GitHub Issues and Discord webhook."""

import os
import requests
from datetime import datetime, timezone


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
    leader_name = ""
    leader_checkpoint = ""

    mushers = state.get("mushers", {})
    if mushers:
        leader = min(mushers.items(), key=lambda x: x[1].get("current_pos", 999))
        leader_name = leader[0]
        leader_checkpoint = leader[1].get("current_checkpoint", "")

    if leader_name:
        return f"Race Report — {date_str} | Leader: {leader_name} at {leader_checkpoint}"
    return f"Race Report — {date_str}"


def build_full_body(summary: str, report_md: str) -> str:
    return f"## Race Summary\n\n{summary}\n\n---\n\n{report_md}"


def post_discord(summary: str, issue_url: str, state: dict) -> None:
    """
    Posts a summary embed to Discord via webhook.
    Keeps it brief — full standings are in the GitHub issue.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord.")
        return

    mushers = state.get("mushers", {})
    leader_name = ""
    leader_checkpoint = ""
    if mushers:
        leader = min(mushers.items(), key=lambda x: x[1].get("current_pos", 999))
        leader_name = leader[0]
        leader_checkpoint = leader[1].get("current_checkpoint", "")

    # Discord embed description has a 4096 char limit; summary is ~400 chars
    description = summary
    if issue_url:
        description += f"\n\n[📋 Full standings & dog report]({issue_url})"

    embed = {
        "title": f"🐕 Iditarod Update — {leader_name} leads at {leader_checkpoint}" if leader_name else "🐕 Iditarod Update",
        "description": description,
        "color": 0x1a6bbd,  # Iditarod blue-ish
        "footer": {"text": f"Log #{state['last_log']} · iditarod.com"},
    }

    payload = {"embeds": [embed]}
    resp = requests.post(webhook_url, json=payload, timeout=15)
    resp.raise_for_status()
    print("Discord notification sent.")
