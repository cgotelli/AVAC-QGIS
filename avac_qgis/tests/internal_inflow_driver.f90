program internal_inflow_driver
    use internal_inflow_module, only: read_internal_inflow, apply_internal_inflow
    implicit none
    integer, parameter :: mbc=2, mx=2, my=2, meqn=3
    real(kind=8), allocatable :: q(:,:,:)
    character(len=1024) :: path

    call get_command_argument(1, path)
    allocate(q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc))
    q = 0.d0
    call read_internal_inflow(trim(path))
    call apply_internal_inflow(meqn,mbc,mx,my,0.d0,0.d0,1.d0,1.d0,q,0.d0,1.d0)
    if (abs(sum(q(1,:,:)) - 1.d0) > 1.d-12) stop 1
    if (abs(sum(q(2,:,:)) - 2.d0) > 1.d-12) stop 2
    if (abs(sum(q(3,:,:)) + 3.d0) > 1.d-12) stop 3
    write(6,*) "Applied Q, Q*u, Q*v:", sum(q(1,:,:)), sum(q(2,:,:)), sum(q(3,:,:))
end program internal_inflow_driver
