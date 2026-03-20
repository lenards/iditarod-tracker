#!/usr/bin/env python3
"""
Compute ranked segment times between checkpoints for all mushers.

Fetches all race logs from iditarod.com, builds complete checkpoint
timing data, and outputs a ranked markdown report of travel times
per segment.
"""

import os
import sys
import time as time_mod
from datetime import datetime, timedelta

import requests

from src import scraper, parser

# Ordered checkpoints (excluding Anchorage and Campbell Airstrip)
CHECKPOINTS = [
    "Willow", "Yentna", "Skwentna", "Finger Lake", "Rainy Pass",
    "Rohn", "Nikolai", "McGrath", "Takotna", "Ophir",
    "Cripple", "Ruby", "Galena", "Nulato", "Kaltag",
    "Unalakleet", "Shaktoolik", "Koyuk", "Elim", "White Mountain",
    "Safety", "Nome",
]

# Cumulative distance from Anchorage (miles)
CHECKPOINT_MILES = {
    "Willow": 11, "Yentna": 53, "Skwentna": 83, "Finger Lake": 123,
    "Rainy Pass": 153, "Rohn": 188, "Nikolai": 263, "McGrath": 311,
    "Takotna": 329, "Ophir": 352, "Cripple": 425, "Ruby": 495,
    "Galena": 545, "Nulato": 582, "Kaltag": 629, "Unalakleet": 714,
    "Shaktoolik": 754, "Koyuk": 804, "Elim": 852, "White Mountain": 898,
    "Safety": 953, "Nome": 975,
}

# Fallback set for Expedition Class — prefer status field from state when available
EXPEDITION_CLASS = {"Thomas Waerner", "Kjell Rokke", "Steve Curtis"}

YEAR = 2026

REPO = "lenards/iditarod-tracker"
LABEL = "segment-times"


def parse_time(s: str) -> datetime | None:
    """Parse time string like '3/8 19:38:00' into a datetime."""
    if not s or s.strip() in ("", "-", "\u2014", "\u2013"):
        return None
    try:
        return datetime.strptime(f"{YEAR}/{s.strip()}", "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def fetch_all_logs() -> list[tuple[int, str]]:
    """Fetch all race logs from iditarod.com."""
    print("Fetching log list...")
    all_numbers = scraper.fetch_log_list()
    print(f"Found {len(all_numbers)} logs to process")

    results = []
    for i, number in enumerate(all_numbers):
        try:
            html = scraper.fetch_log(number)
            results.append((number, html))
            if (i + 1) % 50 == 0:
                print(f"  Fetched {i + 1}/{len(all_numbers)} logs...")
            time_mod.sleep(0.3)
        except Exception as e:
            print(f"  Warning: failed to fetch log {number}: {e}")

    print(f"  Fetched {len(results)}/{len(all_numbers)} logs")
    return results


def build_checkpoint_data(logs: list[tuple[int, str]]) -> dict:
    """Process all logs and build checkpoint timing data per musher.

    Returns:
        {musher_name: {"bib": str, "checkpoints": {cp: {"in_time": str, "out_time": str}}}}
    """
    musher_data: dict[str, dict] = {}

    for log_number, html in logs:
        log_data = parser.parse_log(html)
        for m in log_data["mushers"]:
            name = m["name"]
            if not name:
                continue

            if name not in musher_data:
                musher_data[name] = {"bib": m["bib"], "checkpoints": {}}

            cp = m["checkpoint"]
            cps = musher_data[name]["checkpoints"]

            if cp not in cps:
                cps[cp] = {"in_time": "", "out_time": ""}

            # Always update in_time if present
            in_t = (m["in_time"] or "").strip()
            if in_t and in_t not in ("-", "\u2014", "\u2013"):
                cps[cp]["in_time"] = in_t

            # Update out_time if present
            out_t = (m["out_time"] or "").strip()
            if out_t and out_t not in ("-", "\u2014", "\u2013"):
                cps[cp]["out_time"] = out_t

    return musher_data


def compute_segment_times(musher_data: dict) -> list[dict]:
    """Compute travel times between consecutive checkpoints.

    For each segment A -> B, travel time = in_time(B) - out_time(A).
    """
    segments = []

    for i in range(len(CHECKPOINTS) - 1):
        cp_from = CHECKPOINTS[i]
        cp_to = CHECKPOINTS[i + 1]
        dist = CHECKPOINT_MILES[cp_to] - CHECKPOINT_MILES[cp_from]

        segment_results = []
        for name, data in musher_data.items():
            if name in EXPEDITION_CLASS:
                continue

            cps = data["checkpoints"]
            if cp_from not in cps or cp_to not in cps:
                continue

            out_time = parse_time(cps[cp_from].get("out_time", ""))
            in_time = parse_time(cps[cp_to].get("in_time", ""))

            if out_time is None or in_time is None:
                continue

            travel = in_time - out_time
            if travel.total_seconds() <= 0:
                continue

            hours = travel.total_seconds() / 3600
            speed = dist / hours if hours > 0 else 0

            segment_results.append({
                "name": name,
                "bib": data["bib"],
                "travel_time": travel,
                "speed": speed,
            })

        segment_results.sort(key=lambda x: x["travel_time"])
        segments.append({
            "from": cp_from,
            "to": cp_to,
            "distance": dist,
            "results": segment_results,
        })

    return segments


def format_duration(td: timedelta) -> str:
    """Format a timedelta as 'Xh Ym'."""
    total_minutes = int(td.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours}h {minutes:02d}m"


def generate_markdown(segments: list[dict]) -> str:
    """Generate markdown report of ranked segment times."""
    lines = [
        "# Iditarod 2026 — Segment Times Between Checkpoints",
        "",
        f"_Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}_",
        "",
        "Ranked travel times between consecutive checkpoints for competitive mushers.",
        "Expedition Class mushers are excluded.",
        "",
        "Travel time is measured from **out** time at the departure checkpoint "
        "to **in** time at the arrival checkpoint.",
        "",
    ]

    for seg in segments:
        if not seg["results"]:
            continue

        lines.append(f"## {seg['from']} \u2192 {seg['to']} ({seg['distance']} mi)")
        lines.append("")
        lines.append("| Rank | Musher | Bib | Travel Time | Speed (mph) |")
        lines.append("|------|--------|-----|-------------|-------------|")

        for rank, r in enumerate(seg["results"], 1):
            lines.append(
                f"| {rank} | {r['name']} | {r['bib']} | "
                f"{format_duration(r['travel_time'])} | {r['speed']:.2f} |"
            )

        lines.append("")

    return "\n".join(lines)


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
    """Create the 'segment-times' label if it doesn't exist."""
    url = f"https://api.github.com/repos/{REPO}/labels"
    headers = _gh_headers()

    resp = requests.get(url, headers=headers, timeout=15)
    existing = {lbl["name"] for lbl in resp.json()} if resp.ok else set()

    if LABEL not in existing:
        requests.post(
            url,
            headers=headers,
            json={
                "name": LABEL,
                "color": "1d76db",
                "description": "Segment times between checkpoints",
            },
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


def main():
    print("=== Iditarod 2026 Segment Times Calculator ===")
    print()

    logs = fetch_all_logs()
    if not logs:
        print("No logs found!")
        sys.exit(1)

    print(f"\nProcessing {len(logs)} logs...")
    musher_data = build_checkpoint_data(logs)
    print(f"Found {len(musher_data)} mushers")

    print("Computing segment times...")
    segments = compute_segment_times(musher_data)

    md = generate_markdown(segments)

    # Print summary of fastest per segment
    print("\nFastest per segment:")
    for seg in segments:
        if seg["results"]:
            fastest = seg["results"][0]
            print(
                f"  {seg['from']} \u2192 {seg['to']}: "
                f"{fastest['name']} ({format_duration(fastest['travel_time'])}, "
                f"{fastest['speed']:.2f} mph)"
            )
        else:
            print(f"  {seg['from']} \u2192 {seg['to']}: no data")

    # Post as GitHub issue
    now = datetime.now().strftime("%B %-d, %Y")
    title = f"Segment Times Report \u2014 {now}"
    print(f"\nPosting GitHub issue: {title}")
    try:
        issue_url = post_issue(title, md)
        print(f"Issue created: {issue_url}")
    except Exception as e:
        print(f"Error posting issue: {e}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
