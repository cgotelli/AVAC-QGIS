subroutine step2(maxm,meqn,maux,mbc,mx,my, &
                 qold,aux,dx,dy,dt,cflgrid, &
                 fm,fp,gm,gp,rpn2,rpt2)
!     ==========================================================
!
!     # clawpack routine ...  modified for AMRCLAW
!
!     # Take one time step, updating q.
!     # On entry, qold gives
!     #    initial data for this step
!     #    and is unchanged in this version.
!
!     # fm, fp are fluxes to left and right of single cell edge
!     # See the flux2 documentation for more information.
!
!     # modified again for GeoClaw
!------------------step2_geo.f-----------------------
!     The optional module-controlled path relimits outgoing correction
!     fluxes before the update in order to maintain depth positivity.
!     Its extended face stencil is enabled only by supported AVAC runs.
!------------last modified 12/30/04--------------------------
!

    use geoclaw_module, only: dry_tolerance, &
        relimit => use_fwave_positivity_limiter
    use amr_module, only: mwaves, mcapa

    implicit none
    
    external rpn2, rpt2
    
    ! Arguments
    integer, intent(in) :: maxm,meqn,maux,mbc,mx,my
    real(kind=8), intent(in) :: dx,dy,dt
    real(kind=8), intent(inout) :: cflgrid
    real(kind=8), intent(inout) :: qold(meqn, 1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(inout) :: aux(maux,1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(inout) :: fm(meqn, 1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(inout) :: fp(meqn,1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(inout) :: gm(meqn,1-mbc:mx+mbc, 1-mbc:my+mbc)
    real(kind=8), intent(inout) :: gp(meqn,1-mbc:mx+mbc, 1-mbc:my+mbc)

    ! Local storage for flux accumulation
    real(kind=8) :: faddm(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: faddp(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: gaddm(meqn,1-mbc:maxm+mbc,2)
    real(kind=8) :: gaddp(meqn,1-mbc:maxm+mbc,2)
    
    ! Scratch storage for Sweeps and Riemann problems
    real(kind=8) ::  q1d(meqn,1-mbc:maxm+mbc)
    real(kind=8) :: aux1(maux,1-mbc:maxm+mbc)
    real(kind=8) :: aux2(maux,1-mbc:maxm+mbc)
    real(kind=8) :: aux3(maux,1-mbc:maxm+mbc)
    real(kind=8) :: dtdx1d(1-mbc:maxm+mbc)
    real(kind=8) :: dtdy1d(1-mbc:maxm+mbc)
    
 !   real(kind=8) ::  wave(meqn, mwaves, 1-mbc:maxm+mbc)
 !   real(kind=8) ::     s(mwaves, 1-mbc:maxm + mbc)
 !   real(kind=8) ::  amdq(meqn,1-mbc:maxm + mbc)
 !   real(kind=8) ::  apdq(meqn,1-mbc:maxm + mbc)
!     real(kind=8) ::  cqxx(meqn,1-mbc:maxm + mbc)
!     real(kind=8) :: bmadq(meqn,1-mbc:maxm + mbc)
!     real(kind=8) :: bpadq(meqn,1-mbc:maxm + mbc)
    
    ! Looping scalar storage
    integer :: i,j,m,thread_num
    integer :: sweep_lo,sweep_pad,normal_lo,normal_pad,trans_lo,trans_pad
    real(kind=8) :: dtdx,dtdy,cfl1d,p,phi,cm,dtdxij,dtdyij
    logical :: out_left,out_right,out_bottom,out_top
    
    ! Common block storage
    integer :: icom,jcom

    cflgrid = 0.d0
    dtdx = dt/dx
    dtdy = dt/dy

    sweep_lo = 0
    sweep_pad = 1
    normal_lo = 1
    normal_pad = 1
    trans_lo = 1
    trans_pad = 1
    if (relimit) then
        if (mbc < 5) then
            print *, 'ERROR: f-wave positivity limiter requires mbc >= 5'
            stop
        end if
        sweep_lo = -1
        sweep_pad = 2
        normal_lo = 0
        normal_pad = 2
        trans_lo = 0
        trans_pad = 1
    end if
    
    fm = 0.d0
    fp = 0.d0
    gm = 0.d0
    gp = 0.d0

    ! ==========================================================================
    ! Perform X-Sweeps
    do j = sweep_lo,my+sweep_pad

        ! Copy old q into 1d slice
        q1d(:,1-mbc:mx+mbc) = qold(:,1-mbc:mx+mbc,j)
        
        ! Set dtdx slice if a capacity array exists
        if (mcapa > 0)  then
            dtdx1d(1-mbc:mx+mbc) = dtdx / aux(mcapa,1-mbc:mx+mbc,j)
        else
            dtdx1d = dtdx
        endif
        
        ! Copy aux array into slices
        if (maux > 0) then
            aux1(:,1-mbc:mx+mbc) = aux(:,1-mbc:mx+mbc,j-1)
            aux2(:,1-mbc:mx+mbc) = aux(:,1-mbc:mx+mbc,j  )
            aux3(:,1-mbc:mx+mbc) = aux(:,1-mbc:mx+mbc,j+1)
        endif
        
        ! Store value of j along the slice into common block
        ! *** WARNING *** This may not working with threading
        jcom = j

        ! Compute modifications fadd and gadd to fluxes along this slice:
        call flux2(1,maxm,meqn,maux,mbc,mx,q1d,dtdx1d,aux1,aux2,aux3, &
                   faddm,faddp,gaddm,gaddp,cfl1d,rpn2,rpt2) 

        cflgrid = max(cflgrid,cfl1d)
        ! write(53,*) 'x-sweep: ',cfl1d,cflgrid

        ! Update fluxes
        fm(:,normal_lo:mx+normal_pad,j) = &
            fm(:,normal_lo:mx+normal_pad,j) + &
            faddm(:,normal_lo:mx+normal_pad)
        fp(:,normal_lo:mx+normal_pad,j) = &
            fp(:,normal_lo:mx+normal_pad,j) + &
            faddp(:,normal_lo:mx+normal_pad)
        gm(:,trans_lo:mx+trans_pad,j) = gm(:,trans_lo:mx+trans_pad,j) + &
            gaddm(:,trans_lo:mx+trans_pad,1)
        gp(:,trans_lo:mx+trans_pad,j) = gp(:,trans_lo:mx+trans_pad,j) + &
            gaddp(:,trans_lo:mx+trans_pad,1)
        gm(:,trans_lo:mx+trans_pad,j+1) = &
            gm(:,trans_lo:mx+trans_pad,j+1) + &
            gaddm(:,trans_lo:mx+trans_pad,2)
        gp(:,trans_lo:mx+trans_pad,j+1) = &
            gp(:,trans_lo:mx+trans_pad,j+1) + &
            gaddp(:,trans_lo:mx+trans_pad,2)

    enddo

    ! ============================================================================
    !  y-sweeps    
    !
    do i = sweep_lo, mx+sweep_pad
        
        ! Copy data along a slice into 1d arrays:
        q1d(:,1-mbc:my+mbc) = qold(:,i,1-mbc:my+mbc)

        ! Set dt/dy ratio in slice
        if (mcapa > 0) then
            dtdy1d(1-mbc:my+mbc) = dtdy / aux(mcapa,i,1-mbc:my+mbc)
        else
            dtdy1d = dtdy
        endif

        ! Copy aux slices
        if (maux .gt. 0)  then
            aux1(:,1-mbc:my+mbc) = aux(:,i-1,1-mbc:my+mbc)
            aux2(:,1-mbc:my+mbc) = aux(:,i,1-mbc:my+mbc)
            aux3(:,1-mbc:my+mbc) = aux(:,i+1,1-mbc:my+mbc)
        endif
        
        ! Store the value of i along this slice in the common block
        ! *** WARNING *** This may not working with threading
        icom = i
        
        ! Compute modifications fadd and gadd to fluxes along this slice
        call flux2(2,maxm,meqn,maux,mbc,my,q1d,dtdy1d,aux1,aux2,aux3, &
                   faddm,faddp,gaddm,gaddp,cfl1d,rpn2,rpt2)

        cflgrid = max(cflgrid,cfl1d)
        ! write(53,*) 'y-sweep: ',cfl1d,cflgrid

        ! Update fluxes
        gm(:,i,normal_lo:my+normal_pad) = &
            gm(:,i,normal_lo:my+normal_pad) + &
            faddm(:,normal_lo:my+normal_pad)
        gp(:,i,normal_lo:my+normal_pad) = &
            gp(:,i,normal_lo:my+normal_pad) + &
            faddp(:,normal_lo:my+normal_pad)
        fm(:,i,trans_lo:my+trans_pad) = fm(:,i,trans_lo:my+trans_pad) + &
            gaddm(:,trans_lo:my+trans_pad,1)
        fp(:,i,trans_lo:my+trans_pad) = fp(:,i,trans_lo:my+trans_pad) + &
            gaddp(:,trans_lo:my+trans_pad,1)
        fm(:,i+1,trans_lo:my+trans_pad) = &
            fm(:,i+1,trans_lo:my+trans_pad) + &
            gaddm(:,trans_lo:my+trans_pad,2)
        fp(:,i+1,trans_lo:my+trans_pad) = &
            fp(:,i+1,trans_lo:my+trans_pad) + &
            gaddp(:,trans_lo:my+trans_pad,2)

    end do

    ! Relimit correction fluxes if they drive a cell negative
    if (relimit) then
        dtdxij = dtdx
        dtdyij = dtdy
        do i=0,mx+1
            do j=0,my+1
                if (mcapa > 0) then
                    dtdxij = dtdx / aux(mcapa,i,j)
                    dtdyij = dtdy / aux(mcapa,i,j)
                endif
                p = max(0.d0,dtdxij*fm(1,i+1,j)) + max(0.d0,dtdyij*gm(1,i,j+1)) &
                  - min(0.d0,dtdxij*fp(1,i,j)) - min(0.d0,dtdyij*gp(1,i,j))
                phi = min(1.d0,abs(qold(1,i,j) / (p+dry_tolerance)))

                if (phi < 1.d0) then
                    ! Capture every direction before component 1 changes.
                    ! Each face is owned by exactly one upwind mass donor;
                    ! positive scaling preserves that ownership.
                    out_left = fp(1,i,j) < 0.d0
                    out_bottom = gp(1,i,j) < 0.d0
                    out_right = fm(1,i+1,j) > 0.d0
                    out_top = gm(1,i,j+1) > 0.d0
                    do m=1,meqn
                        if (out_left) then
                            cm = fp(m,i,j) - fm(m,i,j)
                            fm(m,i,j) = phi * fm(m,i,j)
                            fp(m,i,j) = fm(m,i,j) + cm
                        endif
                        if (out_bottom) then
                            cm = gp(m,i,j) - gm(m,i,j)
                            gm(m,i,j) = phi * gm(m,i,j)
                            gp(m,i,j) = gm(m,i,j) + cm
                        endif
                        if (out_right) then
                            cm = fp(m,i+1,j) - fm(m,i+1,j)
                            fp(m,i+1,j) = phi * fp(m,i+1,j)
                            fm(m,i+1,j) = fp(m,i+1,j) - cm
                        endif
                        if (out_top) then
                            cm = gp(m,i,j+1) - gm(m,i,j+1)
                            gp(m,i,j+1) = phi * gp(m,i,j+1)
                            gm(m,i,j+1) = gp(m,i,j+1) - cm
                        endif
                    end do
                endif
            enddo
        enddo
    endif

end subroutine step2
