# AVAC validation

These notebooks exercise the current AVAC source against analytical shallow
water and Coulomb-flow solutions. The originally one-dimensional problems are
represented as uniform narrow two-dimensional domains, and the numerical
centerline is compared with theory.

Each case notebook defines and runs its own initial condition, boundary
conditions, grid, output schedule, and physical parameters. The generated
summary records the solver executable's SHA-256 so a result cannot be confused
with one produced by another AVAC build.

The publication runs use three dynamically regridded AMR levels.  Narrow,
overlapping space--time corridors around the independently known analytical
front paths keep both boundaries on the finest longitudinal mesh while distant
regions remain at the base resolution.  Those analytical paths allocate mesh
resolution only; they are never supplied to AVAC's state or flux calculation.
The separate paper-figure notebook reads the saved numerical arrays and never
launches AVAC; plots can therefore be revised without repeating a simulation.

See the [validation suite index](../README.md) for notebook links and system
requirements.
