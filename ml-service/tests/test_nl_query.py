from datetime import datetime

import pytest

from app.models.nl_query import parse_intent, format_answer, QueryIntent, QueryParseError


def fake_llm(response_text: str):
    """Returns an llm_call-shaped function that always responds with the
    given text, regardless of prompt/question - lets tests control
    exactly what the 'model' says without any real network call."""
    return lambda system_prompt, user_message: response_text


def test_parses_valid_response_into_intent():
    llm = fake_llm('{"employee_identifier": "EMP047", "start_time": "2026-07-08T09:45:00Z", "end_time": "2026-07-08T10:00:00Z"}')
    intent = parse_intent("Where was EMP047 at 10am?", llm)

    assert intent.employee_identifier == "EMP047"
    assert intent.start_time.hour == 9
    assert intent.end_time.hour == 10
    assert intent.raw_question == "Where was EMP047 at 10am?"


def test_model_reports_insufficient_information():
    llm = fake_llm('{"error": "insufficient_information"}')
    with pytest.raises(QueryParseError, match="Couldn't identify"):
        parse_intent("Tell me about employees", llm)


def test_malformed_json_raises_clear_error():
    llm = fake_llm("Sure! Here's the location: somewhere around 10am")
    with pytest.raises(QueryParseError, match="Could not parse"):
        parse_intent("Where was EMP047 at 10am?", llm)


def test_missing_required_field_rejected():
    llm = fake_llm('{"employee_identifier": "EMP047", "start_time": "2026-07-08T09:45:00Z"}')
    with pytest.raises(QueryParseError, match="missing required fields"):
        parse_intent("Where was EMP047 at 10am?", llm)


def test_unparseable_timestamp_rejected():
    llm = fake_llm('{"employee_identifier": "EMP047", "start_time": "sometime", "end_time": "2026-07-08T10:00:00Z"}')
    with pytest.raises(QueryParseError, match="unparseable timestamps"):
        parse_intent("Where was EMP047 at 10am?", llm)


def test_end_time_before_start_time_rejected():
    llm = fake_llm('{"employee_identifier": "EMP047", "start_time": "2026-07-08T10:00:00Z", "end_time": "2026-07-08T09:00:00Z"}')
    with pytest.raises(QueryParseError, match="not after"):
        parse_intent("Where was EMP047 at 10am?", llm)


def test_empty_employee_identifier_rejected():
    llm = fake_llm('{"employee_identifier": "  ", "start_time": "2026-07-08T09:45:00Z", "end_time": "2026-07-08T10:00:00Z"}')
    with pytest.raises(QueryParseError, match="usable employee identifier"):
        parse_intent("Where was that person at 10am?", llm)


def test_non_object_json_rejected():
    llm = fake_llm('["EMP047", "2026-07-08T09:45:00Z"]')
    with pytest.raises(QueryParseError, match="not a JSON object"):
        parse_intent("Where was EMP047 at 10am?", llm)


def _intent():
    return QueryIntent(
        employee_identifier="EMP047",
        start_time=datetime(2026, 7, 8, 9, 45),
        end_time=datetime(2026, 7, 8, 10, 0),
        raw_question="Where was EMP047 at 10am?",
    )


def test_format_answer_no_positions():
    answer = format_answer(_intent(), [])
    assert "No recorded positions" in answer
    assert "EMP047" in answer


def test_format_answer_single_zone():
    positions = [
        {"zone_name": "Concourse B", "recorded_at": "2026-07-08T09:47:00Z"},
        {"zone_name": "Concourse B", "recorded_at": "2026-07-08T09:52:00Z"},
    ]
    answer = format_answer(_intent(), positions)
    assert answer == "EMP047 was in Concourse B during that time."


def test_format_answer_multiple_zones_deduplicates_consecutive():
    positions = [
        {"zone_name": "Concourse B", "recorded_at": "2026-07-08T09:47:00Z"},
        {"zone_name": "Concourse B", "recorded_at": "2026-07-08T09:48:00Z"},
        {"zone_name": "Gate 12", "recorded_at": "2026-07-08T09:55:00Z"},
    ]
    answer = format_answer(_intent(), positions)
    assert answer == "EMP047 moved through: Concourse B, then Gate 12 during that time."


def test_format_answer_falls_back_to_zone_id_if_no_name():
    positions = [{"zone_id": "zone-uuid-123", "recorded_at": "2026-07-08T09:47:00Z"}]
    answer = format_answer(_intent(), positions)
    assert "zone-uuid-123" in answer
