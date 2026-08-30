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
!
! The static Coulomb yield check (stopping criterion) is handled entirely
! in rpn2_geoclaw.f, following D-Claw (George & Iverson 2014).
!
! Mass monitoring is handled on the Python side (module_avac.make_output)
! by reading fort.q files after each output frame.  This avoids the
! AMR multi-patch / OpenMP threading issues that arise in b4step2.

    use geoclaw_module, only: dry_tolerance
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
    use rheology_module, only: dx_avac, dy_avac, dt_avac, imodel_rh, &
                               velocity_depth_threshold_rh, &
                               regularized_velocity

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
    real(kind=8) :: h, s, sratio, u, v, h_eps

    ! Store grid spacings for use in rpn2_geoclaw.f (D-Claw yield check)
    dx_avac = dx
    dy_avac = dy
    dt_avac = dt
    h_eps = max(dry_tolerance, &
                min(2.d0 * velocity_depth_threshold_rh, &
                    0.02d0 * min(dx, dy)))

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
                if (imodel_rh >= 1 .and. q(1,i,j) > dry_tolerance) then
                    call regularized_velocity(q(1,i,j), q(2,i,j), &
                                               q(3,i,j), h_eps, u, v)
                    q(2,i,j) = q(1,i,j) * u
                    q(3,i,j) = q(1,i,j) * v
                end if
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

end subroutine b4step2
