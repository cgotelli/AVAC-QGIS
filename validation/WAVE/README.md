# WAVE validation

These notebooks test the current WAVE source in water-only configurations.
They cover analytical SWASHES profiles, moving wet/dry fronts, topography
balance, Manning friction, a two-dimensional oscillating surface, and the
combined AMR/OpenMP execution path.

The six [SWASHES](https://www.idpoisson.fr/swashes/) notebooks generate their
analytical references from the pinned SWASHES 1.05.01 source included in this
repository. The Baines notebook runs
the same well-balanced configuration through AVAC and WAVE. Generated outputs
are not versioned.

See the [validation suite index](../README.md) for every notebook and its
requirements.
