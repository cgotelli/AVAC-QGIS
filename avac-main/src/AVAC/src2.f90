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
    ! and Robl (2015) to gravity, normal stress, depth, and basal resistance.
    ! Before that frozen constitutive update, transport the post-flux velocity
    ! between its material departure and arrival terrain tangent planes. This
    ! separate geometric operation restores the changing-basis acceleration;
    ! it does not change the physical curvature contribution to basal stress.
    ! On a flat bed this is exactly the previous AVAC Coulomb/Voellmy source.
    !
    ! Closed-form update of dv/dt = -a - b*v^2, with a static-yield-aware
    ! zero-speed safeguard:
    !   speed_new = cartesian_speed_after(...)
    !   (hu)^{n+1} = (hu / speed) * speed_new
    !   (hv)^{n+1} = (hv / speed) * speed_new
    !
    ! Voellmy honors a zero of the frozen source update even on a super-yield
    ! bed: that is a transient split-source stop, not permanent static yield.
    ! The next flux step supplies the bed/pressure-driven direction. Coulomb
    ! retains its existing static-yield-dependent stopping compatibility path.

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
    real(kind=8) :: h, hu, hv, u, v, speed, speed_new, sratio
    real(kind=8) :: dzdx, dzdy, d2zdx2, d2zdxdy, d2zdy2, theta_local
    real(kind=8) :: tau_driving_rho, tau_static_rho
    real(kind=8) :: mu_local, xi_local, C_local   ! altitude-zoned rheology (from get_mu_xi)
    real(kind=8) :: coeff, gamma
    logical :: at_rest

    ! Geometry is kinematic, not a friction option.  Water retains GeoClaw's
    ! original horizontal shallow-water equations. All granular constitutive
    ! laws receive the same terrain transport, including frictionless runs.
    if (imodel_rh >= 1 .and. dt > 0.d0) then
        call terrain_momentum_transport(meqn,mbc,mx,my,maux,xlower,ylower,dx,dy,q,aux,dry_tolerance,dt)
    end if

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
                        ! Closed-form source update.  Unlike forward Euler,
                        ! this gives the same accumulated local
                        ! Voellmy drag when AMR subcycling changes dt.
                        ! Voellmy's quadratic drag becomes stiff as h decreases.
                        ! Never discard that integrated impulse just because the
                        ! split source reaches zero on a super-yield bed. Such a
                        ! transient stop is distinct from a static equilibrium;
                        ! the Riemann update still owns gravity/pressure driving.
                        ! Keep the legacy pure-Coulomb stopping branch unchanged.
                        speed_new = cartesian_speed_after(speed, dt, h, u, v, &
                                                         dzdx, dzdy, d2zdx2, &
                                                         d2zdxdy, d2zdy2, mu_local, &
                                                         xi_local, C_local, rho_rh, &
                                                         g, imodel_rh)
                        if (speed_new > 0.d0) then
                            q(2,i,j) = hu * speed_new / speed
                            q(3,i,j) = hv * speed_new / speed
                        else if (imodel_rh >= 2 .or. tau_driving_rho <= tau_static_rho) then
                            ! A zero vector needs no arbitrary velocity direction.
                            ! For Voellmy this also admits transient source stops;
                            ! only sub-yield states can remain at static rest.
                            q(2,i,j) = 0.d0
                            q(3,i,j) = 0.d0
                        else
                            ! The scalar, split source update has reached
                            ! zero, but a super-yield bed cannot remain at
                            ! rest.  There is no unique map-plane direction
                            ! to assign at zero speed, and this source step
                            ! does not own the Riemann bed-slope drive.
                            ! Keep the incoming momentum; the coupled flux
                            ! update supplies the resolved driving direction.
                        end if
                    end if
                end if
            end do
        end do

        ! No timestep-independent projection of cell-average momentum.
        ! Shallow stabilization is applied to conservative flux corrections.
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

! Complete horizontal conservative flux transport on a resolved terrain graph.
! For z=B(x,y), constrained motion has connection acceleration
!   a_geo = -grad(B) * (u^T Hess(B) u) / (1 + |grad(B)|^2).
! A finite minimal rotation of the tangent velocity has this differential
! limit without the pole of a frozen quadratic acceleration update.  Its
! departure gradient uses a first-order material backtrace over the accepted
! Godunov time step; rejected preflight trials never reach this routine.
!
! Ghost topography inside the physical domain is genuine neighboring terrain,
! including at AMR/tile interfaces. Discarding it would make geometry depend
! on arbitrary patch partitioning. Only exclude exterior physical closures;
! periodically wrapped ghosts also remain genuine terrain. Extend the nearest
! valid quadratic gradient only where a physical exterior prevents centering.
! One physically resolved sample implies extrusion; two resolve a first
! derivative (and a mixed derivative when both axes have two); three resolve
! the corresponding pure second derivative. Patch width is not domain width.
subroutine terrain_momentum_transport(meqn,mbc,mx,my,maux,xlower,ylower,dx,dy,q,aux,h_dry,dt)
    use rheology_module, only: terrain_tangent_transport
    use amr_module, only: domain_xlower => xlower, domain_xupper => xupper, &
                          domain_ylower => ylower, domain_yupper => yupper, &
                          xperdom, yperdom
    implicit none
    integer, intent(in) :: meqn,mbc,mx,my,maux
    real(kind=8), intent(in) :: xlower,ylower,dx,dy,h_dry,dt
    real(kind=8), intent(inout) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8), intent(in) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)
    integer :: i,j,ii,jj,iw,ie,js,jn,ilo,ihi,jlo,jhi,nx_valid,ny_valid
    real(kind=8) :: bx,by,bxx,bxy,byy,bc,bed_scale,relief,tolerance,residual
    real(kind=8) :: u,v,un,vn,h,departure_bx,departure_by,offset_x,offset_y

    if (dt <= 0.d0 .or. dx <= 0.d0 .or. dy <= 0.d0) return
    ilo=1-mbc
    ihi=mx+mbc
    jlo=1-mbc
    jhi=my+mbc
    ! src2 receives the patch's INTERIOR lower corner; all aligned levels
    ! have integer offsets to the domain edge. NINT removes coordinate
    ! roundoff without moving an actually exterior cell into the stencil.
    if (.not. xperdom) then
        ilo=max(ilo,1+nint((domain_xlower-xlower)/dx))
        ihi=min(ihi,nint((domain_xupper-xlower)/dx))
    end if
    if (.not. yperdom) then
        jlo=max(jlo,1+nint((domain_ylower-ylower)/dy))
        jhi=min(jhi,nint((domain_yupper-ylower)/dy))
    end if
    nx_valid=ihi-ilo+1
    ny_valid=jhi-jlo+1
    if (nx_valid < 1 .or. ny_valid < 1) return
    do j=1,my
        jj=j
        if (ny_valid >= 3) jj=max(jlo+1,min(jhi-1,j))
        js=max(jlo,jj-1)
        jn=min(jhi,jj+1)
        do i=1,mx
            h=q(1,i,j)
            if (h <= h_dry) cycle
            if (q(2,i,j) == 0.d0 .and. q(3,i,j) == 0.d0) cycle
            ii=i
            if (nx_valid >= 3) ii=max(ilo+1,min(ihi-1,i))
            iw=max(ilo,ii-1)
            ie=min(ihi,ii+1)
            bc=aux(1,ii,jj)
            bed_scale=max(1.d0,maxval(abs(aux(1,iw:ie,js:jn))))
            relief=maxval(abs(aux(1,iw:ie,js:jn)-bc))
            tolerance=max(1.d-12*max(1.d0,relief),64.d0*epsilon(1.d0)*bed_scale)
            bx=0.d0
            by=0.d0
            bxx=0.d0
            bxy=0.d0
            byy=0.d0
            residual=0.d0
            if (nx_valid >= 2) bx=(aux(1,ie,jj)-aux(1,iw,jj))/(real(ie-iw,8)*dx)
            if (ny_valid >= 2) by=(aux(1,ii,jn)-aux(1,ii,js))/(real(jn-js,8)*dy)
            if (nx_valid >= 3) then
                bxx=(aux(1,ie,jj)-bc)+(aux(1,iw,jj)-bc)
                residual=max(residual,abs(bxx))
                bxx=bxx/dx**2
            end if
            if (ny_valid >= 3) then
                byy=(aux(1,ii,jn)-bc)+(aux(1,ii,js)-bc)
                residual=max(residual,abs(byy))
                byy=byy/dy**2
            end if
            if (nx_valid >= 2 .and. ny_valid >= 2) then
                bxy=((aux(1,ie,jn)-bc)-(aux(1,iw,jn)-bc))- &
                    ((aux(1,ie,js)-bc)-(aux(1,iw,js)-bc))
                residual=max(residual,abs(bxy))
                bxy=bxy/(real((ie-iw)*(jn-js),8)*dx*dy)
            end if
            ! Exact identity for affine terrain, including arithmetic noise
            ! from large stored elevations: do not even reconstruct momentum.
            if (residual <= tolerance) cycle
            offset_x=real(i-ii,8)*dx
            offset_y=real(j-jj,8)*dy
            bx=bx+bxx*offset_x+bxy*offset_y
            by=by+bxy*offset_x+byy*offset_y
            u=q(2,i,j)/h
            v=q(3,i,j)/h
            departure_bx=bx-dt*(bxx*u+bxy*v)
            departure_by=by-dt*(bxy*u+byy*v)
            call terrain_tangent_transport(u,v,departure_bx,departure_by,bx,by,un,vn)
            q(2,i,j)=h*un
            q(3,i,j)=h*vn
        end do
    end do
end subroutine terrain_momentum_transport
