"""Regression coverage for the explicit solver thread-count setting."""

from avac_qgis.core.environment import available_cpu_cores, build_avac_environment


def test_available_cpu_cores_is_positive() -> None:
    assert available_cpu_cores() >= 1


def test_explicit_omp_thread_count_overrides_the_inherited_environment() -> None:
    environment, _root = build_avac_environment(
        None,
        base={"PATH": "", "OMP_NUM_THREADS": "8"},
        omp_threads=3,
    )
    assert environment["OMP_NUM_THREADS"] == "3"
