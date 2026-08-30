# AVAC Voellmy formulation audit

Date: 29 August 2026  
Audited release candidate: AVAC4QGIS 0.5.14  
Final solver SHA-256 used by the three reruns: `dcb75230e46e78fff05bf3e1d390e946542701b87cead27e2756d70878fc13a4`

## Conclusion

The high idealized-Voellmy velocity was caused by a formulation inconsistency, not by the wet--dry front, the value of `xi`, a speed limiter, or the peak-field reader. AVAC evolved vertical depth and horizontal momentum with GeoClaw, but the former moving-state source treated these as normal depth and terrain-tangent velocity and retained GeoClaw's uncorrected `g tan(phi)` steep-slope acceleration. That is a small-slope approximation and is not valid at the 34 degree slope where the peak occurred.

The correction must transform gravity, normal stress, depth, and velocity together. Adding a cosine only to Coulomb friction would reduce resistance while leaving gravity and turbulent drag inconsistent, and could increase the velocity. AVAC now implements the Cartesian steep-slope source of Hergarten and Robl (2015), using angles derived from the fixed bed, and records physical terrain-tangent PFV inside the native peak routine.

The corrected full idealized run has a maximum PFV of 39.048 m/s, compared with 47.072 m/s before the correction and a retained ISeeSnow peer range of 10.928--39.928 m/s. Its value is inside the peer interquartile interval (37.244--39.071 m/s).

## Step-by-step trace

### 1. Conserved AVAC state

GeoClaw advances

```text
q = (h, h u, h v)
```

where `h` is vertical depth and `(u,v)` is horizontal map-grid velocity. These are not the normal depth and terrain-tangent velocity used in the physical Voellmy relation on steep terrain.

### 2. Bed and velocity geometry

For bed elevation `B(x,y)`, AVAC now computes

```text
tan(phi) = |grad B|
tan(psi) = -(u Bx + v By) / sqrt(u^2 + v^2)
cos(phi) = 1 / sqrt(1 + |grad B|^2)
cos(psi) = 1 / sqrt(1 + tan(psi)^2)
```

The represented physical quantities are

```text
normal depth          h_n = h cos(phi)
terrain-tangent speed U   = U_h / cos(psi)
horizontal speed      U_h = sqrt(u^2 + v^2)
```

`psi` can differ from `phi` when motion is not directly downslope.

### 3. Driving acceleration

The Cartesian shallow-water update supplies a map-plane acceleration proportional to the free-surface gradient. On a planar slope its bed contribution is `g tan(phi)`. For steep avalanche terrain this is too large: the physical acceleration is slope-parallel and proportional to `sin(phi)`, and AVAC advances only its horizontal projection.

Following Hergarten and Robl (2015), the excessive flow-parallel component is removed through the source coefficient

```text
g sin(phi)^2 tan(psi).
```

The correction is projected onto the instantaneous horizontal velocity direction. It does not alter the transverse component of acceleration.

### 4. Basal normal stress

With curvature neglected, the normal stress represented by vertical depth is

```text
sigma_b = rho g h cos(phi)^2.
```

The old moving-state source effectively used `rho g h`. At 34 degrees this overstates the Coulomb normal force, but that extra resistance was smaller than the simultaneous overstatement of gravity and understatement of the Voellmy drag transformation. The net effect was excessive speed.

### 5. Voellmy stress

The physical basal law is

```text
tau_b = mu sigma_b + C + rho g U^2 / xi,
```

with cohesion included only for cohesive Voellmy and the quadratic term included for the two Voellmy variants. `xi` has units m/s^2 and its input path was correct; no duplicated or inverted `xi` was found.

### 6. Cartesian source coefficients

After projecting the physical stress back to horizontal momentum, the moving-state speed source is

```text
dU_h/dt = -a - b U_h^2

a = g [sin(phi)^2 tan(psi) + mu cos(phi) cos(psi)]
    + C cos(psi) / [rho h cos(phi)]

b = g / [xi h cos(phi) cos(psi)].
```

The cohesion term is active only for cohesive Voellmy; `b` is active only for Voellmy. On a flat bed, `phi=psi=0`, so these coefficients reduce exactly to the previous flat-bed law `a=mu g + C/(rho h)` and `b=g/(xi h)`.

### 7. Planar analytical limit

For motion directly down a plane, `psi=phi`. Combining GeoClaw's base acceleration with the correction and converting to physical speed gives

```text
dU/dt = g [sin(phi) - mu cos(phi) - C/(rho g h_n) - U^2/(xi h_n)].
```

For non-cohesive Voellmy flow, the terminal speed is

```text
U_inf = sqrt(xi h_n [sin(phi) - mu cos(phi)]).
```

The source-level compiled Fortran test reproduces this identity to floating-point tolerance. At the corrected idealized peak cell (`h=4.0057 m`, `phi=34 degrees`, `mu=0.4`, `xi=2000 m/s^2`), the old formula predicts 46.90 m/s, close to the old 47.07 m/s result. The corrected physical formula predicts 38.88 m/s, close to the full-run 39.05 m/s result. This directly explains the discrepancy.

### 8. Source integration

Depth, bed gradient, rheological coefficients, and velocity direction are frozen during one operator-split source step. AVAC solves the scalar Riccati equation exactly:

- `a>0, b>0`: trigonometric solution with exact arrest at zero;
- `a=0, b>0`: rational turbulent-decay solution;
- `b=0`: exact linear Coulomb/cohesive update;
- `a<0, b>0`: hyperbolic solution tending to `sqrt(-a/b)`.

The last branch is required for uphill-directed motion. There, the geometry term is negative because it must return part of GeoClaw's excessive opposing gravity. Clamping it to positive friction would be wrong on curved terrain.

### 9. Static yield and deposition

The planar static condition remains

```text
tan(phi) <= mu
```

for the non-cohesive models. The moving-state cosine corrections do not change this identity. The cell-centred cohesive criterion includes the corresponding `1/cos(phi)^2` projection. AVAC's separate Riemann-interface arrest test retains a map-plane cohesive approximation because the one-dimensional normal solver does not have the full two-dimensional bed-gradient vector; this does not affect the three non-cohesive ISeeSnow cases.

### 10. Wet--dry handling and peak velocity

The previous audit correctly established that the old peak occurred in resolved flow, so it was not a dry-front division artefact. That result did not validate the governing moving-state geometry.

The native PFV routine now evaluates

```text
sqrt(u^2 + v^2 + (u Bx + v By)^2)
```

at every solver step wherever vertical depth exceeds 0.05 m. Computing this in the solver is necessary: the velocity direction cannot be recovered correctly after a scalar horizontal maximum has already been taken. No practical speed cap or post-processing clipping is used.

## Corrected ISeeSnow reruns

All three cases were rerun from their Jupyter notebooks at 5 m spacing, second order, `CFL=0.5`, and a 1200 s ceiling.

| Case | PFT support (km2) | Maximum PFT (m) | Maximum PFV (m/s) | PFV peer range (m/s) | Practical rest time (s) | Volume change |
|---|---:|---:|---:|---:|---:|---:|
| Idealized Voellmy | 0.2073 | 8.2467 | 39.048 | 10.928--39.928 | 980 | -0.554% |
| Real-terrain Voellmy | 0.8178 | 20.199 | 70.559 | 10.493--80.230 | not reached | +1.393% |
| Idealized Coulomb | 0.4177 | 5.9421 | 106.443 | 90.528--114.190 | 1000 | +0.154% |

The idealized PFV field is closest by RMSE to faSavageHutterFoam (0.586 m/s; active-cell correlation 0.961). Both real-terrain PFT and PFV are closest to Gerris; the PFV RMSE is 1.378 m/s with correlation 0.944. Coulomb PFV is also closest to Gerris (RMSE 3.739 m/s; correlation 0.896).

## Assumptions that remain

These are model choices or documented approximations, not newly discovered coding errors:

1. **Bed-gradient angles.** `phi` and `psi` are derived from the fixed bed (`Gerris-z_b`), not from the evolving free surface. This avoids an inconsistent numerical derivative but is still an approximation.
2. **Flow-parallel correction only.** The steep-slope correction is projected onto velocity; the transverse correction is neglected.
3. **No curvature normal stress.** Centripetal acceleration and curvature-dependent effective normal force are absent.
4. **Hydrostatic, depth-averaged pressure.** AVAC remains a shallow-flow model with earth-pressure coefficient one.
5. **First-order source splitting.** The hyperbolic and rheological/topographic correction steps use Godunov splitting even when the spatial update is second order.
6. **Static interface cohesion.** The interface arrest limiter uses a map-plane cohesion approximation; the full slope correction is used in the cell-centred moving and static sources.
7. **Peak-depth threshold.** PFV is intentionally undefined below 0.05 m vertical depth to exclude unresolved wet--dry cell velocities.

## Primary references

- Hergarten, S. and Robl, J. (2015), *Modelling rapid mass movements using the shallow water equations in Cartesian coordinates*, NHESS, https://doi.org/10.5194/nhess-15-671-2015.
- Wirbel, A. et al. (2026), *ISeeSnow v1.0*, EGUsphere preprint, https://doi.org/10.5194/egusphere-2025-6053.
