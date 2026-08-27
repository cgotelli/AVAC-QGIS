program internal_inflow_driver
    use internal_inflow_module, only: read_internal_inflow, apply_internal_inflow
    implicit none
    integer, parameter :: mbc=2, mx=439, my=2114, meqn=3
    real(kind=8), allocatable :: q(:,:,:)
    character(len=1024) :: path

    call get_command_argument(1, path)
    allocate(q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc))
    q = 0.d0
    call read_internal_inflow(trim(path))
    call apply_internal_inflow(meqn,mbc,mx,my,2592772.5d0,1088965.d0,2.5d0,2.5d0,q,18.d0,0.05d0)
    if (sum(q(1,:,:)) <= 0.d0) stop 1
    write(6,*) "Applied depth sum:", sum(q(1,:,:))
end program internal_inflow_driver
