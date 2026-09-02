c======================================================================
       subroutine rpn2(ixy,maxm,meqn,mwaves,maux,mbc,mx,
     &                 ql,qr,auxl,auxr,fwave,s,amdq,apdq)
c======================================================================
c
c Solves normal Riemann problems for the 2D SHALLOW WATER equations
c     with topography:
c     #        h_t + (hu)_x + (hv)_y = 0                           #
c     #        (hu)_t + (hu^2 + 0.5gh^2)_x + (huv)_y = -ghb_x      #
c     #        (hv)_t + (huv)_x + (hv^2 + 0.5gh^2)_y = -ghb_y      #
c
c Modified from the standard GeoClaw rpn2_geoclaw.f to add a D-Claw
c static Coulomb yield check (George & Iverson 2014, J. Geophys. Res.).
c Once every cell in the local four-cell stencil can reach rest under the
c current exact friction impulse, the limited normal free-surface gradient
c is tested against Coulomb yield.  A cell-centred two-dimensional yield
c ratio, precomputed in b4step2 and passed in aux(2), must also be below one.
c This avoids falsely arresting a diagonal state whose two individual sweep
c increments are sub-yield but whose vector free-surface gradient is not.
c Below yield, the set-valued static friction balances the interface force
c and both mass and momentum waves are set to zero.  The depth states are
c not changed.  This remains a directional f-wave update with a 2D eligibility
c guard, not a monolithic two-dimensional complementarity solve.
c
c Requires:
c   rheology_module : dx_avac, dy_avac  (set by b4step2.f90)
c   rheology_module: rho_rh, imodel_rh and get_mu_xi (set by setprob.f90)
c   aux(1)           : fixed bed elevation
c   aux(2)           : cell-centred 2D static-yield ratio (AVAC Cartesian)

      use geoclaw_module, only: g => grav, drytol => dry_tolerance, rho
      use geoclaw_module, only: earth_radius, deg2rad, coordinate_system
      use amr_module, only: mcapa

      use storm_module, only: pressure_forcing, pressure_index

      use rheology_module, only: dx_avac, dy_avac, dt_avac, rho_rh,
     &                           imodel_rh, get_mu_xi,
     &                           friction_speed_after

      implicit none

      !input
      integer maxm,meqn,maux,mwaves,mbc,mx,ixy

      double precision  fwave(meqn, mwaves, 1-mbc:maxm+mbc)
      double precision  s(mwaves, 1-mbc:maxm+mbc)
      double precision  ql(meqn, 1-mbc:maxm+mbc)
      double precision  qr(meqn, 1-mbc:maxm+mbc)
      double precision  apdq(meqn,1-mbc:maxm+mbc)
      double precision  amdq(meqn,1-mbc:maxm+mbc)
      double precision  auxl(maux,1-mbc:maxm+mbc)
      double precision  auxr(maux,1-mbc:maxm+mbc)

      !local only
      integer m,i,mw,maxiter,mu,nv
      double precision wall(3)
      double precision fw(meqn,3)
      double precision sw(3)

      double precision hR,hL,huR,huL,uR,uL,hvR,hvL,vR,vL,phiR,phiL,pL,pR
      double precision bR,bL,sL,sR,sRoe1,sRoe2,sE1,sE2,uhat,chat
      double precision s1m,s2m
      double precision hstar,hstartest,hstarHLL,sLtest,sRtest
      double precision tw,dxdc

      logical rare1,rare2

      ! Rheological parameters for the D-Claw static yield check.
      double precision mu_rp, xi_rp, C_rp

      ! Local variables for the static yield check
      double precision dh_n, dh_span, db_n, dx_n, costh_n
      double precision thresh_n, h_avg_n
      double precision spd_LL, spd_L, spd_R, spd_RR
      double precision h_LL, h_RR, hu_stencil, hv_stencil
      double precision speed_after_L, speed_after_R
      double precision speed_after_LL, speed_after_RR
      double precision eta_LL, eta_Lc, eta_Rc, eta_RR
      double precision deta_L, deta_C, deta_R, slope_eta_L, slope_eta_R
      logical stops_LL, stops_L, stops_R, stops_RR
      logical rests_LL, rests_L, rests_R, rests_RR
      logical yield_ok_LL, yield_ok_L, yield_ok_R, yield_ok_RR

      ! In case there is no pressure forcing
      pL = 0.d0
      pR = 0.d0

      ! initialize all components to 0
      fw(:,:) = 0.d0
      fwave(:,:,:) = 0.d0
      s(:,:) = 0.d0
      amdq(:,:) = 0.d0
      apdq(:,:) = 0.d0

      !loop through Riemann problems at each grid cell
      do i=2-mbc,mx+mbc

!-----------------------Initializing-----------------------------------
         !inform of a bad riemann problem from the start
         if((qr(1,i-1).lt.0.d0).or.(ql(1,i) .lt. 0.d0)) then
            write(*,*) 'Negative input: hl,hr,i=',qr(1,i-1),ql(1,i),i
         endif


c        !set normal direction
         if (ixy.eq.1) then
            mu=2
            nv=3
         else
            mu=3
            nv=2
         endif

         !zero (small) negative values if they exist
         if (qr(1,i-1).lt.0.d0) then
               qr(1,i-1)=0.d0
               qr(2,i-1)=0.d0
               qr(3,i-1)=0.d0
         endif

         if (ql(1,i).lt.0.d0) then
               ql(1,i)=0.d0
               ql(2,i)=0.d0
               ql(3,i)=0.d0
         endif

         !skip problem if in a completely dry area
         if (qr(1,i-1) <= drytol .and. ql(1,i) <= drytol) then
            go to 30
         endif

         !Riemann problem variables
         hL = qr(1,i-1)
         hR = ql(1,i)
         huL = qr(mu,i-1)
         huR = ql(mu,i)
         bL = auxr(1,i-1)
         bR = auxl(1,i)
         if (pressure_forcing) then
             pL = auxr(pressure_index, i-1)
             pR = auxl(pressure_index, i)
         end if

         hvL=qr(nv,i-1)
         hvR=ql(nv,i)

         !check for wet/dry boundary
         if (hR.gt.drytol) then
            uR=huR/hR
            vR=hvR/hR
            phiR = 0.5d0*g*hR**2 + huR**2/hR
         else
            hR = 0.d0
            huR = 0.d0
            hvR = 0.d0
            uR = 0.d0
            vR = 0.d0
            phiR = 0.d0
         endif

         if (hL.gt.drytol) then
            uL=huL/hL
            vL=hvL/hL
            phiL = 0.5d0*g*hL**2 + huL**2/hL
         else
            hL=0.d0
            huL=0.d0
            hvL=0.d0
            uL=0.d0
            vL=0.d0
            phiL = 0.d0
         endif

         wall(1) = 1.d0
         wall(2) = 1.d0
         wall(3) = 1.d0

c        aux(2) is the cell-centred full-vector static-yield ratio prepared
c        by b4step2.  A missing, dry, or otherwise invalid marker is negative
c        and deliberately disables static interface suppression.  Do not fall
c        back to the old component-wise test for maux=1: allowing a flux is
c        conservative, whereas falsely pinning a diagonal super-yield state is
c        not.  ql/qr can differ in direct Riemann calls, so use the marker of
c        the corresponding state rather than an average.
         yield_ok_L = .false.
         yield_ok_R = .false.
         if (maux .ge. 2 .and. coordinate_system .eq. 1) then
            if (auxr(2,i-1) .ge. 0.d0 .and.
     &          auxr(2,i-1) .le. 1.d0) yield_ok_L = .true.
            if (auxl(2,i) .ge. 0.d0 .and.
     &          auxl(2,i) .le. 1.d0) yield_ok_R = .true.
         endif

c        ---- D-Claw yield check at wet/dry interface ----
c        When the wet cell is EXACTLY at rest (u=v=0, produced by the
c        floor-at-zero in src2.f90) and the free-surface head above the
c        dry bed is below the static Coulomb threshold, suppress inundation
c        (go to 30 = zero flux at this interface).
c        This prevents the deposit edge from spreading cell by cell into
c        adjacent dry terrain via the dam-break Riemann solution.
         if (imodel_rh .ge. 1) then
            call get_mu_xi(0.5d0*(bL+bR),mu_rp,xi_rp,C_rp)
            if (mu_rp .gt. 0.d0 .or. C_rp .gt. 0.d0) then
            if (ixy .eq. 1) then
               dx_n = dx_avac
            else
               dx_n = dy_avac
            endif
c           Right cell dry, left cell wet and exactly at rest
            if (hR .le. drytol .and. hL .gt. drytol .and.
     &          dsqrt(uL**2 + vL**2) .eq. 0.d0 .and.
     &          yield_ok_L) then
               dh_n     = max(0.d0, hL + bL - bR)
               db_n     = dabs(bR - bL)
               costh_n  = dx_n / dsqrt(dx_n**2 + db_n**2)
c              Threshold uses mu*dx (not mu*cos(theta)*dx) to match the
c              physical Coulomb condition tan(theta) > mu.  The SW equations
c              overestimate the driving force by 1/cos(theta) relative to
c              the true slope-parallel gravity component g*h*sin(theta);
c              removing costh_n compensates for this approximation.
               thresh_n = mu_rp * dx_n
c              Cohesion acts on the terrain-normal layer thickness.  AVAC
c              stores vertical depth, h_n=h*cos(theta), so the static head
c              increment is C/(rho*g*h*cos(theta)^2).  Apply the same rule
c              at either orientation of a wet/dry interface.
               if (imodel_rh .eq. 3 .and. rho_rh .gt. 0.d0 .and.
     &             C_rp .gt. 0.d0) then
                  thresh_n = thresh_n + C_rp/(rho_rh*g)
     &                       * dx_n/(hL*costh_n**2)
               endif
               if (dh_n .le. thresh_n) go to 30
            endif
c           Left cell dry, right cell wet and exactly at rest
            if (hL .le. drytol .and. hR .gt. drytol .and.
     &          dsqrt(uR**2 + vR**2) .eq. 0.d0 .and.
     &          yield_ok_R) then
               dh_n     = max(0.d0, hR + bR - bL)
               db_n     = dabs(bR - bL)
               costh_n  = dx_n / dsqrt(dx_n**2 + db_n**2)
               thresh_n = mu_rp * dx_n
               if (imodel_rh .eq. 3 .and. rho_rh .gt. 0.d0 .and.
     &             C_rp .gt. 0.d0) then
                  thresh_n = thresh_n + C_rp/(rho_rh*g)
     &                       * dx_n/(hR*costh_n**2)
               endif
               if (dh_n .le. thresh_n) go to 30
            endif
            endif
         endif
c        ---- end wet/dry yield check ----

         if (hR.le.drytol) then
            call riemanntype(hL,hL,uL,-uL,hstar,s1m,s2m,
     &                                  rare1,rare2,1,drytol,g)
            hstartest=max(hL,hstar)
            if (hstartest+bL.lt.bR) then
c                bR=hstartest+bL
               wall(2)=0.d0
               wall(3)=0.d0
               hR=hL
               huR=-huL
               bR=bL
               phiR=phiL
               uR=-uL
               vR=vL
            elseif (hL+bL.lt.bR) then
               bR=hL+bL
            endif
         elseif (hL.le.drytol) then
            call riemanntype(hR,hR,-uR,uR,hstar,s1m,s2m,
     &                                  rare1,rare2,1,drytol,g)
            hstartest=max(hR,hstar)
            if (hstartest+bR.lt.bL) then
c               bL=hstartest+bR
               wall(1)=0.d0
               wall(2)=0.d0
               hL=hR
               huL=-huR
               bL=bR
               phiL=phiR
               uL=-uR
               vL=vR
            elseif (hR+bR.lt.bL) then
               bL=hR+bR
            endif
         endif

c        ---- D-Claw static yield check (George & Iverson 2014) ----
c
c        Applied only when the wet local stencil is exactly at rest under
c        the current closed-form source update:
c          vnorm_new = friction_speed_after(vnorm,dt,...)
c        The classification uses the closed-form local source update, so no
c        user-selected stopping velocity (u_cr) is introduced.
c
c        The normal free-surface increments are compared with the static
c        Coulomb threshold mu*dx (plus the terrain-normal cohesion term).
c        In addition, the cell-centred 2D ratio |grad(h+b)|/yield_strength
c        must not exceed one for every available wet cell in the stencil.
c        If these necessary conditions hold, static friction balances the
c        interface force and both mass and momentum f-waves are zero.  The
c        depth states are deliberately not equalised: a stopped granular
c        deposit may retain a non-horizontal free surface, and averaging it
c        would itself cause unphysical mass creep.
         spd_L = dsqrt(uL**2 + vL**2)
         spd_R = dsqrt(uR**2 + vR**2)

         if (imodel_rh .ge. 1 .and.
     &       hL .gt. drytol .and. hR .gt. drytol) then

            call get_mu_xi(0.5d0*(bL+bR),mu_rp,xi_rp,C_rp)
            if (mu_rp .gt. 0.d0 .or. C_rp .gt. 0.d0) then

            speed_after_L = friction_speed_after(spd_L,dt_avac,hL,
     &           mu_rp,xi_rp,C_rp,rho_rh,g,imodel_rh)
            speed_after_R = friction_speed_after(spd_R,dt_avac,hR,
     &           mu_rp,xi_rp,C_rp,rho_rh,g,imodel_rh)
            stops_L = speed_after_L .le. 0.d0
            stops_R = speed_after_R .le. 0.d0
            rests_L = spd_L .eq. 0.d0
            rests_R = spd_R .eq. 0.d0

c           A static interface also requires the immediately adjacent cells
c           to stop during this step.  This prevents the yield limiter from
c           pinning the rear edge of a still-moving rarefaction merely
c           because the two reconstructed interface states happen to have
c           zero momentum.  Once the local four-cell stencil is genuinely
c           at rest, the same Coulomb complementarity condition suppresses
c           pressure-driven mass creep.  No empirical velocity threshold is
c           introduced: every test uses the exact dt*tau/(rho*h) impulse.
            stops_LL = .true.
            stops_RR = .true.
            rests_LL = .true.
            rests_RR = .true.
            yield_ok_LL = .true.
            yield_ok_RR = .true.
            if (i .ge. 3-mbc .and. i .le. mx+mbc-1) then
               h_LL = 0.5d0 * (ql(1,i-2) + qr(1,i-2))
               if (h_LL .gt. drytol) then
                  hu_stencil = 0.5d0 * (ql(2,i-2) + qr(2,i-2))
                  hv_stencil = 0.5d0 * (ql(3,i-2) + qr(3,i-2))
                  spd_LL = dsqrt(hu_stencil**2 + hv_stencil**2)
     &                   / h_LL
                  speed_after_LL = friction_speed_after(spd_LL,dt_avac,
     &                 h_LL,mu_rp,xi_rp,C_rp,rho_rh,g,imodel_rh)
                  stops_LL = speed_after_LL .le. 0.d0
                  rests_LL = spd_LL .eq. 0.d0
                  yield_ok_LL = .false.
                  if (maux .ge. 2 .and. coordinate_system .eq. 1) then
                     if (auxl(2,i-2) .ge. 0.d0 .and.
     &                   auxl(2,i-2) .le. 1.d0 .and.
     &                   auxr(2,i-2) .ge. 0.d0 .and.
     &                   auxr(2,i-2) .le. 1.d0) yield_ok_LL = .true.
                  endif
               endif
               h_RR = 0.5d0 * (ql(1,i+1) + qr(1,i+1))
               if (h_RR .gt. drytol) then
                  hu_stencil = 0.5d0 * (ql(2,i+1) + qr(2,i+1))
                  hv_stencil = 0.5d0 * (ql(3,i+1) + qr(3,i+1))
                  spd_RR = dsqrt(hu_stencil**2 + hv_stencil**2)
     &                   / h_RR
                  speed_after_RR = friction_speed_after(spd_RR,dt_avac,
     &                 h_RR,mu_rp,xi_rp,C_rp,rho_rh,g,imodel_rh)
                  stops_RR = speed_after_RR .le. 0.d0
                  rests_RR = spd_RR .eq. 0.d0
                  yield_ok_RR = .false.
                  if (maux .ge. 2 .and. coordinate_system .eq. 1) then
                     if (auxl(2,i+1) .ge. 0.d0 .and.
     &                   auxl(2,i+1) .le. 1.d0 .and.
     &                   auxr(2,i+1) .ge. 0.d0 .and.
     &                   auxr(2,i+1) .le. 1.d0) yield_ok_RR = .true.
                  endif
               endif
            endif

c           Retain both the local minmod slope and the centred gradient over
c           the four-cell Riemann stencil.  Minmod alone returns the smaller
c           one-sided increment and can hide a super-yield rarefaction just
c           downstream, temporarily isolating a static interface.  The span
c           gradient is (eta_RR-eta_LL)/(3*dx), a consistent derivative over
c           the same stencil rather than a maximum-gradient or fitted test.
            if (i .ge. 3-mbc .and. i .le. mx+mbc-1) then
               eta_LL = 0.5d0 * (ql(1,i-2) + qr(1,i-2)
     &                         + auxl(1,i-2) + auxr(1,i-2))
               eta_Lc = 0.5d0 * (ql(1,i-1) + qr(1,i-1)
     &                         + auxl(1,i-1) + auxr(1,i-1))
               eta_Rc = 0.5d0 * (ql(1,i) + qr(1,i)
     &                         + auxl(1,i) + auxr(1,i))
               eta_RR = 0.5d0 * (ql(1,i+1) + qr(1,i+1)
     &                         + auxl(1,i+1) + auxr(1,i+1))
               deta_L = eta_Lc - eta_LL
               deta_C = eta_Rc - eta_Lc
               deta_R = eta_RR - eta_Rc
               if (deta_L*deta_C .gt. 0.d0) then
                  slope_eta_L = dsign(min(dabs(deta_L),
     &                                      dabs(deta_C)),deta_L)
               else
                  slope_eta_L = 0.d0
               endif
               if (deta_C*deta_R .gt. 0.d0) then
                  slope_eta_R = dsign(min(dabs(deta_C),
     &                                      dabs(deta_R)),deta_C)
               else
                  slope_eta_R = 0.d0
               endif
               dh_n = max(dabs(slope_eta_L),dabs(slope_eta_R))
               dh_span = dabs(eta_RR - eta_LL) / 3.d0
            else
               dh_n = dabs((hR + bR) - (hL + bL))
               dh_span = dh_n
            endif
            db_n   = dabs(bR - bL)
            if (ixy .eq. 1) then
               dx_n = dx_avac
            else
               dx_n = dy_avac
            endif
c           cos(theta) at this interface: dx / sqrt(dx^2 + db^2)
            costh_n  = dx_n / dsqrt(dx_n**2 + db_n**2)
            h_avg_n  = 0.5d0 * (hL + hR)
c           Threshold uses mu*dx (not mu*cos(theta)*dx) to match the
c           physical Coulomb condition tan(theta) > mu.  The SW equations
c           overestimate the driving force by 1/cos(theta) relative to
c           the true slope-parallel gravity component g*h*sin(theta);
c           removing costh_n compensates for this approximation.
            thresh_n = mu_rp * dx_n
c           Cohesive Voellmy: use the same terrain-normal static balance as
c           the cell-centred source.  Since AVAC stores vertical depth, the
c           cohesive head-gradient contribution contains 1/cos(theta)^2.
            if (imodel_rh .eq. 3 .and. rho_rh .gt. 0.d0 .and.
     &          C_rp .gt. 0.d0) then
               thresh_n = thresh_n + C_rp/(rho_rh*g)
     &                    * dx_n/(h_avg_n*costh_n**2)
            endif
c           Below yield, set-valued static friction exactly cancels the
c           pressure/topography force, but only after the full local stencil
c           has actually reached rest.  A moving state that kinetic friction
c           is predicted to stop later in this step remains dynamic here;
c           otherwise a rarefaction can be pinned before its characteristic
c           crosses the interface.  The exact zero is produced by src2's
c           closed-form Coulomb update, so this adds no velocity threshold.
            if (stops_LL .and. stops_L .and.
     &          stops_R .and. stops_RR .and.
     &          rests_LL .and. rests_L .and.
     &          rests_R .and. rests_RR .and.
     &          yield_ok_LL .and. yield_ok_L .and.
     &          yield_ok_R .and. yield_ok_RR .and.
     &          dh_n .le. thresh_n .and.
     &          dh_span .le. thresh_n) go to 30
            endif
         endif
c        ---- end D-Claw static yield check ----

         !determine wave speeds
         sL=uL-sqrt(g*hL) ! 1 wave speed of left state
         sR=uR+sqrt(g*hR) ! 2 wave speed of right state

         uhat=(sqrt(g*hL)*uL + sqrt(g*hR)*uR)/(sqrt(g*hR)+sqrt(g*hL)) ! Roe average
         chat=sqrt(g*0.5d0*(hR+hL)) ! Roe average
         sRoe1=uhat-chat ! Roe wave speed 1 wave
         sRoe2=uhat+chat ! Roe wave speed 2 wave

         sE1 = min(sL,sRoe1) ! Eindfeldt speed 1 wave
         sE2 = max(sR,sRoe2) ! Eindfeldt speed 2 wave

         !--------------------end initializing...finally----------
         !solve Riemann problem.

         maxiter = 1

         call riemann_aug_JCP(maxiter,meqn,mwaves,hL,hR,huL,
     &        huR,hvL,hvR,bL,bR,uL,uR,vL,vR,phiL,phiR,pL,pR,sE1,sE2,
     &                                    drytol,g,rho,sw,fw)

c        !eliminate ghost fluxes for wall
         do mw=1,3
            sw(mw)=sw(mw)*wall(mw)

               fw(1,mw)=fw(1,mw)*wall(mw)
               fw(2,mw)=fw(2,mw)*wall(mw)
               fw(3,mw)=fw(3,mw)*wall(mw)
         enddo

         do mw=1,mwaves
            s(mw,i)=sw(mw)
            fwave(1,mw,i)=fw(1,mw)
            fwave(mu,mw,i)=fw(2,mw)
            fwave(nv,mw,i)=fw(3,mw)
         enddo

 30      continue
      enddo


c==========Capacity for mapping from latitude longitude to physical space====
        if (mcapa.gt.0) then
         do i=2-mbc,mx+mbc
          if (ixy.eq.1) then
             dxdc=(earth_radius*deg2rad)
          else
             dxdc=earth_radius*cos(auxl(3,i))*deg2rad
          endif

          do mw=1,mwaves
               s(mw,i)=dxdc*s(mw,i)
               fwave(1,mw,i)=dxdc*fwave(1,mw,i)
               fwave(2,mw,i)=dxdc*fwave(2,mw,i)
               fwave(3,mw,i)=dxdc*fwave(3,mw,i)
          enddo
         enddo
        endif

c===============================================================================


c============= compute fluctuations=============================================

         do i=2-mbc,mx+mbc
            do  mw=1,mwaves
               if (s(mw,i) < -1.d-14) then
                     amdq(1:3,i) = amdq(1:3,i) + fwave(1:3,mw,i)
               else if (s(mw,i) > 1.d-14) then
                  apdq(1:3,i)  = apdq(1:3,i) + fwave(1:3,mw,i)
               else
                 amdq(1:3,i) = amdq(1:3,i) + 0.5d0 * fwave(1:3,mw,i)
                 apdq(1:3,i) = apdq(1:3,i) + 0.5d0 * fwave(1:3,mw,i)
               endif
            enddo
         enddo

      return
      end subroutine
