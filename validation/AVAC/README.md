# AVAC validation

These notebooks exercise the current AVAC source against analytical shallow
water and Coulomb-flow solutions. The originally one-dimensional problems are
represented as uniform narrow two-dimensional domains, and the numerical
centerline is compared with theory.

Each case notebook defines and runs its own initial condition, boundary
conditions, grid, output schedule, and physical parameters. The generated
summary records the solver executable's SHA-256 so a result cannot be confused
with one produced by another AVAC build.

See the [validation suite index](../README.md) for notebook links and system
requirements.
