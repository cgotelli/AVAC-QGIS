module rheology_module
    !
    ! Module providing constitutive laws for basal friction.
    !
    ! Three basal laws are implemented:
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
    ! normal depth and terrain-tangent speed used by the Voellmy law.  The
    ! moving-state source therefore applies the Cartesian steep-slope
    ! correction of Hergarten and Robl (2015): gravity, normal stress, depth,
    ! and velocity are transformed together.  Adding a lone cos(theta) to the
    ! old friction term would be inconsistent.  The correction retains the
    ! planar Coulomb yield identity tan(theta) = mu.
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
    real(kind=8), save :: velocity_depth_threshold_rh = 0.05d0
    integer,      save :: imodel_rh = 0

    ! Altitude-zoned rheological parameters (populated by setprob.f90)
    integer,      save :: n_zones_rh = 1
    real(kind=8), save, allocatable :: z_breaks_rh(:)  ! (n_zones-1) thresholds, ascending (m)
    real(kind=8), save, allocatable :: mu_zones_rh(:)  ! (n_zones) Coulomb coefficients
    real(kind=8), save, allocatable :: xi_zones_rh(:)  ! (n_zones) Voellmy xi values (m/s²)
    real(kind=8), save, allocatable :: C_zones_rh(:)   ! (n_zones) cohesion values (Pa)

contains

    ! ------------------------------------------------------------------
    ! Exact non-negative solution of the frozen-coefficient Riccati source
    !
    !     d(speed)/dt = -a - b*speed^2,    b >= 0.
    !
    ! ``a`` may be negative.  This occurs for uphill motion because the
    ! steep-slope term must compensate part of GeoClaw's uncorrected map-plane
    ! gravity.  Treating that term as ordinary positive friction would give
    ! the wrong acceleration on curved terrain.
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
        else if (a > 0.d0) then
            speed_new = max(0.d0, speed - a * dt)
        else if (a < 0.d0 .and. b > 0.d0) then
            ! Stable tanh/coth solution tending to sqrt(-a/b) from either side.
            terminal = dsqrt(-a / b)
            decay = dexp(-2.d0 * dsqrt((-a) * b) * dt)
            speed_new = terminal * ((speed + terminal) + (speed - terminal) * decay) / &
                        ((speed + terminal) - (speed - terminal) * decay)
        else if (a < 0.d0) then
            speed_new = speed - a * dt
        else if (b > 0.d0) then
            speed_new = speed / (1.d0 + b * speed * dt)
        else
            speed_new = speed
        end if

    end function source_speed_after

    ! ------------------------------------------------------------------
    ! Cartesian steep-slope source coefficients for AVAC's moving state.
    !
    ! AVAC/GeoClaw evolves vertical depth h and horizontal velocity (u,v).
    ! With the bed-surface variant of Hergarten and Robl (2015),
    !
    !   tan(phi) = |grad B|,
    !   tan(psi) = -(u B_x + v B_y) / |v_h|,
    !
    ! and the flow-parallel correction plus basal resistance reduce to
    ! d|v_h|/dt = -a - b|v_h|^2, where
    !
    !   a = g[sin(phi)^2 tan(psi) + mu cos(phi) cos(psi)]
    !       + C cos(psi)/(rho h cos(phi)),
    !   b = g/[xi h cos(phi) cos(psi)].
    !
    ! The first term in a corrects GeoClaw's large-slope gravity; the other
    ! terms are Coulomb/cohesive and Voellmy resistance.  The total physical
    ! speed used by Voellmy is |v_h|/cos(psi), and normal depth is h cos(phi).
    ! ------------------------------------------------------------------
    subroutine cartesian_source_coefficients(h, u, v, dzdx, dzdy, mu, xi, C, &
                                             rho, grav, imodel, a, b, &
                                             cos_phi, cos_psi, tan_psi)
        implicit none
        real(kind=8), intent(in) :: h, u, v, dzdx, dzdy, mu, xi, C, rho, grav
        integer, intent(in) :: imodel
        real(kind=8), intent(out) :: a, b, cos_phi, cos_psi, tan_psi
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

        a = grav * (sin2_phi * tan_psi + mu * cos_phi * cos_psi)
        if (imodel == 3 .and. rho > 0.d0 .and. h > 0.d0) then
            a = a + max(0.d0, C) * cos_psi / (rho * h * cos_phi)
        end if

        b = 0.d0
        if (imodel >= 2 .and. xi > 0.d0 .and. h > 0.d0) then
            b = grav / (xi * h * cos_phi * cos_psi)
        end if

    end subroutine cartesian_source_coefficients

    function cartesian_speed_after(speed, dt, h, u, v, dzdx, dzdy, mu, xi, &
                                   C, rho, grav, imodel) result(speed_new)
        implicit none
        real(kind=8), intent(in) :: speed, dt, h, u, v, dzdx, dzdy
        real(kind=8), intent(in) :: mu, xi, C, rho, grav
        integer, intent(in) :: imodel
        real(kind=8) :: speed_new
        real(kind=8) :: a, b, cos_phi, cos_psi, tan_psi

        if (speed <= 0.d0 .or. dt <= 0.d0 .or. h <= 0.d0) then
            speed_new = max(0.d0, speed)
            return
        end if

        call cartesian_source_coefficients(h, u, v, dzdx, dzdy, mu, xi, C, &
                                           rho, grav, imodel, a, b, &
                                           cos_phi, cos_psi, tan_psi)
        speed_new = source_speed_after(speed, dt, a, b)

    end function cartesian_speed_after

    ! ------------------------------------------------------------------
    ! Wet/dry velocity desingularization.
    !
    ! The Kurganov--Petrova formula avoids division by a vanishing depth
    ! while remaining exactly equal to momentum/depth when h >= h_eps:
    !
    !   u = sqrt(2) h (hu) / sqrt(h^4 + max(h^4,h_eps^4)).
    !
    ! Momentum must be reconstructed as h*u after this calculation to keep
    ! the shallow-flow state consistent.  AVAC bounds h_eps by two per cent
    ! of the local cell spacing and twice the configured minimum depth for a
    ! reported velocity (and never below dry_tolerance).  The operation
    ! therefore affects only the numerically unresolved wet/dry fringe, not
    ! resolved avalanche depths.
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
    ! One-dimensional downslope Coulomb stress for vertical depth h and
    ! horizontal speed: tau/rho = mu * g * h * cos(theta)^2.
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
    ! One-dimensional downslope Voellmy stress.  Here h is vertical depth and
    ! speed is horizontal, so normal depth is h*cos(theta) and physical speed
    ! is speed/cos(theta).
    !
    ! Arguments:
    !   mu    - Coulomb friction coefficient (dimensionless)
    !   grav  - gravitational acceleration (m/s^2)
    !   h     - flow depth (m)
    !   theta - local bed slope angle (rad)
    !   xi    - Voellmy turbulence coefficient (m/s^2)
    !   speed - depth-averaged speed sqrt(u^2+v^2) (m/s)
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
    ! One-dimensional downslope cohesive Voellmy stress for vertical depth
    ! and horizontal speed.
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
