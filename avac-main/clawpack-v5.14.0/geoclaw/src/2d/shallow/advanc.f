c
c --------------------------------------------------------------
c
      subroutine advanc (level,nvar,dtlevnew,vtime,naux)
c
      implicit double precision (a-h,o-z)

      logical vtime

c     Compatibility entry point used by initialization/Richardson code.
c     Normal tick integration prepares once, probes as often as necessary,
c     and calls advanc_prepared directly after its timestep is accepted.
      call prepare_advanc(level,nvar,naux)
      call advanc_prepared(level,nvar,dtlevnew,vtime,naux)

      return
      end
c
c --------------------------------------------------------------
c
      subroutine prepare_advanc(level,nvar,naux)
c
      use amr_module
      use topo_module, only: topo_finalized

      implicit double precision (a-h,o-z)

      integer(kind=8) :: clock_start, clock_finish, clock_rate
      integer(kind=8) :: clock_startBound,clock_finishBound
      real(kind=8) cpu_start, cpu_finish
      real(kind=8) cpu_startBound,cpu_finishBound

c  Prepare a level exactly once in the legacy order: fill ghost cells, save
c  coarse values needed by fine-grid wave fixup, then update moving
c  topography.  None of these operations depends on the trial timestep.
      call system_clock(clock_start,clock_rate)
      call cpu_time(cpu_start)
      call system_clock(clock_startBound,clock_rate)
      call cpu_time(cpu_startBound)

c Fill AMR ghost cells in deterministic grid order.  The recursive AMR
c interpolation used by bound() shares hierarchy work arrays and is not
c thread-safe, so do not call bound() concurrently for sibling patches.
      do  j = 1, numgrids(level)
          levSt  = listStart(level)
          mptr   = listOfGrids(levSt+j-1)
          nx     = node(ndihi,mptr) - node(ndilo,mptr) + 1
          ny     = node(ndjhi,mptr) - node(ndjlo,mptr) + 1
          mitot  = nx + 2*nghost
          mjtot  = ny + 2*nghost
          locnew = node(store1,mptr)
          locaux = node(storeaux,mptr)
          time   = rnode(timemult,mptr)
c
          call bound(time,nvar,nghost,alloc(locnew),mitot,mjtot,mptr,
     1               alloc(locaux),naux)

      end do
      call system_clock(clock_finishBound,clock_rate)
      call cpu_time(cpu_finishBound)
      timeBound = timeBound + clock_finishBound - clock_startBound
      timeBoundCPU=timeBoundCPU+cpu_finishBound-cpu_startBound

c
c save coarse level values if there is a finer level for wave fixup
      if (level+1 .le. mxnest) then
         if (lstart(level+1) .ne. null) then
            call saveqc(level+1,nvar,naux)
         endif
      endif
c
      time = rnode(timemult,lstart(level))
      if (.not. topo_finalized) then
         call topo_update(time)
      endif

      call system_clock(clock_finish,clock_rate)
      call cpu_time(cpu_finish)
      tvoll(level) = tvoll(level) + clock_finish - clock_start
      tvollCPU(level) = tvollCPU(level) + cpu_finish - cpu_start

      return
      end
c
c --------------------------------------------------------------
c
      subroutine advanc_prepared(level,nvar,dtlevnew,vtime,naux)
c
      use amr_module

      implicit double precision (a-h,o-z)

      logical vtime
      integer mythread/0/
      integer(kind=8) :: clock_start, clock_finish, clock_rate
      integer(kind=8) :: clock_startStepgrid
      real(kind=8) cpu_start, cpu_finish
      real(kind=8) cpu_startStepgrid

c  Integrate a level whose boundary/fixup/topography preparation has already
c  been committed.  tick calls this only after the whole-level CFL preflight
c  accepts the shared timestep.
      call system_clock(clock_start,clock_rate)
      call cpu_time(cpu_start)
      hx   = hxposs(level)
      hy   = hyposs(level)
      delt = possk(level)

      dtlevnew = rinfinity
      cfl_level = 0.d0
c
      call system_clock(clock_startStepgrid,clock_rate)
      call cpu_time(cpu_startStepgrid)

c  set number of thrad to use. later will base on number of grids
c     nt = 4
c   ! $OMP PARALLEL DO num_threads(nt)

!$OMP PARALLEL DO
!$OMP&            PRIVATE(j,mptr,nx,ny,mitot,mjtot)
!$OMP&            PRIVATE(mythread,dtnew,levSt)
!$OMP&            SHARED(rvol,rvoll,level,nvar,mxnest,alloc,intrat)
!$OMP&            SHARED(nghost,intratx,intraty,hx,hy,naux,listsp)
!$OMP&            SHARED(node,rnode,dtlevnew,numgrids)
!$OMP&            SHARED(listStart,listOfGrids)
!$OMP&            SCHEDULE (DYNAMIC,1)
!$OMP&            ORDERED
!$OMP&            DEFAULT(none)
      do  j = 1, numgrids(level)
          levSt  = listStart(level)
          mptr   = listOfGrids(levSt+j-1)
          nx     = node(ndihi,mptr) - node(ndilo,mptr) + 1
          ny     = node(ndjhi,mptr) - node(ndjlo,mptr) + 1
          mitot  = nx + 2*nghost
          mjtot  = ny + 2*nghost
c
          call par_advanc(mptr,mitot,mjtot,nvar,naux,dtnew)
!$OMP CRITICAL (newdt)
          dtlevnew = dmin1(dtlevnew,dtnew)
!$OMP END CRITICAL (newdt)

      end do
!$OMP END PARALLEL DO
c
      call system_clock(clock_finish,clock_rate)
      call cpu_time(cpu_finish)
      tvoll(level) = tvoll(level) + clock_finish - clock_start
      tvollCPU(level) = tvollCPU(level) + cpu_finish - cpu_start
      timeStepgrid = timeStepgrid +clock_finish-clock_startStepgrid
      timeStepgridCPU=timeStepgridCPU+cpu_finish-cpu_startStepgrid

c
      return
      end
c
c --------------------------------------------------------------
c
      subroutine cfl_preflight(level,nvar,naux,cfl_trial,cfl_invalid)
c
      use, intrinsic :: ieee_arithmetic, only: ieee_is_finite
      use amr_module

      implicit double precision (a-h,o-z)

      double precision cfl_trial,cfl_patch
      integer cfl_invalid

c  Compute the maximum CFL for one prepared AMR level without committing a
c  physical step.  Each patch is copied to private scratch storage; b4step2
c  and step2 may alter only those copies and temporary fluxes.
c
c  In particular, this deliberately does not touch gauges, fixed-grid
c  observations, flux registers, patch clocks, cflmax, cfl_level, or the
c  accepted solution.  tick can therefore reduce the common level timestep
c  and repeat this trial safely before calling advanc_prepared exactly once.

      cfl_trial = 0.d0
      cfl_invalid = 0
!$OMP PARALLEL DO
!$OMP& PRIVATE(j,levSt,mptr,nx,ny,mitot,mjtot,cfl_patch)
!$OMP& REDUCTION(MAX:cfl_trial)
!$OMP& SCHEDULE(DYNAMIC,1)
      do j = 1, numgrids(level)
          levSt  = listStart(level)
          mptr   = listOfGrids(levSt+j-1)
          nx     = node(ndihi,mptr) - node(ndilo,mptr) + 1
          ny     = node(ndjhi,mptr) - node(ndjlo,mptr) + 1
          mitot  = nx + 2*nghost
          mjtot  = ny + 2*nghost
          call par_cfl_preflight(mptr,mitot,mjtot,nvar,naux,
     &                           cfl_patch)
          if ((.not. ieee_is_finite(cfl_patch)) .or.
     &        cfl_patch .lt. 0.d0) then
              cfl_patch = huge(1.d0)
          endif
          cfl_trial = dmax1(cfl_trial,cfl_patch)
      end do
!$OMP END PARALLEL DO
      if (cfl_trial .eq. huge(1.d0)) cfl_invalid = 1

      return
      end
c
c --------------------------------------------------------------
c
      subroutine par_cfl_preflight(mptr,mitot,mjtot,nvar,naux,
     &                             cfl_patch)
c
      use amr_module

      implicit double precision (a-h,o-z)

      external rpn2,rpt2
      double precision cfl_patch
      double precision, allocatable :: qwork(:,:,:),auxwork(:,:,:)
      double precision, allocatable :: fm(:,:,:),fp(:,:,:)
      double precision, allocatable :: gm(:,:,:),gp(:,:,:)

      level = node(nestlevel,mptr)
      hx    = hxposs(level)
      hy    = hyposs(level)
      delt  = possk(level)
      nx    = node(ndihi,mptr) - node(ndilo,mptr) + 1
      ny    = node(ndjhi,mptr) - node(ndjlo,mptr) + 1
      time  = rnode(timemult,mptr)
      locnew = node(store1,mptr)
      locaux = node(storeaux,mptr)
      maxm = max(nx,ny)

c     Keep the additional trial storage on the heap.  Large AVAC patches and
c     several OpenMP workers otherwise exceed the small default Windows
c     thread stack.
      allocate(qwork(nvar,mitot,mjtot))
      allocate(auxwork(max(1,naux),mitot,mjtot))
      allocate(fm(nvar,mitot,mjtot),fp(nvar,mitot,mjtot))
      allocate(gm(nvar,mitot,mjtot),gp(nvar,mitot,mjtot))

      auxwork = 0.d0
      do jj = 1,mjtot
          do ii = 1,mitot
              do m = 1,nvar
                  idx = m + nvar*((ii-1)+mitot*(jj-1))
                  qwork(m,ii,jj) = alloc(locnew+idx-1)
              enddo
              do m = 1,naux
                  idx = m + naux*((ii-1)+mitot*(jj-1))
                  auxwork(m,ii,jj) = alloc(locaux+idx-1)
              enddo
          enddo
      enddo

c     Use actualstep=.true. on private copies so transient topography, storm,
c     dry-state, speed, and AVAC static-yield preparation exactly match the
c     subsequently accepted call.
      call b4step2(nghost,nx,ny,nvar,qwork,
     &             rnode(cornxlo,mptr),rnode(cornylo,mptr),hx,hy,
     &             time,delt,naux,auxwork,.true.)

      call step2(maxm,nvar,naux,nghost,nx,ny,
     &           qwork,auxwork,hx,hy,delt,cfl_patch,
     &           fm,fp,gm,gp,rpn2,rpt2)

      deallocate(qwork,auxwork,fm,fp,gm,gp)
      return
      end
c
c -------------------------------------------------------------
c
       subroutine prepgrids(listgrids,num, level)

       use amr_module
       implicit double precision (a-h,o-z)
       integer listgrids(num)

       mptr = lstart(level)
       do j = 1, num
          listgrids(j) = mptr
          mptr = node(levelptr, mptr)
       end do

      if (mptr .ne. 0) then
         write(*,*)" Error in routine setting up grid array "
         stop
      endif

      return
      end

c
c --------------------------------------------------------------
c
      subroutine par_advanc (mptr,mitot,mjtot,nvar,naux,dtnew)
c
      use amr_module
      use gauges_module, only: update_gauges, num_gauges
      implicit double precision (a-h,o-z)


      integer omp_get_thread_num, omp_get_max_threads
      integer mythread/0/, maxthreads/1/

      double precision fp(nvar,mitot,mjtot),fm(nvar,mitot,mjtot)
      double precision gp(nvar,mitot,mjtot),gm(nvar,mitot,mjtot)


c
c  :::::::::::::: PAR_ADVANC :::::::::::::::::::::::::::::::::::::::::::
c  integrate this grid. grids are done in parallel.
c  extra subr. used to allow for stack based allocation of
c  flux arrays. They are only needed temporarily. If used alloc
c  array for them it has too long a lendim, makes too big
c  a checkpoint file, and is a big critical section.
c :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
c
      level = node(nestlevel,mptr)
      hx    = hxposs(level)
      hy    = hyposs(level)
      delt  =  possk(level)
      nx    = node(ndihi,mptr) - node(ndilo,mptr) + 1
      ny    = node(ndjhi,mptr) - node(ndjlo,mptr) + 1
      time  = rnode(timemult,mptr)

!$         mythread = omp_get_thread_num()

      locold = node(store2, mptr)
      locnew = node(store1, mptr)

c
c  copy old soln. values into  next time steps soln. values
c  since integrator will overwrite it. only for grids not at
c  the finest level. finest level grids do not maintain copies
c  of old and new time solution values.
c
          if (level .lt. mxnest) then
             ntot   = mitot * mjtot * nvar
cdir$ ivdep
             do 10 i = 1, ntot
 10            alloc(locold + i - 1) = alloc(locnew + i - 1)
          endif
c
      xlow = rnode(cornxlo,mptr) - nghost*hx
      ylow = rnode(cornylo,mptr) - nghost*hy

!$OMP CRITICAL(rv)
      rvol = rvol + nx * ny
      rvoll(level) = rvoll(level) + nx * ny
!$OMP END CRITICAL(rv)

c     Call b4step2 here so that time dependent arrays can be filled properly
c     Pass delt, the initialized timestep for this AMR level.  The old call
c     passed an uninitialized local named dt, making any b4step2/Riemann logic
c     that consumes dt nondeterministic under OpenMP and AMR regridding.
      locaux = node(storeaux,mptr)
      call b4step2(nghost, nx, ny, nvar, alloc(locnew),
     &             rnode(cornxlo,mptr), rnode(cornylo,mptr), hx, hy,
     &             time, delt, naux, alloc(locaux), .true.)
c
      if (node(ffluxptr,mptr) .ne. 0) then
         lenbc  = 2*(nx/intratx(level-1)+ny/intraty(level-1))
         locsvf = node(ffluxptr,mptr)
         locsvq = locsvf + nvar*lenbc
         locx1d = locsvq + nvar*lenbc
         call qad(alloc(locnew),mitot,mjtot,nvar,
     1            alloc(locsvf),alloc(locsvq),lenbc,
     2            intratx(level-1),intraty(level-1),hx,hy,
     3            naux,alloc(locaux),alloc(locx1d),delt,mptr)
      endif

c        # See if the grid about to be advanced has gauge data to output.
c        # This corresponds to previous time step, but output done
c        # now to make linear interpolation easier, since grid
c        # now has boundary conditions filled in.

c     should change the way print_gauges does io - right now is critical section
c     NOW changed, mjb 2/6/2015.
c     NOTE that gauge subr called before stepgrid, so never get
c     the very last gauge time at end of run.

      if (num_gauges > 0) then
           call update_gauges(alloc(locnew:locnew+nvar*mitot*mjtot),
     .                       alloc(locaux:locaux+naux*mitot*mjtot),
     .                       xlow,ylow,nvar,mitot,mjtot,naux,mptr)
           endif

c
      call stepgrid(alloc(locnew),fm,fp,gm,gp,
     2            mitot,mjtot,nghost,
     3            delt,dtnew,hx,hy,nvar,
     4            xlow,ylow,time,mptr,naux,alloc(locaux))

c     fluxsv writes coarse-patch fluxes into registers owned by adjacent
c     fine patches.  Two coarse patches can touch the same fine patch, so
c     save them in deterministic coarse-grid order.
!$OMP ORDERED
      if (node(cfluxptr,mptr) .ne. 0)
     2   call fluxsv(mptr,fm,fp,gm,gp,
     3               alloc(node(cfluxptr,mptr)),mitot,mjtot,
     4               nvar,listsp(level),delt,hx,hy)
!$OMP END ORDERED
      if (node(ffluxptr,mptr) .ne. 0) then
         lenbc = 2*(nx/intratx(level-1)+ny/intraty(level-1))
         locsvf = node(ffluxptr,mptr)
         call fluxad(fm,fp,gm,gp,
     2               alloc(locsvf),mptr,mitot,mjtot,nvar,
     4               lenbc,intratx(level-1),intraty(level-1),
     5               nghost,delt,hx,hy)
      endif
c
c        write(outunit,969) mythread,delt, dtnew
c969     format(" thread ",i4," updated by ",e15.7, " new dt ",e15.7)
          rnode(timemult,mptr)  = rnode(timemult,mptr)+delt
c
      return
      end
