! src2.f90 for AVAC 4: version = 2.0
subroutine src2(meqn,mbc,mx,my,xlower,ylower,dx,dy,q,maux,aux,t,dt)

    ! Called to update q by solving source term equation
    ! $q_t = \psi(q)$ over time dt starting at time t.
    !
    ! Moving-state steep-slope and basal-resistance source term.
    ! Supported constitutive laws (selected via imodel_rh in rheology_module):
    !
    !   imodel = 1  Coulomb:          tau = mu * sigma
    !   imodel = 2  Voellmy:          tau = mu * sigma
    !                                     + rho * g / xi * speed^2
    !   imodel = 3  Cohesive Voellmy: tau = C + mu * sigma
    !                                     + rho * g / xi * speed^2
    !
    ! AVAC evolves vertical depth and horizontal map velocity.  The source
    ! applies the flow-parallel Cartesian steep-slope correction of Hergarten
    ! and Robl (2015), so gravity, normal stress, depth, and velocity are
    ! transformed consistently.  On a flat bed this is exactly the previous
    ! AVAC Coulomb/Voellmy source.
    !
    ! Closed-form update of dv/dt = -a - b*v^2, with a floor at zero:
    !   speed_new = cartesian_speed_after(...)
    !   (hu)^{n+1} = (hu / speed) * h * speed_new
    !   (hv)^{n+1} = (hv / speed) * h * speed_new
    !
    ! This allows exact stopping (speed = 0 precisely).

    use geoclaw_module, only: g => grav, dry_tolerance, speed_limit
    use geoclaw_module, only: friction_forcing, friction_depth
    use geoclaw_module, only: manning_coefficient, manning_break, num_manning
    use rheology_module

    implicit none

    ! Input parameters
    integer, intent(in) :: meqn, mbc, mx, my, maux
    double precision, intent(in) :: xlower, ylower, dx, dy, t, dt

    ! Solution arrays
    double precision, intent(inout) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    double precision, intent(inout) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)

    ! Locals
    integer :: i, j, nman
    real(kind=8) :: h, hu, hv, u, v, speed, speed_new, sratio, h_eps
    real(kind=8) :: dzdx, dzdy, d2zdx2, d2zdxdy, d2zdy2, theta_local
    real(kind=8) :: tau_driving_rho, tau_static_rho
    real(kind=8) :: mu_local, xi_local, C_local   ! altitude-zoned rheology (from get_mu_xi)
    real(kind=8) :: coeff, gamma
    logical :: at_rest, patch_nonplanar

    if (friction_forcing) then
        do j = 1, my
            do i = 1, mx
                h = q(1,i,j)

                if (h <= dry_tolerance) then
                    q(2,i,j) = 0.d0
                    q(3,i,j) = 0.d0

                else if (h <= friction_depth) then
                    hu = q(2,i,j)
                    hv = q(3,i,j)

                    ! Water mode uses GeoClaw's standard semi-implicit Manning
                    ! update.  This is the Saint-Venant source term required by
                    ! the SWASHES MacDonald benchmarks; granular modes below are
                    ! unchanged.
                    if (imodel_rh == 0) then
                        coeff = 0.d0
                        do nman = num_manning, 1, -1
                            if (aux(1,i,j) < manning_break(nman)) then
                                coeff = manning_coefficient(nman)
                            end if
                        end do
                        gamma = dsqrt(hu**2+hv**2)*g*coeff**2 / &
                                (h**(7.d0/3.d0))
                        q(2,i,j) = hu/(1.d0+dt*gamma)
                        q(3,i,j) = hv/(1.d0+dt*gamma)
                        cycle
                    end if

                    ! Altitude-dependent rheology: pick mu and xi for this cell's bed elevation
                    call get_mu_xi(aux(1,i,j), mu_local, xi_local, C_local)

                    ! Local bed slope angle from centred topography gradient
                    dzdx = (aux(1,i+1,j) - aux(1,i-1,j)) / (2.d0*dx)
                    dzdy = (aux(1,i,j+1) - aux(1,i,j-1)) / (2.d0*dy)
                    d2zdx2 = (aux(1,i+1,j) - 2.d0*aux(1,i,j) + &
                              aux(1,i-1,j)) / dx**2
                    d2zdy2 = (aux(1,i,j+1) - 2.d0*aux(1,i,j) + &
                              aux(1,i,j-1)) / dy**2
                    d2zdxdy = (aux(1,i+1,j+1) - aux(1,i+1,j-1) - &
                               aux(1,i-1,j+1) + aux(1,i-1,j-1)) / &
                              (4.d0*dx*dy)
                    theta_local = datan(dsqrt(dzdx**2 + dzdy**2))

                    ! Current speed
                    u = hu / h
                    v = hv / h
                    speed = dsqrt(u**2 + v**2)

                    ! Static yield test (Mohr-Coulomb): keep cells at rest if their
                    ! momentum is exactly zero and the driving stress is below yield.
                    ! A cell in motion must NOT be stopped here — it decelerates via
                    ! kinetic friction until speed_new reaches zero (see below).
                    !   tau_driving / rho = g * h * tan(theta)
                    !   tau_static  / rho = mu * g * h
                    !                            [+ C/(rho*cos(theta)^2)]
                    ! (turbulent Voellmy term vanishes at v=0 => same for imodel=2)
                    tau_driving_rho = g * h * dtan(theta_local)
                    if (imodel_rh == 3) then
                        tau_static_rho = C_local / &
                                         (rho_rh * dcos(theta_local)**2) + &
                                         mu_local * g * h
                    else
                        tau_static_rho = mu_local * g * h
                    end if
                    at_rest = (speed == 0.d0) .and. (tau_driving_rho <= tau_static_rho)
                    if (at_rest) then
                        q(2,i,j) = 0.d0
                        q(3,i,j) = 0.d0
                    end if

                    if (.not. at_rest .and. speed > 0.d0) then
                        ! Closed-form source update with floor at zero.  Unlike
                        ! forward Euler, this gives the same accumulated local
                        ! Voellmy drag when AMR subcycling changes dt.
                        ! Mohr-Coulomb stop: if kinetic friction brings speed to zero
                        ! (speed_new <= 0) AND the driving stress is below yield,
                        ! the cell stops definitively.  A cell on a super-yield slope
                        ! (tau_driving > tau_static) must NOT be zeroed, otherwise
                        ! the slope re-accelerates it on the next step, creating a
                        ! freeze/restart oscillation that violates the CFL.
                        speed_new = cartesian_speed_after(speed, dt, h, u, v, &
                                                         dzdx, dzdy, d2zdx2, &
                                                         d2zdxdy, d2zdy2, mu_local, &
                                                         xi_local, C_local, rho_rh, &
                                                         g, imodel_rh)
                        if (speed_new <= 0.d0 .and. &
                            tau_driving_rho <= tau_static_rho) then
                            ! Definitive stop: slope cannot restart the cell.
                            q(2,i,j) = 0.d0
                            q(3,i,j) = 0.d0
                        else
                            ! Floor at zero, but no forced stop on super-yield slopes.
                            speed_new = max(0.d0, speed_new)
                            if (speed_new > 0.d0) then
                                q(2,i,j) = hu * speed_new / speed
                                q(3,i,j) = hv * speed_new / speed
                            else
                                q(2,i,j) = 0.d0
                                q(3,i,j) = 0.d0
                            end if
                        end if
                    end if
                end if
            end do
        end do

        ! A second-order wet/dry update can leave a tiny amount of momentum
        ! in a very shallow cell.  On non-planar terrain that unresolved seed
        ! may subsequently be transported into resolved flow and appear as a
        ! spurious peak velocity.  Apply the standard Kurganov--Petrova
        ! desingularization only in granular modes, below a mesh-dependent
        ! shallow-depth scale, and only where the local bed is not affine.
        ! Depth and momentum direction are preserved.  In particular, flat
        ! and constant-slope analytical Coulomb cells receive no
        ! regularization update.
        if (imodel_rh >= 1) then
            ! First classify the patch from stencils wholly inside it.  Ghost
            ! topography at a physical or AMR boundary is a boundary closure,
            ! not evidence of terrain curvature; using it for this decision
            ! can spuriously modify an otherwise affine analytical bed.
            patch_nonplanar = .false.
            if (mx >= 3 .and. my >= 3) then
                do j = 2, my-1
                    do i = 2, mx-1
                        if (locally_nonplanar_bed(aux(1,i,j), aux(1,i-1,j), &
                                                  aux(1,i+1,j), aux(1,i,j-1), &
                                                  aux(1,i,j+1), aux(1,i-1,j-1), &
                                                  aux(1,i+1,j-1), aux(1,i-1,j+1), &
                                                  aux(1,i+1,j+1))) then
                            patch_nonplanar = .true.
                            exit
                        end if
                    end do
                    if (patch_nonplanar) exit
                end do
            end if

            if (patch_nonplanar) then
                h_eps = max(dry_tolerance, &
                            min(2.d0*velocity_depth_threshold_rh, &
                                0.02d0*min(dx,dy)))
                do j = 1, my
                    do i = 1, mx
                        h = q(1,i,j)
                        if (h > dry_tolerance .and. h < h_eps .and. &
                            locally_nonplanar_bed(aux(1,i,j), aux(1,i-1,j), &
                                                  aux(1,i+1,j), aux(1,i,j-1), &
                                                  aux(1,i,j+1), aux(1,i-1,j-1), &
                                                  aux(1,i+1,j-1), aux(1,i-1,j+1), &
                                                  aux(1,i+1,j+1))) then
                            call regularized_velocity(h, q(2,i,j), q(3,i,j), &
                                                      h_eps, u, v)
                            q(2,i,j) = h*u
                            q(3,i,j) = h*v
                        end if
                    end do
                end do
            end if
        end if
    else
        ! Keep GeoClaw's standard no-friction dry-front protection.  This is
        ! essential for frictionless water benchmarks: a tiny wet cell can
        ! otherwise produce hu/h above the configured physical speed limit,
        ! overflow on the next step, and generate NaNs.
        do j = 1-mbc, my+mbc
            do i = 1-mbc, mx+mbc
                if (q(1,i,j) <= dry_tolerance) then
                    q(2,i,j) = 0.d0
                    q(3,i,j) = 0.d0
                else
                    speed = dsqrt(q(2,i,j)**2 + q(3,i,j)**2) / q(1,i,j)
                    if (speed > speed_limit) then
                        sratio = speed_limit / speed
                        q(2,i,j) = q(2,i,j) * sratio
                        q(3,i,j) = q(3,i,j) * sratio
                    end if
                end if
            end do
        end do
    end if

end subroutine src2
