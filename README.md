# iditarod-tracker

Automated race tracker for the Iditarod Trail Sled Dog Race.

Runs 3× per day (8am, 2pm, 7pm Alaska time) and posts a GitHub issue with:

- **Standings** — current positions for all mushers
- **At checkpoint** — who is currently resting (Out columns empty)
- **Dog report** — cumulative dropped dogs per musher per checkpoint
- **Narrative summary** — 2-3 paragraph prose summary via Claude Haiku

## How it works

1. Fetches the log index at `iditarod.com/race/2026/logs/`
2. Downloads any logs newer than the last run (tracked in `state.json`)
3. Parses the standings table — detects checkpoint passages and dog counts
4. Generates a report and posts it as a GitHub issue with the `race-report` label

## Setup

Add these secrets to the repo (`Settings → Secrets → Actions`):

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | For Claude Haiku narrative summaries |
| `DISCORD_WEBHOOK_URL` | Discord channel webhook URL for notifications |

`GITHUB_TOKEN` is provided automatically by GitHub Actions.

## Run manually

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export GITHUB_TOKEN=...
python main.py
```
