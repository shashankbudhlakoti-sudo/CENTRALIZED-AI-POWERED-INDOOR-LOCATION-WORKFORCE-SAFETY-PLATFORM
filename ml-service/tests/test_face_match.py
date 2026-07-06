import numpy as np
import pytest

from app.models.face_match import (
    EnrolledEmbedding,
    MatchResult,
    cosine_similarity,
    find_best_match,
    is_identity_mismatch,
    DEFAULT_MATCH_THRESHOLD,
)


def _unit_vec(seed: int, dim: int = 512) -> np.ndarray:
    # 512 dims matches typical face-embedding size (e.g. InsightFace) - at
    # low dimensions, random vectors can coincidentally have high cosine
    # similarity by chance, which made the below-threshold test flaky.
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim)
    return v / np.linalg.norm(v)


def test_no_face_detected_short_circuits_to_no_face_status():
    result = find_best_match(query_embedding=None, enrolled=[EnrolledEmbedding("emp-1", _unit_vec(1))])
    assert result.match_status == "no_face"
    assert result.match_employee_id is None
    assert result.match_confidence is None


def test_confident_match_above_threshold():
    target = _unit_vec(42)
    enrolled = [
        EnrolledEmbedding("emp-1", target),
        EnrolledEmbedding("emp-2", _unit_vec(99)),
    ]
    result = find_best_match(query_embedding=target, enrolled=enrolled)
    assert result.match_status == "match"
    assert result.match_employee_id == "emp-1"
    assert result.match_confidence == pytest.approx(1.0, abs=1e-6)


def test_below_threshold_reports_mismatch_without_identity():
    # Two unrelated random unit vectors are very unlikely to exceed a 0.55
    # cosine-similarity threshold in 8 dimensions.
    query = _unit_vec(1)
    enrolled = [EnrolledEmbedding("emp-1", _unit_vec(2))]
    result = find_best_match(query_embedding=query, enrolled=enrolled, threshold=DEFAULT_MATCH_THRESHOLD)
    assert result.match_status == "mismatch"
    assert result.match_employee_id is None  # never report a low-confidence guess as an identity
    assert result.match_confidence is not None  # but still surface the score for audit/tuning


def test_no_enrolled_employees_is_mismatch_not_no_face():
    result = find_best_match(query_embedding=_unit_vec(1), enrolled=[])
    assert result.match_status == "mismatch"
    assert result.match_employee_id is None


def test_cosine_similarity_identical_vectors_is_one():
    v = _unit_vec(7)
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_handles_zero_vector():
    zero = np.zeros(512)
    v = _unit_vec(3)
    assert cosine_similarity(zero, v) == 0.0


def test_identity_mismatch_true_when_confident_match_disagrees_with_tag():
    result = MatchResult(match_employee_id="emp-1", match_confidence=0.9, match_status="match")
    assert is_identity_mismatch(result, claimed_employee_id="emp-2") is True


def test_identity_mismatch_false_when_match_agrees_with_tag():
    result = MatchResult(match_employee_id="emp-1", match_confidence=0.9, match_status="match")
    assert is_identity_mismatch(result, claimed_employee_id="emp-1") is False


def test_identity_mismatch_false_when_no_confident_match():
    # A 'mismatch' or 'no_face' status means we don't know who this is -
    # that's not evidence of tag disagreement, just missing information.
    result = MatchResult(match_employee_id=None, match_confidence=0.3, match_status="mismatch")
    assert is_identity_mismatch(result, claimed_employee_id="emp-2") is False


def test_identity_mismatch_false_when_tag_claim_unknown():
    result = MatchResult(match_employee_id="emp-1", match_confidence=0.9, match_status="match")
    assert is_identity_mismatch(result, claimed_employee_id=None) is False
