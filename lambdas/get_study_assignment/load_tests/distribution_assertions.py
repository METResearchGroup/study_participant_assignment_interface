"""Distribution checks for load-test outcomes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, floor, sqrt

from lambdas.get_study_assignment.load_tests.traffic import PARTIES

CONDITIONS = ("control", "training_assisted")


@dataclass(frozen=True)
class DistributionCheckResult:
    ok: bool
    errors: list[str]
    details: dict[str, object]


def _binom_cdf_leq(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    q = 1.0 - p
    pmf = q**n
    cdf = pmf
    ratio_base = p / q
    for i in range(0, k):
        pmf = pmf * (n - i) / (i + 1) * ratio_base
        cdf += pmf
    return min(1.0, max(0.0, cdf))


def _solve_monotonic_desc(
    *,
    target: float,
    n: int,
    k: int,
    evaluator: Callable[[int, int, float], float],
    iterations: int = 80,
) -> float:
    lo = 0.0
    hi = 1.0
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        value = evaluator(k, n, mid)
        if value > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson_interval(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Return exact two-sided CI for Binomial(k | n)."""
    if n <= 0:
        return (0.0, 1.0)
    if k < 0 or k > n:
        raise ValueError(f"k must be in [0, n], got k={k}, n={n}")
    if k == 0:
        lower = 0.0
    else:
        # Solve CDF(k-1; n, p) = 1 - alpha/2.
        lower = _solve_monotonic_desc(
            target=1.0 - alpha / 2.0,
            n=n,
            k=k - 1,
            evaluator=_binom_cdf_leq,
        )
    if k == n:
        upper = 1.0
    else:
        # Solve CDF(k; n, p) = alpha/2.
        upper = _solve_monotonic_desc(
            target=alpha / 2.0,
            n=n,
            k=k,
            evaluator=_binom_cdf_leq,
        )
    return (lower, upper)


def exact_binomial_acceptance_interval_counts(
    *, n: int, p: float = 0.5, alpha: float = 0.05
) -> tuple[int, int]:
    """Return a normal-approx central interval [lo, hi] for X~Binomial(n, p)."""
    if n <= 0:
        return (0, 0)
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0, 1)")
    z = 1.96 if alpha == 0.05 else 1.96
    mean = n * p
    std = sqrt(n * p * (1.0 - p))
    lo = max(0, floor(mean - z * std))
    hi = min(n, ceil(mean + z * std))
    return (int(lo), int(hi))


def _alternate_expected_cell_count(n: int) -> int:
    if n % 4 != 0:
        raise ValueError(
            "alternate scenario requires n divisible by 4 "
            "(exact request_party x response_condition checks)"
        )
    return n // 4


def assert_distribution(
    *,
    scenario: str,
    request_condition_counts: Counter[tuple[str, str]],
) -> DistributionCheckResult:
    """Validate request_party x response_condition distribution invariants."""
    if scenario not in ("alternate", "random"):
        raise ValueError(f"unsupported scenario={scenario!r}")

    total = sum(request_condition_counts.values())
    errors: list[str] = []
    details: dict[str, object] = {"scenario": scenario, "total": total}
    cell_counts = {
        f"{party}:{condition}": int(request_condition_counts[(party, condition)])
        for party in PARTIES
        for condition in CONDITIONS
    }
    details["request_condition_counts"] = cell_counts

    if scenario == "alternate":
        expected = _alternate_expected_cell_count(total)
        details["expected_per_cell"] = expected
        for party in PARTIES:
            for condition in CONDITIONS:
                observed = int(request_condition_counts[(party, condition)])
                if observed != expected:
                    errors.append(
                        f"alternate exact check failed for {party}:{condition}: "
                        f"expected {expected}, got {observed}"
                    )
        return DistributionCheckResult(ok=not errors, errors=errors, details=details)

    # random scenario checks: party split must satisfy exact 95% CI + +/-100 slack.
    party_counts = {
        party: sum(request_condition_counts[(party, c)] for c in CONDITIONS) for party in PARTIES
    }
    details["party_counts"] = party_counts
    details["interval_method"] = "normal-approx-central-95"
    slack = 100
    details["slack"] = slack

    n = total
    expected = n / 2.0
    lower_count, upper_count = exact_binomial_acceptance_interval_counts(n=n, p=0.5, alpha=0.05)
    details["binomial_count_bounds"] = [lower_count, upper_count]
    for party in PARTIES:
        k = int(party_counts[party])
        if k < lower_count or k > upper_count:
            errors.append(
                "random CI check failed for "
                f"{party}: observed {k} not in [{lower_count}, {upper_count}]"
            )
        if abs(k - expected) > slack:
            errors.append(
                "random +/-"
                f"{slack} check failed for {party}: observed {k}, expected around {expected:.1f}"
            )
    return DistributionCheckResult(ok=not errors, errors=errors, details=details)
