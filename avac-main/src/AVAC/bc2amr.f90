! GeoClaw AMR boundary routine with data-driven hydraulic user boundaries.
!
! AVAC uses a one-way (diode) form of the standard extrapolation boundary
! (mthbc=1).  An outward state is copied exactly, retaining GeoClaw's usual
! zero-gradient outflow.  If the adjacent normal momentum points inward, its
! ghost-cell sign is reflected so that the boundary Riemann problem has zero
! normal mass flux.  This prevents the copied ghost state from becoming an
! infinite external avalanche reservoir without changing a genuine outflow.
subroutine bc2amr(val,aux,nrow,ncol,meqn,naux,hx,hy,level,time, &
                  xlo_patch,xhi_patch,ylo_patch,yhi_patch)

    use amr_module, only: mthbc, xlower, ylower, xupper, yupper
    use amr_module, only: xperdom, yperdom, spheredom
    use hydraulic_bc_module, only: apply_hydraulic_bc

    implicit none
    integer, intent(in) :: nrow,ncol,meqn,naux,level
    real(kind=8), intent(in) :: hx,hy,time,xlo_patch,xhi_patch
    real(kind=8), intent(in) :: ylo_patch,yhi_patch
    real(kind=8), intent(inout) :: val(meqn,nrow,ncol)
    real(kind=8), intent(inout) :: aux(naux,nrow,ncol)
    integer :: i,j,ibeg,jbeg,nxl,nxr,nyb,nyt
    real(kind=8) :: hxmarg,hymarg

    hxmarg = hx*0.01d0
    hymarg = hy*0.01d0
    if (xperdom .and. (yperdom .or. spheredom)) return

    ! West boundary.
    if (xlo_patch < xlower-hxmarg) then
        nxl = int((xlower+hxmarg-xlo_patch)/hx)
        select case(mthbc(1))
        case(0)
            call apply_hydraulic_bc(1,val,aux,nrow,ncol,meqn,naux, &
                                    hx,hy,xlo_patch,ylo_patch,nxl)
        case(1)
            do j=1,ncol; do i=1,nxl
                aux(:,i,j)=aux(:,nxl+1,j); val(:,i,j)=val(:,nxl+1,j)
                if (val(2,nxl+1,j) > 0.d0) val(2,i,j)=-val(2,nxl+1,j)
            end do; end do
        case(2)
            continue
        case(3)
            do j=1,ncol; do i=1,nxl
                aux(:,i,j)=aux(:,2*nxl+1-i,j)
                val(:,i,j)=val(:,2*nxl+1-i,j)
                val(2,i,j)=-val(2,i,j)
            end do; end do
        case(4)
            continue
        case default
            stop 'Invalid west boundary condition.'
        end select
    end if

    ! East boundary.
    if (xhi_patch > xupper+hxmarg) then
        nxr = int((xhi_patch-xupper+hxmarg)/hx)
        ibeg = max(nrow-nxr+1,1)
        select case(mthbc(2))
        case(0)
            call apply_hydraulic_bc(2,val,aux,nrow,ncol,meqn,naux, &
                                    hx,hy,xlo_patch,ylo_patch,nxr)
        case(1)
            do i=ibeg,nrow; do j=1,ncol
                aux(:,i,j)=aux(:,ibeg-1,j); val(:,i,j)=val(:,ibeg-1,j)
                if (val(2,ibeg-1,j) < 0.d0) val(2,i,j)=-val(2,ibeg-1,j)
            end do; end do
        case(2)
            continue
        case(3)
            do i=ibeg,nrow; do j=1,ncol
                aux(:,i,j)=aux(:,2*ibeg-1-i,j)
                val(:,i,j)=val(:,2*ibeg-1-i,j)
                val(2,i,j)=-val(2,i,j)
            end do; end do
        case(4)
            continue
        case default
            stop 'Invalid east boundary condition.'
        end select
    end if

    ! South boundary.
    if (ylo_patch < ylower-hymarg) then
        nyb = int((ylower+hymarg-ylo_patch)/hy)
        select case(mthbc(3))
        case(0)
            call apply_hydraulic_bc(3,val,aux,nrow,ncol,meqn,naux, &
                                    hx,hy,xlo_patch,ylo_patch,nyb)
        case(1)
            do j=1,nyb; do i=1,nrow
                aux(:,i,j)=aux(:,i,nyb+1); val(:,i,j)=val(:,i,nyb+1)
                if (val(3,i,nyb+1) > 0.d0) val(3,i,j)=-val(3,i,nyb+1)
            end do; end do
        case(2)
            continue
        case(3)
            do j=1,nyb; do i=1,nrow
                aux(:,i,j)=aux(:,i,2*nyb+1-j)
                val(:,i,j)=val(:,i,2*nyb+1-j)
                val(3,i,j)=-val(3,i,j)
            end do; end do
        case(4)
            continue
        case default
            stop 'Invalid south boundary condition.'
        end select
    end if

    ! North boundary.
    if (yhi_patch > yupper+hymarg) then
        nyt = int((yhi_patch-yupper+hymarg)/hy)
        jbeg = max(ncol-nyt+1,1)
        select case(mthbc(4))
        case(0)
            call apply_hydraulic_bc(4,val,aux,nrow,ncol,meqn,naux, &
                                    hx,hy,xlo_patch,ylo_patch,nyt)
        case(1)
            do j=jbeg,ncol; do i=1,nrow
                aux(:,i,j)=aux(:,i,jbeg-1); val(:,i,j)=val(:,i,jbeg-1)
                if (val(3,i,jbeg-1) < 0.d0) val(3,i,j)=-val(3,i,jbeg-1)
            end do; end do
        case(2)
            continue
        case(3)
            do j=jbeg,ncol; do i=1,nrow
                aux(:,i,j)=aux(:,i,2*jbeg-1-j)
                val(:,i,j)=val(:,i,2*jbeg-1-j)
                val(3,i,j)=-val(3,i,j)
            end do; end do
        case(4)
            continue
        case default
            stop 'Invalid north boundary condition.'
        end select
    end if

end subroutine bc2amr
