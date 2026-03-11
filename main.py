#!/usr/bin/env python3
"""
Iditarod Race Tracker — main entrypoint.

1. Load state (last processed log number + musher history)
2. Fetch any new logs from iditarod.com
3. Parse + update state
4. If new logs found: generate report + narrative, post GitHub issue
5. Save updated state
"""

import sys
from src import scraper, parser, state as state_mod, report as report_mod
from src.summarize import generate_summary
from src.deliver import build_issue_title, build_full_body, post_issue, post_discord


def main():
    print("Loading state...")
    state = state_mod.load()
    last_log = state["last_log"]
    print(f"Last processed log: {last_log}")

    print("Fetching new logs...")
    try:
        new_logs = scraper.fetch_new_logs(last_log)
    except Exception as e:
        print(f"Error fetching logs: {e}", file=sys.stderr)
        sys.exit(1)

    if not new_logs:
        print("No new logs found. Nothing to do.")
        return

    print(f"Found {len(new_logs)} new log(s): {[n for n, _ in new_logs]}")

    # Process each new log in order
    for log_number, html in new_logs:
        print(f"Parsing log {log_number}...")
        log_data = parser.parse_log(html)
        musher_count = len(log_data["mushers"])
        print(f"  → {musher_count} mushers found")

        if musher_count == 0:
            print(f"  Warning: no mushers parsed from log {log_number}, skipping state update")
            continue

        state_mod.update_from_log(state, log_data)
        state["last_log"] = log_number

    # Save state immediately after processing
    state_mod.save(state)
    print(f"State saved. Last log: {state['last_log']}")

    # Build report
    print("Building report...")
    report = report_mod.build_report(state)
    report_md = report_mod.format_report_markdown(report, state)
    facts = report_mod.format_summary_prompt(report, state)

    # Generate Claude narrative
    print("Generating narrative summary...")
    try:
        summary = generate_summary(facts)
    except Exception as e:
        print(f"Warning: Claude summary failed ({e}), using fallback")
        summary = "_Narrative summary unavailable._"

    # Post GitHub issue
    print("Posting GitHub issue...")
    issue_url = None
    try:
        title = build_issue_title(state)
        body = build_full_body(summary, report_md)
        issue_url = post_issue(title, body)
        print(f"Issue created: {issue_url}")
    except Exception as e:
        print(f"Error posting issue: {e}", file=sys.stderr)

    # Post Discord notification
    print("Posting Discord notification...")
    try:
        post_discord(summary, issue_url or "", state)
    except Exception as e:
        print(f"Warning: Discord post failed: {e}", file=sys.stderr)

    if issue_url is None:
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
