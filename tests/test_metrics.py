"""Unit tests for retrieval evaluation metrics with hand-calculated ground truths."""

import math
import pytest
from ragtune.evaluation.metrics import (
    recall_at_k,
    mrr_at_k,
    dcg_at_k,
    ndcg_at_k,
    paired_bootstrap_delta,
    mcnemar_table,
)


def test_recall_at_k_hand_calculated():
    """Verify Recall@K against hand-calculated fractions."""
    positives = {"docA", "docB"}
    retrieved = ["docC", "docA", "docD", "docB", "docE"]

    assert recall_at_k(retrieved, positives, k=1) == 0.0
    assert recall_at_k(retrieved, positives, k=2) == 0.5
    assert recall_at_k(retrieved, positives, k=3) == 0.5
    assert recall_at_k(retrieved, positives, k=4) == 1.0
    assert recall_at_k(retrieved, positives, k=5) == 1.0
    # Empty positives should return 0.0 cleanly
    assert recall_at_k(retrieved, set(), k=5) == 0.0


def test_mrr_at_k_hand_calculated():
    """Verify MRR@K against hand-calculated reciprocal ranks."""
    positives = {"docA", "docB"}
    retrieved = ["docC", "docD", "docA", "docB"]

    # First positive is docA at rank 3 -> 1/3
    expected_mrr = 1.0 / 3.0
    assert pytest.approx(mrr_at_k(retrieved, positives, k=10), rel=1e-6) == expected_mrr

    # When first positive is outside k cut-off
    assert mrr_at_k(retrieved, positives, k=2) == 0.0


def test_ndcg_at_k_hand_calculated():
    """Verify NDCG@K against manual exponential gain calculation."""
    # Graded relevance: docA=3, docB=2, docC=1, unmentioned=0
    relevance = {"docA": 3, "docB": 2, "docC": 1}
    retrieved = ["docB", "docC", "docA", "docX"]

    # Hand calculation:
    # Rank 1: docB (rel=2) -> gain = 2^2 - 1 = 3 -> discount = log2(2) = 1.0 -> 3 / 1 = 3.0
    # Rank 2: docC (rel=1) -> gain = 2^1 - 1 = 1 -> discount = log2(3) -> 1 / log2(3) ≈ 0.63092975357
    # Rank 3: docA (rel=3) -> gain = 2^3 - 1 = 7 -> discount = log2(4) = 2.0 -> 7 / 2 = 3.5
    # Rank 4: docX (rel=0) -> gain = 0
    actual_dcg = 3.0 + (1.0 / math.log2(3.0)) + 3.5

    # Ideal ranking: [docA(3), docB(2), docC(1)]
    # Rank 1: 7 / log2(2) = 7.0
    # Rank 2: 3 / log2(3) ≈ 1.8927892607
    # Rank 3: 1 / log2(4) = 0.5
    idcg = 7.0 + (3.0 / math.log2(3.0)) + 0.5

    expected_ndcg = actual_dcg / idcg
    computed_ndcg = ndcg_at_k(retrieved, relevance, k=10)

    assert pytest.approx(computed_ndcg, rel=1e-6) == expected_ndcg
    assert pytest.approx(computed_ndcg, rel=1e-4) == 0.7592


def test_ndcg_at_k_perfect_ranking():
    """Verify that ideal ranking gives exactly NDCG = 1.0."""
    relevance = {"docA": 3, "docB": 2, "docC": 1}
    ideal_retrieved = ["docA", "docB", "docC"]
    assert pytest.approx(ndcg_at_k(ideal_retrieved, relevance, k=10), rel=1e-6) == 1.0


def test_paired_bootstrap_delta():
    """Verify paired bootstrap returns valid confidence interval around mean."""
    baseline = [0.2, 0.4, 0.5, 0.3, 0.6]
    candidate = [0.3, 0.5, 0.7, 0.4, 0.8]  # Candidate is consistently +0.1 to +0.2 better

    mean_delta, ci_lower, ci_upper = paired_bootstrap_delta(
        candidate, baseline, num_resamples=1000, alpha=0.05, seed=42
    )

    # Observed mean delta: (0.1 + 0.1 + 0.2 + 0.1 + 0.2) / 5 = 0.14
    assert pytest.approx(mean_delta, rel=1e-6) == 0.14
    assert ci_lower > 0.0  # Confirms candidate is significantly better
    assert ci_lower <= mean_delta <= ci_upper


def test_mcnemar_table():
    """Verify McNemar 2x2 contingency table calculation."""
    baseline_hits = [True, False, False, True, False]
    candidate_hits = [True, True, False, False, True]

    res = mcnemar_table(candidate_hits, baseline_hits)
    assert res["n00_both_miss"] == 1
    assert res["n01_candidate_better"] == 2
    assert res["n10_baseline_better"] == 1
    assert res["n11_both_hit"] == 1
    # Continuity corrected chi2: (|2 - 1| - 1)^2 / (2 + 1) = 0.0 / 3 = 0.0
    assert res["chi2_statistic"] == 0.0
