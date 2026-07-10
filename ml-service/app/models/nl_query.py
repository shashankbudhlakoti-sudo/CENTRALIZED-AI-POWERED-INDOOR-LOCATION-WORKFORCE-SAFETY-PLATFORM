"""
NL query assistant (Section 4.2, row 7): natural-language interface over
the audit-logged query layer, e.g. "Where was EMP047 at 10am".

Design principle: the LLM's output is NEVER trusted directly. It's asked
to produce strict JSON matching a fixed schema, and that JSON is validated
before a single database query runs. If parsing fails or the schema
doesn't match, this returns a clear "I couldn't understand that" result -
it never silently guesses at which employee or time range was meant,
since a wrong guess here means showing someone the wrong person's
location history.

This module deliberately does NOT read Postgres directly. Employee
position history is personal data under RLS - it goes through the
backend's own GET /positions/history endpoint using the CALLER'S forwarded
JWT, so the backend's existing department-scoping applies exactly as it
would for any other access. The ML service does not get to bypass RLS
for personal data just because the request came in as a natural-language
query instead of a normal REST call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


class QueryParseError(Exception):
    """Raised when the question can't be confidently turned into a
    structured query - the caller should show this as a clarification
    request, never fall back to a guess."""


@dataclass
class QueryIntent:
    employee_identifier: str  # employee_code as written in the question, e.g. "EMP047"
    start_time: datetime
    end_time: datetime
    raw_question: str


REQUIRED_FIELDS = {"employee_identifier", "start_time", "end_time"}

SYSTEM_PROMPT = """You convert a question about an employee's location history into JSON.

Output ONLY a JSON object with exactly these fields, nothing else:
{
  "employee_identifier": "<employee code as mentioned, e.g. EMP047>",
  "start_time": "<ISO 8601 datetime, UTC>",
  "end_time": "<ISO 8601 datetime, UTC>"
}

Rules:
- If the question mentions a single point in time (e.g. "at 10am"), set
  start_time and end_time to a 15-minute window centered on that time.
- If you cannot identify a specific employee code or a specific time from
  the question, output {"error": "insufficient_information"} instead -
  never guess an employee identifier or time that wasn't actually stated.
- Assume today's date if no date is mentioned.
- Output nothing except the JSON object - no explanation, no markdown fences.
"""


def parse_intent(
    question: str,
    llm_call: Callable[[str, str], str],
    reference_date: Optional[datetime] = None,
) -> QueryIntent:
    """llm_call(system_prompt, user_message) -> raw text response.
    Injected so tests can use a fake, deterministic implementation instead
    of a real network call to an LLM provider.
    """
    reference_date = reference_date or datetime.now(timezone.utc)
    user_message = f"Today's date: {reference_date.date().isoformat()}\nQuestion: {question}"

    raw_response = llm_call(SYSTEM_PROMPT, user_message)

    try:
        data = json.loads(raw_response.strip())
    except json.JSONDecodeError as exc:
        raise QueryParseError(
            f"Could not parse a structured query from the model's response: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise QueryParseError("Model response was not a JSON object")

    if "error" in data:
        raise QueryParseError(
            "Couldn't identify a specific employee and time from that question - "
            "try including an employee ID and a specific time, e.g. "
            "\"Where was EMP047 at 10am on July 8?\""
        )

    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        raise QueryParseError(f"Model response missing required fields: {missing}")

    try:
        start_time = datetime.fromisoformat(data["start_time"].replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(data["end_time"].replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise QueryParseError(f"Model returned unparseable timestamps: {exc}") from exc

    if end_time <= start_time:
        raise QueryParseError("Model returned an end_time not after start_time")

    employee_identifier = data["employee_identifier"]
    if not isinstance(employee_identifier, str) or not employee_identifier.strip():
        raise QueryParseError("Model did not return a usable employee identifier")

    return QueryIntent(
        employee_identifier=employee_identifier.strip(),
        start_time=start_time,
        end_time=end_time,
        raw_question=question,
    )


def format_answer(intent: QueryIntent, positions: list[dict]) -> str:
    """Turns a list of position_event-shaped dicts (from the backend's
    GET /positions/history) into a plain-English answer. Never invents
    a location that isn't actually in the returned data."""
    if not positions:
        window = f"{intent.start_time.strftime('%H:%M')}-{intent.end_time.strftime('%H:%M')}"
        return (
            f"No recorded positions found for {intent.employee_identifier} "
            f"between {window} on {intent.start_time.date().isoformat()}."
        )

    # Positions are assumed sorted by recorded_at (backend's responsibility);
    # summarize by zone rather than dumping every raw point.
    zones_seen = []
    for p in positions:
        zone = p.get("zone_name") or p.get("zone_id") or "an unspecified zone"
        if not zones_seen or zones_seen[-1] != zone:
            zones_seen.append(zone)

    if len(zones_seen) == 1:
        return f"{intent.employee_identifier} was in {zones_seen[0]} during that time."

    zone_list = ", then ".join(zones_seen)
    return f"{intent.employee_identifier} moved through: {zone_list} during that time."
