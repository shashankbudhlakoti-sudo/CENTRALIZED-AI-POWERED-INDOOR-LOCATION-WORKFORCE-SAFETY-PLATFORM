"""
Real LLM-backed implementation of the llm_call interface used by
nl_query.parse_intent. Kept in its own file, separate from the parsing
logic, so tests can inject a fake implementation and never make a real
network call or need an API key.
"""

import os

import httpx

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def anthropic_llm_call(system_prompt: str, user_message: str) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set - the NL query assistant needs this to "
            "call the LLM. Set it in .env, do not hardcode it anywhere."
        )

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 300,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    # Anthropic's response content is a list of blocks; we only expect text.
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")
