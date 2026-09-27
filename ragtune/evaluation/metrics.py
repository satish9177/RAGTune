"""Information Retrieval evaluation metrics and statistical testing."""

from __future__ import annotations

import math
from typing import Dict, List, Set, Tuple
import numpy as np


def recall_at_k(retrieved_ids: List[str], positive_ids: Set[str], k: int) -> float:
    """Calculate Recall@K: fraction of relevant documents retrieved in top K."""
    if not positive_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = sum(1 for doc_id in top_k if doc_id in positive_ids)
    return hits / len(positive_ids)


def mrr_at_k(retrieved_ids: List[str], positive_ids: Set[str], k: int = 10) -> float:
    """Calculate Mean Reciprocal Rank@K for a single query."""
    if not positive_ids:
        return 0.0
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        if doc_id in positive_ids:
            return 1.0 / rank
    return 0.0


def dcg_at_k(retrieved_ids: List[str], graded_relevance: Dict[str, int], k: int = 10) -> float:
    """Calculate Discounted Cumulative Gain at K using exponential gain formulation."""
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        rel = graded_relevance.get(doc_id, 0)
        gain = (2.0 ** rel) - 1.0
        discount = math.log2(rank + 1.0)
        dcg += gain / discount
    return dcg


def ndcg_at_k(retrieved_ids: List[str], graded_relevance: Dict[str, int], k: int = 10) -> float:
    """Calculate Normalized Discounted Cumulative Gain at K."""
    # Ideal DCG: sort available relevance grades descending
    sorted_grades = sorted(graded_relevance.values(), reverse=True)[:k]
    if not sorted_grades or sorted_grades[0] == 0:
        return 0.0

    idcg = 0.0
    for rank, rel in enumerate(sorted_grades, start=1):
        gain = (2.0 ** rel) - 1.0
        discount = math.log2(rank + 1.0)
        idcg += gain / discount

    if idcg == 0.0:
        return 0.0

    actual_dcg = dcg_at_k(retrieved_ids, graded_relevance, k=k)
    return actual_dcg / idcg


def paired_bootstrap_delta(
    candidate_scores: List[float],
    baseline_scores: List[float],
    num_resamples: int = 10000,
    alpha: float = 0.05,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Calculate paired bootstrap confidence interval for delta (candidate - baseline).
    
    Returns:
        (mean_delta, ci_lower, ci_upper)
    """
    assert len(candidate_scores) == len(baseline_scores), "Scores lists must be paired and identical length"
    n = len(candidate_scores)
    if n == 0:
        return 0.0, 0.0, 0.0

    deltas = np.array(candidate_scores) - np.array(baseline_scores)
    observed_mean = float(np.mean(deltas))

    rng = np.random.default_rng(seed)
    bootstrap_means = np.empty(num_resamples, dtype=np.float64)

    for i in range(num_resamples):
        indices = rng.integers(0, n, size=n)
        bootstrap_means[i] = np.mean(deltas[indices])

    ci_lower = float(np.percentile(bootstrap_means, 100.0 * (alpha / 2.0)))
    ci_upper = float(np.percentile(bootstrap_means, 100.0 * (1.0 - alpha / 2.0)))

    return observed_mean, ci_lower, ci_upper


def mcnemar_table(candidate_hits: List[bool], baseline_hits: List[bool]) -> Dict[str, float]:
    """Calculate 2x2 contingency table and McNemar test statistic with continuity correction."""
    assert len(candidate_hits) == len(baseline_hits), "Hits lists must be paired and identical length"

    n00 = 0  # both miss
    n01 = 0  # baseline miss, candidate hit (positive transition)
    n10 = 0  # baseline hit, candidate miss (regression)
    n11 = 0  # both hit

    for c, b in zip(candidate_hits, baseline_hits):
        if not b and not c:
            n00 += 1
        elif not b and c:
            n01 += 1
        elif b and not c:
            n10 += 1
        else:
            n11 += 1

    discordant = n01 + n10
    if discordant == 0:
        chi2 = 0.0
    else:
        # McNemar test with Edwards continuity correction
        chi2 = ((abs(n01 - n10) - 1.0) ** 2) / float(discordant)

    return {
        "n00_both_miss": n00,
        "n01_candidate_better": n01,
        "n10_baseline_better": n10,
        "n11_both_hit": n11,
        "chi2_statistic": chi2,
    }
