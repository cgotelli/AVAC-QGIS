subroutine setprob
    use internal_inflow_module, only: read_internal_inflow
    use hydraulic_bc_module, only: setup_hydraulic_bc
    implicit none
    character(len=1024) :: inflow_file
    integer :: unit

    unit = 72
    call opendatafile(unit, "setprob.data")
    read(unit,*) inflow_file
    close(unit)
    call read_internal_inflow(trim(inflow_file))
    ! Optional and inert for normal plugin runs.  A hydraulic_bc.data file is
    ! used only by published water benchmarks that request user boundaries.
    call setup_hydraulic_bc()
end subroutine setprob
