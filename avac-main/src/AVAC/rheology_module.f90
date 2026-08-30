module rheology_module
    !
    ! Module providing constitutive laws for basal friction.
    !
    ! Three laws are implemented:
    !
    !   - Coulomb:          tau = mu * rho * g * h * cos²(theta)
    !   - Voellmy:          tau = mu * rho * g * h * cos²(theta) + rho * g / xi * speed^2
    !   - Cohesive Voellmy: tau = C + mu * rho * g * h * cos²(theta) + rho * g / xi * speed^2
    !
    ! The functions return the kinematic stress tau/rho [m^2/s^2], which is
    ! the quantity directly needed for the momentum source term.
    !
    ! The source update uses the closed-form solution of the local friction
    ! ODE.  This is important for AMR: refined levels take smaller substeps,
    ! and a forward-Euler Voellmy update otherwise changes the accumulated
    ! drag merely because the AMR level changed.
    !
    ! In 2D, theta is the local bed slope angle (rad), computed from the
    ! topography gradient in src2.f90.  The velocity magnitude (speed) is
    ! sqrt(u^2 + v^2); the direction is preserved by the explicit update.
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
    integer,      save :: imodel_rh = 0

    ! Altitude-zoned rheological parameters (populated by setprob.f90)
    integer,      save :: n_zones_rh = 1
    real(kind=8), save, allocatable :: z_breaks_rh(:)  ! (n_zones-1) thresholds, ascending (m)
    real(kind=8), save, allocatable :: mu_zones_rh(:)  ! (n_zones) Coulomb coefficients
    real(kind=8), save, allocatable :: xi_zones_rh(:)  ! (n_zones) Voellmy xi values (m/s²)
    real(kind=8), save, allocatable :: C_zones_rh(:)   ! (n_zones) cohesion values (Pa)

contains

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
        real(kind=8) :: a, b, phase, scale

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
        else if (b > 0.d0) then
            speed_new = speed / (1.d0 + b * speed * dt)
        else
            speed_new = speed
        end if

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

        !tau_rho = mu * grav * h * dcos(theta)**2
        tau_rho = mu * grav * h

    end function coulomb_tau


    ! ------------------------------------------------------------------
    ! Voellmy friction: tau/rho = mu * g * h * cos(theta) + g / xi * speed^2
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

        !tau_rho = mu * grav * h * dcos(theta)**2 + grav / xi * speed**2
        tau_rho = mu * grav * h   + grav / xi * speed**2

    end function voellmy_tau


    ! ------------------------------------------------------------------
    ! Cohesive Voellmy friction:
    !   tau/rho = C/rho + mu * g * h * cos²(theta) + g / xi * speed^2
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

        !tau_rho = C / rho + mu * grav * h * dcos(theta)**2 + grav / xi * speed**2
        tau_rho = C / rho + mu * grav * h   + grav / xi * speed**2

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
