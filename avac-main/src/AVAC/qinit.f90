! qinit routine  
subroutine qinit(meqn,mbc,mx,my,xlower,ylower,dx,dy,q,maux,aux)

    !use geoclaw_module, only: grav

    implicit none
    character*12 free_surface
    integer iunit
    double precision theta, d_0, x_b
    common /initial_conditions/ free_surface
    common /initial_depth/ d_0, theta, x_b

    ! Subroutine arguments
    integer, intent(in) :: meqn,mbc,mx,my,maux
    real(kind=8), intent(in) :: xlower,ylower,dx,dy
    real(kind=8), intent(inout) :: q(meqn,1-mbc:mx+mbc,1-mbc:my+mbc)
    real(kind=8), intent(inout) :: aux(maux,1-mbc:mx+mbc,1-mbc:my+mbc)

    ! Parameters for problem
    real(kind=8), parameter :: pente = 0.d0 !  no use for now
    ! Other storage
    integer      :: i,j
    real(kind=8) :: x,y 
    

    if (trim(free_surface) == 'horizontal' .and. theta>0.d0) then
    ! free surface is horizontal
		!xb = -d_0/tan(theta)
		do i=1-mbc,mx+mbc
			x = xlower + (i - 0.5d0)*dx
			do j=1-mbc,my+mbc
				y = ylower + (j - 0.5d0) * dy
				if (x<= x_b) then
					q(1,i,j) = max(0.d0,d_0*tan(theta)*(x_b-x))
				else
					q(1,i,j) = 0.d0
				end if
				q(2,i,j) = 0.d0
				q(3,i,j) = 0.d0
			enddo
		enddo
	! free surface is parallel to the ground
	else 
	        !if (theta > 0.d0) then
	             !xb = -d_0/tan(theta)
	        !else
	             !xb = -10
	        !end if 
			do i=1-mbc,mx+mbc
			x = xlower + (i - 0.5d0)*dx
				do j=1-mbc,my+mbc
					y = ylower + (j - 0.5d0) * dy
					if (x<= x_b) then
						q(1,i,j) = d_0
					else
						q(1,i,j) = 0.d0
					end if
					q(2,i,j) = 0.d0
					q(3,i,j) = 0.d0
				enddo
			enddo
	end if
    
end subroutine qinit
