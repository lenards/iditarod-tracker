"""Generates a narrative race summary using Claude Haiku."""

import anthropic


def generate_summary(facts: str) -> str:
    """
    Takes a structured facts string and returns a 2-3 paragraph
    narrative race summary written for a general audience.
    """
    client = anthropic.Anthropic()

    prompt = f"""You are writing a race update for the Iditarod Trail Sled Dog Race 2026.
Write a friendly, engaging 2-3 paragraph summary for a general audience (think: family following along from home).
Mention the race leader and top positions, note who is resting at checkpoints, and call out any notable dog drops.
Keep it warm and informative — not too technical. Don't use bullet points; write in prose.

IMPORTANT: If Expedition Class mushers appear in the facts, mention them briefly and separately
from the competitive field. Make it clear they are not competing for placement — they run alongside
the race with support teams and different rules. Do not mix them into the competitive standings
narrative. A sentence or two at the end is sufficient.

Here are the current race facts:

{facts}

Write the summary now:"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()
