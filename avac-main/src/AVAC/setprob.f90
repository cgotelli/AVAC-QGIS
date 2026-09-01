! setprob.f90 for AVAC 4: version = 4.0
!
! Reads rheological parameters from setprob.data and populates:
!   - rheology_module scalar state: rho_rh, u_cr_rh, imodel_rh
!   - rheology_module   : n_zones_rh, z_breaks_rh, mu_zones_rh, xi_zones_rh
!                         (altitude-zoned mu and xi, accessed via get_mu_xi)
!
! setprob.data format (written by setrun.py):
!   rho               snow density (kg/m³)
!   C                 cohesion (Pa) !!! removed
!   u_cr              legacy unused compatibility value (m/s)
!   velocity_depth_threshold  minimum depth for a reported velocity (m)
!   n_zones           number of altitude zones (>= 1)
!   z_break_0 .. z_break_{n-2}   altitude thresholds (m), one per line, ascending
!   mu_0 .. mu_{n-1}             Coulomb coefficients, one per line
!   xi_0 .. xi_{n-1}             Voellmy xi values (m/s²), one per line
!   C_0 .. C_{n-1}               cohesion (Pa), one per line
!   constitutive_model           string: Coulomb | Voellmy | cohesive_Voellmy
!   itype_init                   0 = synthetic topo, 1 = file-based
!   [theta free_surface d0 x_b]  only if itype_init == 0

subroutine setprob

    use rheology_module
    use hydraulic_bc_module, only: setup_hydraulic_bc
    use geoclaw_module, only: conserve_depth_amr, refinement_energy_depth

    implicit none

    character*12 fname, free_surface
    integer iunit, k
    !double precision :: rho, C, u_cr
    double precision :: rho, u_cr, velocity_depth_threshold
    double precision :: d_0, x_b, theta
    integer :: imodel, itype_init, n_zones
    character(len=20) :: constitutive_model
    common /initial_conditions/ free_surface
    common /initial_depth/ d_0, theta, x_b

    !
    !     # read data values for this problem
    !
    iunit = 7
    fname = 'setprob.data'
    !     # open the unit with new routine from Clawpack 4.4 to skip over
    !     # comment lines starting with #:
    call opendatafile(iunit, fname)

    !     # Rheological scalars
    read(7,*) rho
    !read(7,*) C
    read(7,*) u_cr
    read(7,*) velocity_depth_threshold

    !     # Number of altitude zones
    read(7,*) n_zones
    n_zones_rh = n_zones

    !     # Allocate and read altitude thresholds (n_zones-1 values)
    if (allocated(z_breaks_rh)) deallocate(z_breaks_rh)
    allocate(z_breaks_rh(max(n_zones - 1, 1)))   ! min size 1 to avoid zero-size
    do k = 1, n_zones - 1
        read(7,*) z_breaks_rh(k)
    end do

    !     # Allocate and read mu array (n_zones values)
    if (allocated(mu_zones_rh)) deallocate(mu_zones_rh)
    allocate(mu_zones_rh(n_zones))
    do k = 1, n_zones
        read(7,*) mu_zones_rh(k)
    end do

    !     # Allocate and read xi array (n_zones values)
    if (allocated(xi_zones_rh)) deallocate(xi_zones_rh)
    allocate(xi_zones_rh(n_zones))
    do k = 1, n_zones
        read(7,*) xi_zones_rh(k)
    end do

    if (allocated(C_zones_rh)) deallocate(C_zones_rh)
    allocate(C_zones_rh(n_zones))
    do k = 1, n_zones
        read(7,*) C_zones_rh(k)
    end do

    !     # Constitutive model name and init type
    read(7,*) constitutive_model
    read(7,*) itype_init

!     # These parameters are used in qinit.f90 (synthetic topography only)
    if (itype_init == 0) then
        read(7,*) theta
        read(7,*) free_surface
        read(7,*) d_0
        read(7,*) x_b
    end if
    close(unit=7)

    call setup_hydraulic_bc()

    !     # Convert constitutive model name to integer flag
    !     # imodel = 0  =>  Water (standard Manning friction when enabled)
    !     # imodel = 1  =>  Coulomb
    !     # imodel = 2  =>  Voellmy
    !     # imodel = 3  =>  cohesive_Voellmy
    if (trim(constitutive_model) == 'Water') then
        imodel = 0
    else if (trim(constitutive_model) == 'Coulomb') then
        imodel = 1
    else if (trim(constitutive_model) == 'Voellmy') then
        imodel = 2
    else if (trim(constitutive_model) == 'cohesive_Voellmy') then
        imodel = 3
    else
        print *, 'ERROR in setprob: unknown constitutive_model = ', &
                 trim(constitutive_model)
        print *, 'Valid options are: Water, Coulomb, Voellmy, cohesive_Voellmy'
        stop
    end if

    rho_rh = rho
    u_cr_rh = u_cr
    velocity_depth_threshold_rh = max(0.d0, velocity_depth_threshold)
    imodel_rh = imodel
    conserve_depth_amr = .true.
    refinement_energy_depth = velocity_depth_threshold_rh

    print *, 'rho (snow density) = ', rho
    !print *, 'C (cohesion, Pa)   = ', C
    print *, 'u_cr (legacy, unused) = ', u_cr
    print *, 'velocity depth threshold (m) = ', &
             velocity_depth_threshold_rh
    print *, 'constitutive_model = ', trim(constitutive_model), &
             '  (imodel=', imodel, ')'
    print *, 'number of altitude zones = ', n_zones
    print *, 'conservative AVAC AMR depth transfer = ', conserve_depth_amr
    print *, 'AMR kinetic-energy reference depth = ', refinement_energy_depth
    do k = 1, n_zones - 1
        print *, '  z_break(', k, ') = ', z_breaks_rh(k), ' m'
    end do
    do k = 1, n_zones
        print *, '  zone', k, ': mu =', mu_zones_rh(k), &
                 '  xi =', xi_zones_rh(k)
    end do

end subroutine setprob
