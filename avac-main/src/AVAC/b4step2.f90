! ============================================
subroutine b4step2(mbc, mx, my, meqn, q, xlower, ylower, dx, dy, t, dt, &
                   maux, aux, actualstep)
! ============================================
!
! Called before each call to step2 on a given AMR level.
!
! This local version extends the standard GeoClaw b4step2.f90 with:
!   1. Store dx/dy in rheology_module for the D-Claw static yield check
!      performed in rpn2_geoclaw.f.
!   2. Refresh aux(2), the cell-centred two-dimensional static-yield ratio
!      consumed by the directional Riemann sweeps.  The solver is Cartesian;
!      aux(1) remains the fixed bed and aux(2) is transient solver scratch.
!
! The interface decision itself remains in rpn2_geoclaw.f, following D-Claw
! (George & Iverson 2014).  The full free-surface gradient must be formed
! here because a normal Riemann problem receives only a one-dimensional slice.
!
! Mass monitoring is handled on the Python side (module_avac.make_output)
! by reading fort.q files after each output frame.  This avoids the
! AMR multi-patch / OpenMP threading issues that arise in b4step2.

    use geoclaw_module, only: dry_tolerance, coordinate_system
    use geoclaw_module, only: g => grav
    use geoclaw_module, only: speed_limit
    use topo_module, only: num_dtopo, topotime
    use topo_module, only: aux_finalized
    use topo_module, only: xlowdtopo, xhidtopo, ylowdtopo, yhidtopo

    use amr_module, only: xlowdomain => xlower
    use amr_module, only: ylowdomain => ylower
    use amr_module, only: xhidomain => xupper
    use amr_module, only: yhidomain => yupper
    use amr_module, only: xperdom, yperdom, spheredom, NEEDS_TO_BE_SET
    use amr_module, only: outunit

    use storm_module, only: set_storm_fields

    ! Store current grid spacings for the D-Claw static yield check in rpn2
    use rheology_module, only: dx_avac, dy_avac, dt_avac, rho_rh, imodel_rh
    use rheology_module, only: get_mu_xi, static_yield_ratio_2d

    implicit none

    ! Subroutine arguments
    integer, intent(in) :: meqn
    integer, intent(inout) :: mbc, mx, my, maux
    real(kind=8), intent(inout) :: xlower, ylower, dx, dy, t, dt
    real(kind=8), intent(inout) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8), intent(inout) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
    logical, intent(in) :: actualstep

    ! Local variables
    integer :: i, j
    real(kind=8) :: h, s, sratio, mu_cell, xi_cell, C_cell
    real(kind=8) :: eta_w, eta_e, eta_s, eta_n

    ! Store grid spacings for use in rpn2_geoclaw.f (D-Claw yield check)
    dx_avac = dx
    dy_avac = dy
    dt_avac = dt

    ! Check for NaNs in the solution
    call check4nans(meqn, mbc, mx, my, q, t, 1)

    ! A dry state is defined consistently with rpn2_geoclaw: h <=
    ! dry_tolerance.  Leaving momentum in a cell exactly at the tolerance
    ! creates an arbitrarily large hu/h or hv/h.  It is particularly visible
    ! at same-level patch interfaces, where roundoff can leave h equal to the
    ! threshold after a wet/dry Riemann update and spuriously restart an
    ! otherwise arrested Coulomb deposit.
    forall(i=1-mbc:mx+mbc, j=1-mbc:my+mbc, q(1,i,j) <= dry_tolerance)
        q(1,i,j) = max(q(1,i,j), 0.d0)
        q(2:3,i,j) = 0.d0
    end forall

    ! Check for fluid speed sqrt(u**2 + v**2) > speed_limit
    ! and reset by scaling (u,v) down to this value (preserving direction)
    do j = 1-mbc, my+mbc
        do i = 1-mbc, mx+mbc
            if (q(1,i,j) > 0.d0) then
                s = sqrt((q(2,i,j)**2 + q(3,i,j)**2)) / q(1,i,j)
                if (s > speed_limit) then
                    sratio = speed_limit / s
                    q(2,i,j) = q(2,i,j) * sratio
                    q(3,i,j) = q(3,i,j) * sratio
                endif
            endif
        enddo
    enddo

    if (aux_finalized < 2 .and. actualstep) then
        aux(1,:,:) = NEEDS_TO_BE_SET
        call setaux(mbc, mx, my, xlower, ylower, dx, dy, maux, aux)
    endif

    if (actualstep) then
        call set_storm_fields(maux, mbc, mx, my, xlower, ylower, dx, dy, t, aux)
    end if

    ! On AVAC's Cartesian grid aux(2) is a deliberately transient marker
    ! rather than a physical field.  A negative value means "do not statically
    ! suppress this interface".  It is the conservative default for dry cells,
    ! grid-edge cells without a complete centred stencil, and legacy
    ! hand-written runs that omit the extra AVAC auxiliary variable.  Do not
    ! touch aux(2) in a non-Cartesian GeoClaw configuration: it is then the
    ! framework capacity field rather than AVAC scratch storage.
    !
    ! The extra field is needed because rpn2 is called separately in x and y
    ! with only one line of q.  Comparing its normal increment to mu in each
    ! sweep used to arrest a diagonal state with, for example, eta_x=eta_y=0.4
    ! and mu=0.5 even though ||grad eta||=0.566>mu.  Requiring the marker to
    ! be <= 1 adds the full vector Coulomb condition while retaining rpn2's
    ! established normal minmod/span and exact-rest checks.
    if (maux >= 2 .and. coordinate_system == 1) then
        aux(2,:,:) = -1.d0
        if (imodel_rh >= 1) then
            do j = 2-mbc, my+mbc-1
                do i = 2-mbc, mx+mbc-1
                    h = q(1,i,j)
                    if (h <= dry_tolerance) cycle

                    eta_w = q(1,i-1,j) + aux(1,i-1,j)
                    eta_e = q(1,i+1,j) + aux(1,i+1,j)
                    eta_s = q(1,i,j-1) + aux(1,i,j-1)
                    eta_n = q(1,i,j+1) + aux(1,i,j+1)
                    call get_mu_xi(aux(1,i,j), mu_cell, xi_cell, C_cell)
                    aux(2,i,j) = static_yield_ratio_2d(h, eta_w, eta_e, eta_s, &
                                                        eta_n, aux(1,i-1,j), &
                                                        aux(1,i+1,j), aux(1,i,j-1), &
                                                        aux(1,i,j+1), dx, dy, mu_cell, &
                                                        C_cell, rho_rh, g, imodel_rh)
                end do
            end do
        end if
    end if

end subroutine b4step2
