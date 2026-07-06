"""
Face-match decision logic.

Deliberately pure and dependency-free (no Postgres, no embedding model) so
it's fully testable before the two blocked pieces land:
  - employees.face_embedding / pgvector (enrolled embeddings storage)
  - the actual embedding-generation model (InsightFace, pending team
    confirmation - see app/services/embedding_backend.py)

This module answers exactly one question: given a query embedding and a
list of enrolled (employee_id, embedding) pairs, which employee - if any -
does the photo match, and how confident is that match?

It does NOT decide alerting. Whether a 'match' result disagrees with the
tag's claimed identity (the badge-sharing/tailgating signal Shashank
described) is a separate check the caller does with the result - see the
open question in main.py about where that alert actually gets created.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Cosine similarity threshold above which we consider it a confident match.
# Placeholder value - needs real calibration once we have (a) the actual
# embedding model chosen and (b) real enrolled photos to test false-accept /
# false-reject rates against. Do not treat 0.55 as tuned.
DEFAULT_MATCH_THRESHOLD = 0.55


@dataclass
class EnrolledEmbedding:
    employee_id: str
    embedding: np.ndarray


@dataclass
class MatchResult:
    match_employee_id: Optional[str]
    match_confidence: Optional[float]
    match_status: str  # 'match' | 'mismatch' | 'no_face' (never 'pending' - that's the initial DB default only)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    return float(np.dot(a, b) / (a_norm * b_norm))


def find_best_match(
    query_embedding: Optional[np.ndarray],
    enrolled: list[EnrolledEmbedding],
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> MatchResult:
    """
    query_embedding=None means no face was detected in the captured photo
    at all (upstream embedding step failed) - distinct from "a face was
    found but didn't match anyone confidently".
    """
    if query_embedding is None:
        return MatchResult(match_employee_id=None, match_confidence=None, match_status="no_face")

    if not enrolled:
        return MatchResult(match_employee_id=None, match_confidence=None, match_status="mismatch")

    scored = [(e.employee_id, cosine_similarity(query_embedding, e.embedding)) for e in enrolled]
    best_employee_id, best_score = max(scored, key=lambda pair: pair[1])

    if best_score >= threshold:
        return MatchResult(match_employee_id=best_employee_id, match_confidence=best_score, match_status="match")

    # Below threshold: we deliberately do NOT report a low-confidence
    # employee_id here - "closest guess anyway" invites treating a
    # non-match as an identity, which is the opposite of what this
    # feature is for. match_confidence still reports the best score found,
    # for audit/debugging/threshold-tuning purposes.
    return MatchResult(match_employee_id=None, match_confidence=best_score, match_status="mismatch")


def is_identity_mismatch(result: MatchResult, claimed_employee_id: Optional[str]) -> bool:
    """
    The actual tailgating/badge-sharing signal: a CONFIDENT face match that
    disagrees with who the tag claims is present. This is distinct from
    match_status='mismatch' (which means no confident match at all).

    Returns False whenever there's no confident match to compare, or no
    claimed identity to compare against - absence of information is not
    evidence of a mismatch.
    """
    if result.match_status != "match":
        return False
    if claimed_employee_id is None:
        return False
    return result.match_employee_id != claimed_employee_id
