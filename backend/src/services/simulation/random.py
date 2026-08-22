"""Random delay generation for Petri net simulation.

Port of ua.stetsenkoinna.PetriObj.FunRand with Arena-style truncated
distributions: time delays must be non-negative, so samples that fall
below zero are re-drawn rather than raising. This matches standard DES
practice (Arena, AnyLogic, SimPy) and keeps the simulation alive on
realistic parameters such as N(60, 30) where ~2% of raw samples are
negative but the truncated distribution is well-defined.
"""

import math
import random as _random

# Cap on resampling attempts. With reasonable parameters (e.g. σ ≤ μ) the
# negative-tail probability is well under 50%, so 100 attempts gives a miss
# probability < 1e-30. Hitting this limit means the user supplied parameters
# where most of the mass is below zero — surface that as an error instead of
# spinning forever.
_MAX_TRUNCATION_ATTEMPTS = 100


def exp_delay(mean: float) -> float:
    a = 0.0
    while not a:
        a = _random.random()  # NOSONAR - simulation PRNG, not security-sensitive
    return -mean * math.log(a)


def norm_delay(mean: float, deviation: float) -> float:
    """Sample from a normal distribution truncated at zero.

    Equivalent to a truncated normal TN(mean, deviation, low=0). The mean
    of the truncated distribution is shifted slightly upward relative to
    the underlying normal — the magnitude of the shift is small for the
    typical regime σ ≪ μ (e.g. ~1% for N(60, 30)).
    """
    for _ in range(_MAX_TRUNCATION_ATTEMPTS):
        a = mean + deviation * _random.gauss(0.0, 1.0)
        if a >= 0:
            return a
    raise ValueError(
        f"Truncated normal failed after {_MAX_TRUNCATION_ATTEMPTS} resamples "
        f"(mean={mean}, deviation={deviation}). Most of the distribution lies "
        f"below zero — reduce deviation or use a different distribution."
    )


def unif_delay(low: float, high: float) -> float:
    """Sample uniform[low, high] truncated at zero.

    If both bounds are negative the request is meaningless and raises;
    otherwise samples below zero are redrawn.
    """
    if high < 0:
        raise ValueError(
            f"Uniform distribution upper bound must be >= 0, got high={high}"
        )
    for _ in range(_MAX_TRUNCATION_ATTEMPTS):
        a = 0.0
        while a == 0.0:
            a = _random.random()  # NOSONAR - simulation PRNG, not security-sensitive
        result = low + a * (high - low)
        if result >= 0:
            return result
    raise ValueError(
        f"Truncated uniform failed after {_MAX_TRUNCATION_ATTEMPTS} resamples "
        f"(low={low}, high={high}). Most of the range lies below zero — "
        f"raise the bounds."
    )


def generate_delay(
    distribution: str | None,
    parameter: float,
    deviation: float = 0.0,
) -> float:
    if distribution is None or distribution == "det":
        return parameter
    if distribution == "exp":
        return exp_delay(parameter)
    if distribution == "norm":
        return norm_delay(parameter, deviation)
    if distribution == "unif":
        return unif_delay(parameter - deviation, parameter + deviation)
    raise ValueError(f"Unknown distribution: {distribution}")
