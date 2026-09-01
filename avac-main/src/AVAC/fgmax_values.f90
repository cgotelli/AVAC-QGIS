subroutine fgmax_values(mx,my,meqn,mbc,maux,q,aux,dx,dy, &
                        xlower,ylower,i1,i2,j1,j2,values)

    ! AVAC-specific fgmax diagnostics.  Depth is recorded wherever GeoClaw
    ! considers the cell wet.  Velocity, momentum, and momentum flux are
    ! reported only when the depth exceeds the configured minimum depth for
    ! a meaningful cell-average velocity.  Immediately above that threshold,
    ! momentum/depth is desingularized smoothly following Kurganov--Petrova;
    ! the diagnostic becomes the exact momentum/depth velocity once the depth
    ! reaches four times the threshold.  AVAC advances horizontal momentum, while
    ! its physical terrain-tangent diagnostic speed is
    ! sqrt(u^2+v^2+w^2), with w=u*B_x+v*B_y.  This calculation only populates
    ! fixed-grid maximum diagnostics; it does not alter the conserved state.

    use fgmax_module
    use geoclaw_module, only: dry_tolerance
    use rheology_module, only: velocity_depth_threshold_rh

    implicit none
    integer, intent(in) :: mx,my,meqn,mbc,maux
    real(kind=8), intent(in) :: q(meqn, 1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(in) :: aux(maux, 1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(in) :: dx,dy,xlower,ylower
    integer, intent(in) :: i1,i2,j1,j2
    real(kind=8), intent(inout) :: values(FG_NUM_VAL, &
                                           1-mbc:mx+mbc, 1-mbc:my+mbc)

    real(kind=8) :: velocity_depth, transition_depth
    real(kind=8) :: h4, transition_h4, denominator
    real(kind=8) :: u, v, dzdx, dzdy, w
    integer :: i,j

    if ((FG_NUM_VAL.ne.1) .and. (FG_NUM_VAL.ne.2) .and. &
        (FG_NUM_VAL.ne.5)) then
        write(6,*) '*** Error -- expecting FG_NUM_VAL = 1, 2, or 5'
        write(6,*) '***   in AVAC fgmax_values, found ', FG_NUM_VAL
        stop
    end if

    velocity_depth = max(dry_tolerance, velocity_depth_threshold_rh)
    transition_depth = 4.d0 * velocity_depth
    transition_h4 = transition_depth**4

    do i=i1,i2
        do j=j1,j2
            values(1,i,j) = q(1,i,j)
            if (FG_NUM_VAL > 1) then
                if (q(1,i,j) > velocity_depth) then
                    h4 = q(1,i,j)**4
                    denominator = sqrt(h4 + max(h4, transition_h4))
                    u = sqrt(2.d0) * q(1,i,j) * q(2,i,j) / denominator
                    v = sqrt(2.d0) * q(1,i,j) * q(3,i,j) / denominator
                    dzdx = (aux(1,i+1,j) - aux(1,i-1,j)) / (2.d0*dx)
                    dzdy = (aux(1,i,j+1) - aux(1,i,j-1)) / (2.d0*dy)
                    w = u*dzdx + v*dzdy
                    values(2,i,j) = sqrt(u**2 + v**2 + w**2)
                else
                    values(2,i,j) = 0.d0
                end if
            end if
            if (FG_NUM_VAL > 2) then
                values(3,i,j) = q(1,i,j)*values(2,i,j)
                values(4,i,j) = values(3,i,j)*values(2,i,j)
                values(5,i,j) = -q(1,i,j)
            end if
        end do
    end do

end subroutine fgmax_values
