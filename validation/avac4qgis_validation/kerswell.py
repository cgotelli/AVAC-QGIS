"""Kerswell's analytical Coulomb dam-break equations for validation only.

These routines are a direct transcription of the analytical construction used
in the Chapter 8 tutorial.  They supply reference curves for post-processing;
they are never imported by, or supplied to, the AVAC solver.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.integrate import quad
from scipy.special import hyp2f1


@lru_cache(maxsize=None)
def riemann(s: float, r: float, a: float, b: float) -> float:
    """Riemann function in the Kerswell construction."""
    denominator = (a + r) ** 1.5 * (s + b) ** 1.5
    if denominator == 0.0:
        return 0.0
    z = ((r - b) * (s - a)) / ((r + a) * (s + b))
    if not np.isfinite(z) or abs(z) >= 1.0:
        return 0.0
    return (r + s) ** 3 * hyp2f1(1.5, 1.5, 1, z) / denominator


def _t_r(r: float) -> float:
    return (
        3.700279768999653
        - 2.0222717471071308 * r
        + 0.6121280543569234 * r**2
        - 0.5305730395014081 * r**3
        + 0.32693579002742174 * r**4
        - 0.1008432305585469 * r**5
        + 0.014345919899608602 * r**6
    )


def _mean_r_rs(r: float, a: float, b: float) -> float:
    """Regularized mean derivative along the characteristic singularity."""
    z = (((b - r) * (-2.0 + (a + r))) / (a + r)) / ((2.0 + b) - r)
    value_1 = hyp2f1(1.5, 1.5, 1, z)
    value_2 = hyp2f1(1.5, 2.5, 1, z)
    auxiliary_1 = (
        -2.0 + a - 3.0 * b + 2.0 * a * b
        + 2.0 * ((2.0 + b) - a) * r - 2.0 * r**2
    ) * value_1
    auxiliary_3 = (
        ((2.0 + b) - r) * (a + r) * auxiliary_1
        - 2.0 * (a + b)
        * (-2.0 + a + a * b + ((2.0 + b) - a) * r - r**2 - b)
        * value_2
    )
    denominator = b - r
    if (
        not np.isfinite(value_1)
        or not np.isfinite(value_2)
        or not np.isfinite(auxiliary_3)
        or abs(denominator) < 1.0e-12
        or (2.0 + b - r) <= 0.0
        or (a + r) <= 0.0
        or abs(z) >= 1.0
    ):
        return 0.0
    result = 6.0 * (2.0 + b - r) ** -2.5 * (a + r) ** -2.5 * auxiliary_3
    result /= (-2.0 + a + r) * denominator
    return float(result) if np.isfinite(result) else 0.0


def _b_operator(r: float, a: float, b: float) -> float:
    return riemann(2.0 - r, r, a, b) * (3.0 * r - 4.0 + _t_r(r)) - 2.0 * _mean_r_rs(r, a, b) * (r - 1.0)


def time_riemann(a: float, b: float, eps: float = 1.0e-9) -> float:
    """Dimensionless time from Kerswell's implicit solution."""
    integral, _ = quad(lambda value: _b_operator(value, a, b), 1.0 + eps, b,
                       limit=5000, epsabs=1.0e-6, epsrel=1.0e-6)
    return float((b - 1.0) * riemann(2.0 - b, b, a, b) + integral)


@lru_cache(maxsize=None)
def position_riemann(a: float, b: float) -> float:
    """Dimensionless position from Kerswell's implicit solution."""
    integral, _ = quad(lambda value: time_riemann(a, value), 1.0, b,
                       limit=5000, epsabs=1.0e-5, epsrel=1.0e-5)
    time = time_riemann(a, b)
    return float(-0.5 * integral + 0.5 * (b - 3.0 * a) * time - 0.5 * time**2)
