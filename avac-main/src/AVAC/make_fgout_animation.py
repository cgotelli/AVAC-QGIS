# make_fgout_animation.py for AVAC 4: version = 1.0
"""
Initial script provided in
https://www.clawpack.org/gallery/_static/geoclaw/examples/tsunami/chile2010_fgmax-fgout/make_fgout_animation.py.html
Make an mp4 animation of fgout grid results. 
This is done in a way that makes the animation quickly and with minimum 
storage required, by making one plot and then defining an update function
that only changes the parts of the plot that change in each frame.

Make the animation via:
    python make_fgout_animation.py

If this script is executed in IPython or a notebook it may go into
an infinite loop for reasons unknown.  If so, close the figure to halt.

To view individual fgout frames interactively, this should work:
    import make_fgout_animation
    make_fgout_animation.update(fgframeno)  # for desired fgout frame no
    
Modified March 2026 for AVAC by C. Ancey

"""

import sys
if 'matplotlib' not in sys.modules:
    # Use an image backend to insure animation has size specified by figsize
    import matplotlib
    matplotlib.use('Agg')

import matplotlib
matplotlib.rcParams['animation.embed_limit'] = 100
import os, glob
from pylab import *
from clawpack.visclaw import plottools, geoplot
from clawpack.visclaw import animation_tools
from matplotlib import animation, colors
from datetime import timedelta
from clawpack.geoclaw import fgout_tools
from pathlib import Path
from yaml import safe_load
from module_avac import plot_topo, reading_raster_file

# opening the configuration file
projdir = Path(__file__).parents[0]
with open(projdir / "AVAC_configuration.yaml") as file:
    configuration = safe_load(file)
    Files   = configuration["file_names"]
    Rheol   = configuration["rheology"]
    DEM     = configuration["dem_extent"]
    Param   = configuration["computation"]
    OUT     = configuration["output"]
    Movie   = configuration["animation"]
    Release = configuration['release']

# Directory to which animation is exported
animation_dir = Path(Movie['animation_directory'])
topo_dir      = Path(Files['topo_directory'])
#######################
# variable definition #
#######################
# which fgout grid
fgno       = 1  

# variable definition
outdir     = OUT['output_directory'] #'_output'
out_format = OUT['output_format']
variable   = Movie['variable']

if 1:
    # use all fgout frames in outdir:
    fgout_frames = glob.glob(os.path.join(outdir, \
                                          'fgout%s.t*' % str(fgno).zfill(4)))
    nout = len(fgout_frames)
    fgframes = range(1, nout+1)
    print('Found %i fgout frames in %s' % (nout,outdir))
else:
    # set explicitly, e.g. to test with only a few frames
    fgframes = range(1,26)  # frames of fgout solution to use in animation

###################
# cmap definition #
###################
ϵ = 1e-6
#depth
bounds_depth = np.array([ϵ,0.1,0.5,1,2,4,8,16])
cmap_depth = mpl.colors.ListedColormap([[.9,.9,1],[.6,.6,1],\
                 [.3,.3,1],[0,0,1], [1,.8,.8],\
                 [1,.6,.6], [1,0,0]])

# pressure (kPa)
bounds_pressure = np.array([ϵ,1e3,5e3,1e4,3e4,5e4,1e5,2e5])/1e3
cmap_pressure = mpl.colors.ListedColormap([[.9,.9,1],[.6,.6,1],\
                 [.3,.3,1],[0,0,1], [1,.8,.8],\
                 [1,.6,.6], [1,0,0]])

# velocity norm
bounds_speed = np.array([ϵ,0.5,1,2,4,8,16,32])
cmap_speed = mpl.colors.ListedColormap([[.9,.9,1],[.6,.6,1],\
                 [.3,.3,1],[0,0,1], [1,.8,.8],\
                 [1,.6,.6], [1,0,0]])

# Set color for value exceeding top of range to purple if needed:
cmap_speed.set_over(color=[1,0,1])
cmap_depth.set_over(color=[1,0,1])
cmap_pressure.set_over(color=[1,0,1])

# Set color for land points with too low values to light green if needed:
cmap_speed.set_under(color=[.7,1,.7])
cmap_depth.set_under(color=[.7,1,.7])
cmap_pressure.set_under(color=[.7,1,.7])

# Normalization
norm_speed = colors.BoundaryNorm(bounds_speed, cmap_speed.N)
norm_depth = colors.BoundaryNorm(bounds_depth, cmap_depth.N)
norm_pressure = colors.BoundaryNorm(bounds_pressure, cmap_pressure.N)

 

###################
# Instantiation   #
###################
# Instantiate object for reading fgout frames:
fgout_grid = fgout_tools.FGoutGrid(fgno, outdir,output_format = out_format) 
fgout_grid.read_fgout_grids_data()


# Plot one frame of fgout data and define the Artists that will need to
# be updated in subsequent frames:
fgout1 = fgout_grid.read_frame(fgframes[0])


# DEM
bottom    = fgout1.B
cell_size = (-fgout1.X[0]+fgout1.X[1])[0]
xmin = fgout1.X.min()
ymin = fgout1.Y.min()

topo_file = reading_raster_file(topo_dir / Files['topofile'])
step = Movie['label_step']
fig, axes, x0, y0 = plot_topo(topo_file,step=step)

#cmap
velocity = ma.masked_where(fgout1.h<0.001, fgout1.s)
depth    = ma.masked_where(fgout1.h<0.001, fgout1.h)
ρ        = Rheol['rho']
pressure = 0.5*ρ*velocity**2/1e3 # pressure is expressed in kPa

# plot

Language = OUT['Language']
if variable == 'depth':
    légende = "hauteur (m)" if Language == 'French' else 'depth (m)'
    pc = plottools.pcolorcells(fgout1.X-xmin, fgout1.Y-ymin, depth, cmap=cmap_depth, norm=norm_depth,ax=axes,alpha=0.75)
    cb = colorbar(pc, extend='max', shrink=0.7,label=légende)
elif variable == 'pressure':
    légende = 'pression cinétique (kPa)' if Language == 'French' else 'pressure (kPa)'
    pc = plottools.pcolorcells(fgout1.X-xmin, fgout1.Y-ymin, pressure, cmap=cmap_pressure, norm=norm_pressure,ax=axes,alpha=0.75)
    cb = colorbar(pc, extend='max', shrink=0.7,label=légende)
else:
    légende = 'vitesse (m/s)' if Language == 'French' else 'velocity (m/s)'
    pc = plottools.pcolorcells(fgout1.X-xmin, fgout1.Y-ymin, velocity, cmap=cmap_speed, norm=norm_speed,ax=axes,alpha=0.75)
    cb = colorbar(pc, extend='max', shrink=0.7,label=légende)


texte = "Avalanche à " if Language == 'French' else "Avalanche at time "
title_text = title(rf"{texte}$t=${fgout1.t:0.1f} s.") 
 

blit = False
if blit:
    # The artists that will be updated for subsequent frames:
    update_artists = (pc, title_text)
    
# Note that update_artists is only needed if blit==True in call to
# animation.FuncAnimation below.
# Using blit==False does not seem to slow down creation of the animation by much
# and slightly simplifies modification of this script to situations where more
# artists are updated.
        
def update(fgframeno):
    """
    Update an exisiting plot with solution from fgout frame fgframeno.
    Note: Even if blit==True in call to animation.FuncAnimation,
    the update_artists do not need to be passed in, unpacked, and repacked
    as in an earlier version of this example (Clawpack version <= 5.10.0).
    """
    
    fgout = fgout_grid.read_frame(fgframeno)
    print(f'Updating plot at time { timedelta(seconds=fgout.t)} s.')
        
    # reset title to current time:
    title_text.set_text(rf"{texte} $t=${fgout.t:0.1f} s.")

    # reset surface eta to current state:
    if variable == 'depth':
        depth = ma.masked_where(fgout.h<0.001, fgout.h)
        pc.set_array(depth.T.flatten())
    if variable == 'velocity':
        velocity = ma.masked_where(fgout.h<0.001, fgout.s)
        pc.set_array(velocity.T.flatten())
    if variable == 'pressure':
        ρ        = Rheol['rho']
        pressure = ma.masked_where(fgout1.h<0.001, fgout1.s)**2*ρ/2./1e3
        pc.set_array(pressure.T.flatten())
        
    if blit:
        return update_artists


if __name__ == '__main__':

    print('Making anim...')
    anim = animation.FuncAnimation(fig, update, frames=fgframes, 
                                   interval=200, blit=blit)
    
    # Output files:
    return_period  = Release['period_return']
    name = f'AVAC_animation_for_{variable}_{return_period}yr'

    fname_mp4 = animation_dir / (name + '.mp4')

    #fname_html = None
    fname_html = animation_dir / (name + '.html')

    if not Movie['making_html']:
        fname_html = None

    if fname_mp4:
        fps = 5
        print('Making mp4...')
        writer = animation.writers['ffmpeg'](fps=fps)
        anim.save(fname_mp4, writer=writer)
        print("Created %s" % fname_mp4)


    if fname_html:
        # html version (re-renders all frames a second time):
        print('Making html...')
        animation_tools.make_html(anim, file_name=fname_html, title=name)
        print("Created %s" % fname_html)

