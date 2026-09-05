module rheology_module
    !
    ! Module providing constitutive laws for basal friction and the
    ! flow-parallel Cartesian steep-slope correction.
    !
    ! Three laws are implemented:
    !
    !   - Coulomb:          tau = mu * sigma
    !   - Voellmy:          tau = mu * sigma + rho * g / xi * speed^2
    !   - Cohesive Voellmy: tau = C + mu * sigma + rho * g / xi * speed^2
    !
    ! The functions return the kinematic stress tau/rho [m^2/s^2], which is
    ! the quantity directly needed for the momentum source term.
    !
    ! The source update uses the closed-form solution of the local friction
    ! ODE.  This is important for AMR: refined levels take smaller substeps,
    ! and a forward-Euler Voellmy update otherwise changes the accumulated
    ! drag merely because the AMR level changed.
    !
    ! AVAC advances vertical depth and horizontal map velocity with Cartesian
    ! shallow-water equations.  On steep terrain these variables are not the
    ! normal depth and terrain-tangent speed used by the basal law.  The
    ! moving-state source therefore applies the flow-parallel Cartesian
    ! correction of Hergarten and Robl (2015) to gravity, normal stress,
    ! depth, and basal resistance.  It does not rotate horizontal velocity
    ! through a changing terrain tangent within a frozen cell-local source
    ! step.  It reduces exactly to the established AVAC source on a flat bed.
    !
    ! Altitude-zoned rheology (set by setprob.f90, used by src2.f90):
    !   n_zones_rh   : number of altitude zones (>= 1)
    !   z_breaks_rh  : (n_zones-1) altitude thresholds in ascending order (m)
    !   mu_zones_rh  : mu value for each zone (dimensionless)
    !   xi_zones_rh  : xi value for each zone (m/s²)
    !
    !   Zone k (0-indexed) covers:
    !     k=0          : z_bed < z_breaks_rh(1)
    !     k=1..n-2     : z_breaks_rh(k) <= z_bed < z_breaks_rh(k+1)
    !     k=n_zones-1  : z_bed >= z_breaks_rh(n_zones-1)
    !
    implicit none

    ! Grid spacings for the current AMR level, set by b4step2.f90 before
    ! each Riemann solve and read by rpn2_geoclaw.f for the D-Claw static
    ! yield check.  Initialised to 1.0 (safe: check is conservative).
    real(kind=8) :: dx_avac = 1.d0
    real(kind=8) :: dy_avac = 1.d0
    real(kind=8) :: dt_avac = 0.d0
!$omp threadprivate(dx_avac, dy_avac, dt_avac)

    ! Run-wide scalar state.  This replaces the old named COMMON block,
    ! whose incompatible declarations in setprob, src2 and rpn2 caused
    ! layout-dependent rheology values at run time.
    real(kind=8), save :: rho_rh = 0.d0
    real(kind=8), save :: u_cr_rh = 0.d0
    ! Minimum depth used when reporting velocity and as the AMR kinetic-energy
    ! reference depth.  It is intentionally independent of the separate
    ! state-level shallow-momentum regularization below.
    real(kind=8), save :: velocity_depth_threshold_rh = 0.05d0
    ! Physical depth scales for the Kurganov--Petrova shallow-momentum
    ! regularization on locally non-planar terrain.  Coulomb and the Voellmy
    ! equations use separate controls because their source updates differ.
    ! Fixed values make mesh comparisons explicit; zero disables the
    ! corresponding regularization above dry_tol.
    real(kind=8), save :: state_momentum_regularization_depth_rh = 0.05d0
    real(kind=8), save :: voellmy_state_momentum_regularization_depth_rh = 0.10d0
    integer,      save :: imodel_rh = 0

    ! Altitude-zoned rheological parameters (populated by setprob.f90)
    integer,      save :: n_zones_rh = 1
    real(kind=8), save, allocatable :: z_breaks_rh(:)  ! (n_zones-1) thresholds, ascending (m)
    real(kind=8), save, allocatable :: mu_zones_rh(:)  ! (n_zones) Coulomb coefficients
    real(kind=8), save, allocatable :: xi_zones_rh(:)  ! (n_zones) Voellmy xi values (m/s²)
    real(kind=8), save, allocatable :: C_zones_rh(:)   ! (n_zones) cohesion values (Pa)

contains

    ! ------------------------------------------------------------------
    ! Kurganov--Petrova desingularization of velocity near a wet/dry front.
    !
    ! For h >= h_eps this is exactly hu/h and hv/h.  Below h_eps it smoothly
    ! removes momentum faster than depth tends to zero, preventing a tiny
    ! shallow-water depth from carrying an unresolved, arbitrarily large
    ! velocity.  The caller decides where the operation is appropriate and
    ! reconstructs momentum as h*u and h*v, so depth and flow direction are
    ! unchanged.
    ! ------------------------------------------------------------------
    subroutine regularized_velocity(h, hu, hv, h_eps, u, v)
        implicit none
        real(kind=8), intent(in) :: h, hu, hv, h_eps
        real(kind=8), intent(out) :: u, v
        real(kind=8) :: h4, eps4, denominator

        if (h <= 0.d0) then
            u = 0.d0
            v = 0.d0
            return
        end if

        h4 = h**4
        eps4 = max(0.d0, h_eps)**4
        denominator = dsqrt(h4 + max(h4, eps4))
        if (denominator <= 0.d0) then
            u = 0.d0
            v = 0.d0
        else
            u = dsqrt(2.d0) * h * hu / denominator
            v = dsqrt(2.d0) * h * hv / denominator
        end if

    end subroutine regularized_velocity

    ! ------------------------------------------------------------------
    ! Detect whether the 3x3 bed stencil departs materially from an affine
    ! plane.  This is a geometry criterion, not a case-specific switch.
    ! Constant-slope analytical beds return false even when steep, while a
    ! curved or piecewise-planar terrain returns true around its curvature.
    ! ------------------------------------------------------------------
    logical function locally_nonplanar_bed(bc, bw, be, bs, bn, &
                                           bsw, bse, bnw, bne)
        implicit none
        real(kind=8), intent(in) :: bc, bw, be, bs, bn
        real(kind=8), intent(in) :: bsw, bse, bnw, bne
        real(kind=8) :: bed_scale, local_relief, nonplanarity, tolerance
        real(kind=8) :: dw, de, ds, dn, dsw, dse, dnw, dne

        ! Centre every difference on the local cell so adding a constant
        ! vertical datum does not alter the geometric residual.  The second
        ! tolerance term accounts only for the precision lost while forming
        ! those differences when the stored elevations themselves are large.
        dw = bw - bc
        de = be - bc
        ds = bs - bc
        dn = bn - bc
        dsw = bsw - bc
        dse = bse - bc
        dnw = bnw - bc
        dne = bne - bc
        local_relief = max(dabs(dw), dabs(de), dabs(ds), dabs(dn), &
                           dabs(dsw), dabs(dse), dabs(dnw), dabs(dne))
        bed_scale = max(1.d0, dabs(bc), dabs(bw), dabs(be), dabs(bs), &
                        dabs(bn), dabs(bsw), dabs(bse), dabs(bnw), dabs(bne))
        nonplanarity = max(dabs(de + dw), dabs(dn + ds), &
                           dabs((dne - dnw) - (dse - dsw)))
        ! This is an affine/non-affine classifier, not a physical curvature
        ! cutoff.  Ignore only local arithmetic noise; any resolved departure
        ! from a plane remains eligible at each AMR level.
        tolerance = max(1.d-12 * max(1.d0, local_relief), &
                        64.d0 * epsilon(1.d0) * bed_scale)
        locally_nonplanar_bed = nonplanarity > tolerance

    end function locally_nonplanar_bed

    ! ------------------------------------------------------------------
    ! Dimensionless two-dimensional static-yield ratio for one cell.
    !
    ! This is an eligibility diagnostic for the static Riemann limiter, not
    ! a momentum source.  The normal Riemann solver only receives a 1-D
    ! slice, so b4step2 computes this full map-plane free-surface gradient
    ! before the directional sweeps.  A value <= 1 means that the local
    ! vector driving gradient is no greater than the static Coulomb/cohesive
    ! strength; a negative value means that no safe static classification is
    ! available (dry cell, invalid spacing, or zero static strength).
    !
    ! The gradient is centred on the cell.  The bed-normal cohesion factor
    ! uses the full two-dimensional DEM slope, cos(theta_b)^2 =
    ! 1/(1 + B_x^2 + B_y^2).  Voellmy drag vanishes at rest and therefore
    ! does not enter this static condition.
    ! ------------------------------------------------------------------
    pure function static_yield_ratio_2d(h, eta_w, eta_e, eta_s, eta_n, &
                                        b_w, b_e, b_s, b_n, dx, dy, mu, C, &
                                        rho, grav, imodel) result(ratio)
        implicit none
        real(kind=8), intent(in) :: h, eta_w, eta_e, eta_s, eta_n
        real(kind=8), intent(in) :: b_w, b_e, b_s, b_n, dx, dy, mu, C, rho, grav
        integer, intent(in) :: imodel
        real(kind=8) :: ratio
        real(kind=8) :: eta_x, eta_y, b_x, b_y, cos2_theta
        real(kind=8) :: yield_gradient

        ratio = -1.d0
        if (h <= 0.d0 .or. dx <= 0.d0 .or. dy <= 0.d0) return

        eta_x = (eta_e - eta_w) / (2.d0 * dx)
        eta_y = (eta_n - eta_s) / (2.d0 * dy)
        b_x = (b_e - b_w) / (2.d0 * dx)
        b_y = (b_n - b_s) / (2.d0 * dy)
        cos2_theta = 1.d0 / (1.d0 + b_x**2 + b_y**2)

        yield_gradient = max(0.d0, mu)
        if (imodel == 3 .and. C > 0.d0 .and. rho > 0.d0 .and. grav > 0.d0) then
            yield_gradient = yield_gradient + C / (rho * grav * h * cos2_theta)
        end if
        if (yield_gradient > 0.d0) then
            ratio = dsqrt(eta_x**2 + eta_y**2) / yield_gradient
        end if

    end function static_yield_ratio_2d

    ! ------------------------------------------------------------------
    ! Exact non-negative solution of the frozen-coefficient source
    !
    !     d(speed)/dt = -a - b*speed^2.
    !
    ! ``a`` may be negative for uphill motion because the geometric term
    ! returns part of GeoClaw's excessive opposing map-plane gravity.
    ! ------------------------------------------------------------------
    function source_speed_after(speed, dt, a, b) result(speed_new)
        implicit none
        real(kind=8), intent(in) :: speed, dt, a, b
        real(kind=8) :: speed_new
        real(kind=8) :: phase, scale, terminal, decay

        if (speed <= 0.d0 .or. dt <= 0.d0) then
            speed_new = max(0.d0, speed)
            return
        end if

        if (a > 0.d0 .and. b > 0.d0) then
            scale = dsqrt(b / a)
            phase = datan(speed * scale) - dsqrt(a * b) * dt
            if (phase <= 0.d0) then
                speed_new = 0.d0
            else
                speed_new = dtan(phase) / scale
            end if
        else if (a < 0.d0 .and. b > 0.d0) then
            terminal = dsqrt(-a / b)
            decay = dexp(-2.d0 * dsqrt((-a) * b) * dt)
            speed_new = terminal * ((speed + terminal) + &
                        (speed - terminal) * decay) / &
                        ((speed + terminal) - (speed - terminal) * decay)
        else if (a > 0.d0 .and. b < 0.d0) then
            ! Convex curvature can make b negative while basal contact is
            ! retained.  The equilibrium sqrt(a/|b|) is unstable.
            terminal = dsqrt(a / (-b))
            if (dabs(speed-terminal) <= 16.d0*epsilon(terminal)*terminal) then
                speed_new = terminal
            else
                decay = ((speed-terminal)/(speed+terminal)) * &
                        dexp(2.d0*dsqrt(a*(-b))*dt)
                if (decay <= -1.d0) then
                    speed_new = 0.d0
                else if (decay >= 1.d0) then
                    speed_new = huge(1.d0)
                else
                    speed_new = terminal * (1.d0+decay) / (1.d0-decay)
                end if
            end if
        else if (a > 0.d0) then
            speed_new = max(0.d0, speed - a * dt)
        else if (a < 0.d0 .and. b < 0.d0) then
            scale = dsqrt((-b) / (-a))
            phase = datan(speed*scale) + dsqrt(a*b)*dt
            if (phase >= 0.5d0*acos(-1.d0)) then
                speed_new = huge(1.d0)
            else
                speed_new = dtan(phase) / scale
            end if
        else if (a < 0.d0) then
            speed_new = speed - a * dt
        else if (b > 0.d0) then
            speed_new = speed / (1.d0 + b * speed * dt)
        else if (b < 0.d0) then
            decay = 1.d0 + b*speed*dt
            if (decay <= 0.d0) then
                speed_new = huge(1.d0)
            else
                speed_new = speed / decay
            end if
        else
            speed_new = speed
        end if

    end function source_speed_after

    ! ------------------------------------------------------------------
    ! Flow-parallel Cartesian steep-slope source coefficients.
    !
    ! AVAC/GeoClaw evolves vertical depth h and horizontal velocity (u,v).
    ! With the bed-surface variant of Hergarten and Robl (2015),
    !
    !   tan(phi) = |grad B|,
    !   tan(psi) = -(u B_x + v B_y) / |v_h|,
    !
    ! and the geometric correction plus basal resistance reduce to
    !
    !   d|v_h|/dt = -a - b|v_h|^2,
    !
    !   a = g[sin(phi)^2 tan(psi) + mu cos(phi) cos(psi)]
    !       + C cos(psi)/(rho h cos(phi)),
    !   b = g/[xi h cos(phi) cos(psi)]
    !       + mu k_v cos(phi) cos(psi).
    !
    ! k_v is the bed Hessian projected onto the horizontal flow direction.
    ! Its term is the Fischer et al. (2012) centripetal correction to normal
    ! load: positive concave curvature increases Coulomb resistance; negative
    ! convex curvature decreases it.  AVAC deliberately does not add a local
    ! source for rotation of the terrain-tangent velocity into the horizontal
    ! map plane.  That changing-basis effect requires the material position
    ! and changing terrain angle along its path.  Treating it as a coefficient
    ! frozen at one cell produces a spurious Riccati acceleration and a
    ! finite-time pole.  The horizontal map velocity is therefore not rotated
    ! by this source step; a terrain-following state or a coupled flux/source
    ! formulation would be required for that extension.  The component
    ! transverse to the instantaneous flow direction is not included.
    ! ------------------------------------------------------------------
    subroutine cartesian_source_coefficients(h, u, v, dzdx, dzdy, &
                                             d2zdx2, d2zdxdy, d2zdy2, &
                                             mu, xi, C, rho, grav, imodel, &
                                             a, b, cos_phi, cos_psi, tan_psi, &
                                             curvature)
        implicit none
        real(kind=8), intent(in) :: h, u, v, dzdx, dzdy, mu, xi, C, rho, grav
        real(kind=8), intent(in) :: d2zdx2, d2zdxdy, d2zdy2
        integer, intent(in) :: imodel
        real(kind=8), intent(out) :: a, b, cos_phi, cos_psi, tan_psi, curvature
        real(kind=8) :: speed, tan2_phi, sin2_phi

        speed = dsqrt(u**2 + v**2)
        tan2_phi = dzdx**2 + dzdy**2
        cos_phi = 1.d0 / dsqrt(1.d0 + tan2_phi)
        sin2_phi = tan2_phi / (1.d0 + tan2_phi)

        if (speed > 0.d0) then
            tan_psi = -(u * dzdx + v * dzdy) / speed
        else
            tan_psi = 0.d0
        end if
        cos_psi = 1.d0 / dsqrt(1.d0 + tan_psi**2)

        curvature = 0.d0
        if (speed > 0.d0) then
            curvature = (u*u*d2zdx2 + 2.d0*u*v*d2zdxdy + &
                         v*v*d2zdy2) / speed**2
        end if

        a = grav * (sin2_phi * tan_psi + mu * cos_phi * cos_psi)
        if (imodel == 3 .and. rho > 0.d0 .and. h > 0.d0) then
            a = a + max(0.d0, C) * cos_psi / (rho * h * cos_phi)
        end if

        b = 0.d0
        if (imodel >= 2 .and. xi > 0.d0 .and. h > 0.d0) then
            b = grav / (xi * h * cos_phi * cos_psi)
        end if
        ! Curvature contributes only through the contact-normal load.  A
        ! changing-basis transport term is not a frozen local source; see the
        ! formulation note above.
        b = b + mu * curvature * cos_phi * cos_psi

    end subroutine cartesian_source_coefficients

    ! ------------------------------------------------------------------
    ! Apply curvature only while the material retains non-negative contact.
    ! For convex curvature, g + k_v*speed^2 can cross zero.  Coulomb gravity
    ! and curvature vanish together beyond that boundary; Voellmy drag and
    ! cohesion remain unchanged.  Each autonomous branch is integrated
    ! exactly and a possible crossing is located by bisection.
    ! ------------------------------------------------------------------
    function contact_limited_speed_after(speed, dt, a_contact, b_contact, &
                                         a_free, b_free, curvature, grav) &
                                         result(speed_new)
        implicit none
        real(kind=8), intent(in) :: speed, dt, a_contact, b_contact
        real(kind=8), intent(in) :: a_free, b_free, curvature, grav
        real(kind=8) :: speed_new
        real(kind=8) :: threshold, trial, tlo, thi, tmid, value, tcross
        integer :: iteration

        if (curvature >= 0.d0 .or. grav <= 0.d0) then
            speed_new = source_speed_after(speed, dt, a_contact, b_contact)
            return
        end if

        threshold = dsqrt(-grav / curvature)
        if (speed < threshold) then
            trial = source_speed_after(speed, dt, a_contact, b_contact)
            if (trial <= threshold) then
                speed_new = trial
                return
            end if
            tlo = 0.d0
            thi = dt
            do iteration = 1, 60
                tmid = 0.5d0*(tlo+thi)
                value = source_speed_after(speed, tmid, a_contact, b_contact)
                if (value < threshold) then
                    tlo = tmid
                else
                    thi = tmid
                end if
            end do
            tcross = 0.5d0*(tlo+thi)
            speed_new = source_speed_after(threshold, dt-tcross, a_free, b_free)
        else
            trial = source_speed_after(speed, dt, a_free, b_free)
            if (trial >= threshold) then
                speed_new = trial
                return
            end if
            tlo = 0.d0
            thi = dt
            do iteration = 1, 60
                tmid = 0.5d0*(tlo+thi)
                value = source_speed_after(speed, tmid, a_free, b_free)
                if (value > threshold) then
                    tlo = tmid
                else
                    thi = tmid
                end if
            end do
            tcross = 0.5d0*(tlo+thi)
            speed_new = source_speed_after(threshold, dt-tcross, &
                                           a_contact, b_contact)
        end if

    end function contact_limited_speed_after

    function cartesian_speed_after(speed, dt, h, u, v, dzdx, dzdy, &
                                   d2zdx2, d2zdxdy, d2zdy2, mu, xi, &
                                   C, rho, grav, imodel) result(speed_new)
        implicit none
        real(kind=8), intent(in) :: speed, dt, h, u, v, dzdx, dzdy
        real(kind=8), intent(in) :: d2zdx2, d2zdxdy, d2zdy2
        real(kind=8), intent(in) :: mu, xi, C, rho, grav
        integer, intent(in) :: imodel
        real(kind=8) :: speed_new
        real(kind=8) :: a, b, cos_phi, cos_psi, tan_psi, curvature
        real(kind=8) :: coulomb_projection, a_free, b_free

        if (speed <= 0.d0 .or. dt <= 0.d0 .or. h <= 0.d0) then
            speed_new = max(0.d0, speed)
            return
        end if

        call cartesian_source_coefficients(h, u, v, dzdx, dzdy, &
                                           d2zdx2, d2zdxdy, d2zdy2, &
                                           mu, xi, C, rho, grav, imodel, a, b, &
                                           cos_phi, cos_psi, tan_psi, curvature)
        coulomb_projection = mu*cos_phi*cos_psi
        a_free = a - grav*coulomb_projection
        b_free = b - curvature*coulomb_projection
        speed_new = contact_limited_speed_after(speed, dt, a, b, &
                                                a_free, b_free, curvature, grav)

    end function cartesian_speed_after

    ! ------------------------------------------------------------------
    ! Exact local speed after one basal-friction source step.
    !
    ! With depth and rheological coefficients frozen during the source step,
    ! the implemented constitutive laws reduce to
    !
    !     dv/dt = -a - b*v^2,
    !
    ! where a is Coulomb plus cohesive acceleration and b is the Voellmy
    ! coefficient.  Integrating this equation analytically removes the
    ! timestep-dependent over-damping of forward Euler while retaining an
    ! exact zero-speed state when Coulomb/cohesive resistance arrests flow.
    ! ------------------------------------------------------------------
    function friction_speed_after(speed, dt, h, mu, xi, C, rho, grav, imodel) result(speed_new)
        implicit none
        real(kind=8), intent(in) :: speed, dt, h, mu, xi, C, rho, grav
        integer, intent(in) :: imodel
        real(kind=8) :: speed_new
        real(kind=8) :: a, b

        if (speed <= 0.d0 .or. dt <= 0.d0 .or. h <= 0.d0) then
            speed_new = max(0.d0, speed)
            return
        end if

        a = max(0.d0, mu * grav)
        if (imodel == 3 .and. rho > 0.d0) then
            a = a + max(0.d0, C) / (rho * h)
        end if

        b = 0.d0
        if (imodel >= 2 .and. xi > 0.d0) then
            b = grav / (xi * h)
        end if

        speed_new = source_speed_after(speed, dt, a, b)

    end function friction_speed_after

    ! ------------------------------------------------------------------
    ! Coulomb friction: tau/rho = mu * g * h * cos²(theta)
    !
    ! Arguments:
    !   mu    - Coulomb friction coefficient (dimensionless)
    !   grav  - gravitational acceleration (m/s^2)
    !   h     - flow depth (m)
    !   theta - local bed slope angle (rad)
    ! ------------------------------------------------------------------
    function coulomb_tau(mu, grav, h, theta) result(tau_rho)
        implicit none
        real(kind=8), intent(in) :: mu, grav, h, theta
        real(kind=8) :: tau_rho

        tau_rho = mu * grav * h * dcos(theta)**2

    end function coulomb_tau


    ! ------------------------------------------------------------------
    ! Voellmy friction for vertical h and horizontal speed:
    ! tau/rho = mu*g*h*cos(theta)^2 + g/xi*(speed/cos(theta))^2
    !
    ! Arguments:
    !   mu    - Coulomb friction coefficient (dimensionless)
    !   grav  - gravitational acceleration (m/s^2)
    !   h     - flow depth (m)
    !   theta - local bed slope angle (rad)
    !   xi    - Voellmy turbulence coefficient (m/s^2)
    !   speed - horizontal map speed sqrt(u^2+v^2) (m/s)
    !
    ! Note: Coulomb is recovered in the limit xi -> infinity.
    ! ------------------------------------------------------------------
    function voellmy_tau(mu, grav, h, theta, xi, speed) result(tau_rho)
        implicit none
        real(kind=8), intent(in) :: mu, grav, h, theta, xi, speed
        real(kind=8) :: tau_rho

        tau_rho = mu * grav * h * dcos(theta)**2 + &
                  grav / xi * (speed / dcos(theta))**2

    end function voellmy_tau


    ! ------------------------------------------------------------------
    ! Cohesive Voellmy friction:
    !   tau/rho = C/rho + mu*g*h*cos(theta)^2
    !             + g/xi*(speed/cos(theta))^2
    !
    ! Arguments:
    !   mu    - Coulomb friction coefficient (dimensionless)
    !   grav  - gravitational acceleration (m/s^2)
    !   h     - flow depth (m)
    !   theta - local bed slope angle (rad)
    !   xi    - Voellmy turbulence coefficient (m/s^2)
    !   speed - depth-averaged speed sqrt(u^2+v^2) (m/s)
    !   C     - cohesion (Pa = kg/m/s^2)
    !   rho   - bulk density (kg/m^3)
    ! ------------------------------------------------------------------
    function cohesive_voellmy_tau(mu, grav, h, theta, xi, speed, C, rho) result(tau_rho)
        implicit none
        real(kind=8), intent(in) :: mu, grav, h, theta, xi, speed, C, rho
        real(kind=8) :: tau_rho

        tau_rho = C / rho + mu * grav * h * dcos(theta)**2 + &
                  grav / xi * (speed / dcos(theta))**2

    end function cohesive_voellmy_tau

    ! ------------------------------------------------------------------
    ! Altitude-zoned lookup: returns mu and xi for a given bed elevation.
    !
    ! Zones are ordered by ascending altitude:
    !   zone 1 applies for z_bed < z_breaks_rh(1)
    !   zone k applies for z_breaks_rh(k-1) <= z_bed < z_breaks_rh(k)
    !   zone n applies for z_bed >= z_breaks_rh(n-1)
    !
    ! When n_zones_rh == 1 (uniform rheology), z_breaks_rh is not
    ! allocated and the unique values mu_zones_rh(1), xi_zones_rh(1)
    ! are returned for any elevation.
    ! ------------------------------------------------------------------
    subroutine get_mu_xi(z_bed, mu_out, xi_out, C_out)
        implicit none
        real(kind=8), intent(in)  :: z_bed
        real(kind=8), intent(out) :: mu_out, xi_out, C_out
        integer :: k

        k = 1
        do while (k < n_zones_rh)
            if (z_bed >= z_breaks_rh(k)) then
                k = k + 1
            else
                exit
            end if
        end do
        mu_out = mu_zones_rh(k)
        xi_out = xi_zones_rh(k)
        C_out  = C_zones_rh(k)

    end subroutine get_mu_xi

end module rheology_module
