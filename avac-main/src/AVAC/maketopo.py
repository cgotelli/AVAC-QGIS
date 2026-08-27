import numpy as np
from clawpack.geoclaw import topotools as topo

def maketopo(theta_rad, xlower = -40,xupper = 100, yupper = 5, ylower = -5, cell_size = 1, type='plane', z_ref=0, θ2_deg=5, x_t = 100, K=0.1):
    """
    Output topography file for the entire domain.
    The topography is a plane inclined at theta (in deg, absolute value) with respect to the horizontal if type = 'plane'
    The topography is a curved surface given z = fnc_curve if type != 'plane'
    """
    theta_rad = np.abs(theta_rad)
    if theta_rad > 1: print(f"check slope angle θ = {theta_rad:.2f}>1")
    nxpoints = int((xupper-xlower)/cell_size)+1
    nypoints = int((yupper-ylower)/cell_size)+1

    outfile  = "plane.topotype3.asc"     

    if (xlower+(nxpoints-1)*cell_size != xupper): print("check cell size for the x-direction")
    if (ylower+(nypoints-1)*cell_size != yupper): print("check cell size for the y-direction")

    topography = topo.Topography()
    x = np.linspace(xlower,xupper,nxpoints)
    y = np.linspace(ylower,yupper,nypoints)
    X_fine_grid, Y_fine_grid = np.meshgrid(x,y)
    if type == 'curved':
        theta_deg = np.rad2deg(theta_rad)
        Z = fnc_curve(X_fine_grid, Y_fine_grid,  theta_deg, θ2_deg, z_ref, K, x_t )
        print("I created the curved surface.")
    if type == 'elbow':
        theta_deg = np.rad2deg(theta_rad)
        Z = elbow(X_fine_grid, Y_fine_grid,  theta_deg, θ2_deg, x_t,xlower,z_ref,R=1/K )
        print("I created the curved surface.")
    else:
        Z = fnc_plane(X_fine_grid, Y_fine_grid, theta_rad,z_ref)
        print("I created the inclined plane surface.")
    topography.x = x
    topography.y = y
    topography.Z = Z
    topography.write(outfile, topo_type=3, Z_format="%22.15e")

def fnc_plane(x, y, θ_rad ,z_ref):
    """
    inclined plane 
    """
    θ_1   = -θ_rad
    z = z_ref+np.tan(θ_1 )*x
    return z

def fnc_curve(x, y, θ_1, θ_2, z_ref, K ,x_t):
    """
    inclined planes intersecting at x = x_t (K corner curvature)
    """
    θ_1   = -np.deg2rad(θ_1)
    θ_2   = -np.deg2rad(θ_2)

    z = z_ref+np.tan(θ_1 )*x+(1+np.tanh(K*(x-x_t)))/2*(np.tan(θ_2 )*x-np.tan(θ_1 )*x+(np.tan(θ_1 )-np.tan(θ_2 )) *x_t)
    return z



def elbow(x, y, θ_1, θ_2, L1, x0, y0, R=20):
    """ 
    two planes linked by an arc of circle of radius R
    point 0: left end of the first plane
    point A: right end of the first plane
    point B: left end of the second plane
    point C: position of the center of the circle
    return elevation z
    """
    # Conveersion to radians
    theta1 = np.deg2rad(θ_1)
    theta2 = np.deg2rad(θ_2)
    
    # Point coordinates
    xa = x0 + L1
    ya = y0 - xa * np.tan(theta1)
    xc = R * np.sin(theta1) + xa
    yc = R * np.cos(theta1) + ya   
    xb = xc - R * np.sin(theta2)
    yb = yc - R * np.cos(theta2)
    
    
     
    z = np.zeros_like(x, dtype=float)
    
    # plane1
    mask1 = (x >= x0) & (x <= xa)
    z[mask1] = y0 - x[mask1] * np.tan(theta1)
    
    # elbow
    mask2 = (x > xa) & (x <= xb)
    cos_angle = (x[mask2] - xc) / R
    angle = np.arccos(cos_angle)
    z[mask2] = yc - R * np.sin(angle)
    
    # plane2
    mask3 = x > xb
    z[mask3] = yb - (x[mask3] - xb) * np.tan(theta2)
    
    return z