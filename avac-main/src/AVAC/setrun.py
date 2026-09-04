# setrun.py for AVAC 4: version = 1.1
"""
Module to set up run time parameters for Clawpack.

The values set in the function setrun are then written out to data files
that will be read in by the Fortran code.
Last update: 23 May 2026
"""

from __future__ import absolute_import
from __future__ import print_function
import os
import numpy as np
from clawpack.geoclaw import fgmax_tools
from clawpack.geoclaw import fgout_tools
from pathlib import Path
from yaml import safe_load

proj_dir = Path(__file__).parents[1]
current_dir = Path(__file__).parents[0]
with open(current_dir / "AVAC_configuration.yaml") as file:
    configuration = safe_load(file)
    Files   = configuration["file_names"]
    Rheol   = configuration["rheology"]
    DEM     = configuration["dem_extent"]
    ResultGrid = configuration.get("result_grid")
    Param   = configuration["computation"]
    OUT     = configuration["output"]
    Movie   = configuration["animation"]
    Refine  = configuration["refinement"]
    Gauges  = configuration["gauges"]
    Release = configuration["release"]
    topo_source = Files['topo_source']
topo_dir    = proj_dir / "Topo"


def _whole_cell_count(lower, upper, cell_size, axis):
    """Return an exact positive grid-cell count without truncating roundoff.

    AVAC-QGIS validates the prepared domain before this backend runs, but the
    YAML values are ordinary binary floats.  ``int(span / cell_size)`` can
    truncate an otherwise valid value such as ``0.1 / 0.1`` to zero (or drop
    a full cell from a larger real-world domain).  Round only after checking
    that the ratio is genuinely integral, so hand-written invalid YAMLs also
    fail explicitly rather than producing a different domain from the one
    recorded in the configuration.
    """
    span = float(upper) - float(lower)
    spacing = float(cell_size)
    if not np.isfinite(span) or not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError(f"AVAC {axis}-domain bounds and cell size must be finite, with positive spacing.")
    raw_count = span / spacing
    count = int(round(raw_count))
    if span <= 0.0 or count < 1 or not np.isclose(raw_count, count, rtol=0.0, atol=1e-8):
        raise ValueError(
            f"AVAC {axis}-domain span {span:.12g} is not a whole number of "
            f"{spacing:.12g} m computational cells."
        )
    return count


#------------------------------
def setrun(claw_pkg='geoclaw'):
#------------------------------

    """
    Define the parameters used for running Clawpack.

    INPUT:
        claw_pkg expected to be "geoclaw" for this setrun.

    OUTPUT:
        rundata - object of class ClawRunData

    """

    from clawpack.clawutil import data

    assert claw_pkg.lower() == 'geoclaw',  "Expected claw_pkg = 'geoclaw'"

    num_dim = 2
    rundata = data.ClawRunData(claw_pkg, num_dim)
    # A fine DEM can improve level-1 terrain sampling even when AMR is off,
    # but a second fine-resolution fgmax/fgout grid is then redundant.  It
    # previously forced every step through a huge serialized fixed-grid update
    # and produced hundreds of MB per frame outside the computational domain.
    use_zoom_output = bool(Refine['topo_refinement']) and int(Param['refinement']) > 1

    #------------------------------------------------------------------
    # GeoClaw specific parameters:
    #------------------------------------------------------------------
    rundata = setgeo(rundata)

    #------------------------------------------------------------------
    # Standard Clawpack parameters to be written to claw.data:
    #   (or to amr2ez.data for AMR)
    #------------------------------------------------------------------
    clawdata = rundata.clawdata  # initialized when rundata instantiated


    # Set single grid parameters first.
    # See below for AMR parameters.


    # ---------------
    # Spatial domain:
    # ---------------

    # Number of space dimensions:
    clawdata.num_dim = num_dim


    # Lower and upper edge of computational domain:
    if topo_source == 'real_world':
        # Lower and upper edge of computational domain:
        clawdata.lower[0] = DEM['xmin']
        clawdata.upper[0] = DEM['xmax']

        clawdata.lower[1] = DEM['ymin']
        clawdata.upper[1] = DEM['ymax']
        nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['cell_size'], 'x')
        ny = _whole_cell_count(DEM['ymin'], DEM['ymax'], Param['cell_size'], 'y')
        # Number of grid cells: Coarsest grid
        clawdata.num_cells[0] = nx
        clawdata.num_cells[1] = ny
        

    else:
        clawdata.lower[0] = Param['xlower']
        clawdata.upper[0] = Param['xupper']

        clawdata.lower[1] = Param['ylower']
        clawdata.upper[1] = Param['yupper']
        
        nx = _whole_cell_count(Param['xlower'], Param['xupper'], Param['dx'], 'x')
        ny = _whole_cell_count(Param['ylower'], Param['yupper'], Param['dy'], 'y')
        
        # Number of grid cells: Coarsest grid
        clawdata.num_cells[0] = nx
        clawdata.num_cells[1] = ny

    # GeoClaw FGmax ``point_style = 2`` derives its spacing from n-1, and the
    # QGIS reader needs two centres to reconstruct a raster envelope.  Fail
    # before writing an invalid fixed-grid setup for hand-authored YAML too.
    if nx < 2 or ny < 2:
        raise ValueError(
            "AVAC fixed-grid results require at least two computational cells "
            "along both x and y."
        )
    print(f"* computational domain x = [{clawdata.lower[0]:.2f}, {clawdata.upper[0]:.2f}] m, nx = {nx}")
    print(f"* computational domain y = [{clawdata.lower[1]:.2f}, {clawdata.upper[1]:.2f}] m, ny = {ny}")

    # ---------------
    # Size of system:
    # ---------------
    # Number of equations in the system:
    clawdata.num_eqn = 3
    # aux(1) is the fixed bed.  aux(2) is a transient, cell-centred AVAC
    # static-yield ratio refreshed by b4step2 before every Riemann sweep.  It
    # lets the directional solver reject a diagonal vector-super-yield state.
    # AVAC uses Cartesian coordinates, so this does not conflict with
    # GeoClaw's spherical capacity/latitude auxiliary fields.
    clawdata.num_aux = 2
    # Index of aux array corresponding to capacity function, if there is one:
    clawdata.capa_index = 0

    # -------------
    # Initial time:
    # -------------
    clawdata.t0 = 0.0

    # Restart from checkpoint file of a previous run?
    # If restarting, t0 above should be from original run, and the
    # restart_file 'fort.chkNNNNN' specified below should be in 
    # the OUTDIR indicated in Makefile.
    clawdata.restart      = False            # True to restart from prior results
    clawdata.restart_file = 'fort.chk00006'  # File to use for restart data

    # -------------
    # Output times:
    #--------------
    # Specify at what times the results should be written to fort.q files.
    # Note that the time integration stops after the final output time.
    # The solution at initial time t0 is always written in addition.
    clawdata.output_style = 1

    if clawdata.output_style==1:
        # Output nout frames at equally spaced times up to tfinal:
        clawdata.num_output_times = Param['nb_simul']
        clawdata.tfinal           = Param['t_max']
        clawdata.output_t0        = True  # output at initial (or restart) time?

    elif clawdata.output_style == 2:
        # Specify a list of output times.
        clawdata.output_times = [0.5, 1.0]

    elif clawdata.output_style == 3:
        # Output every iout timesteps with a total of ntot time steps:
        clawdata.output_step_interval = 1
        clawdata.total_steps = 1
        clawdata.output_t0 = True
        
    # --------------
    # Output format:
    #---------------
    clawdata.output_format = OUT['output_format']      # 'ascii', 'binary32" "binary64
    clawdata.output_q_components   = 'all'   # could be list such as [True,True]
    # GeoClaw 5.14 writes all auxiliary fields when any are requested.  Keep
    # bed output for legacy post-processing; aux(2) is solver scratch and is
    # recomputed before each step, so output files are not restart-compatible
    # with the former one-auxiliary-field AVAC layout.
    clawdata.output_aux_components = 'all'
    clawdata.output_aux_onlyonce   = False   # output aux arrays only at t0. False required for post process in jupyter

    # ---------------------------------------------------
    # Verbosity of messages to screen during integration:
    # ---------------------------------------------------
    # The current t, dt, and cfl will be printed every time step
    # at AMR levels <= verbosity.  Set verbosity = 0 for no printing.
    #   (E.g. verbosity == 2 means print only on levels 1 and 2.)
    clawdata.verbosity = OUT['verbosity']

    # --------------
    # Time stepping:
    # --------------
    # if dt_variable==1: variable time steps used based on cfl_desired,
    # if dt_variable==0: fixed time steps dt = dt_initial will always be used.
    clawdata.dt_variable = True

    # Initial time step for variable dt.
    clawdata.dt_initial = 0.01 # If dt_variable==0 then dt=dt_initial for all steps:
    clawdata.dt_max     = 1e+99 # Max time step to be allowed if variable dt used:

    # Desired Courant number if variable dt used, and max to allow without
    # retaking step with a smaller dt:
    clawdata.cfl_desired = Param['cfl_target']
    clawdata.cfl_max     = Param['cfl_max']

    # Maximum number of time steps to allow between output times:
    clawdata.steps_max   = Param['max_iter']
 
    # ------------------
    # Method to be used:
    # ------------------
    # Order of accuracy:  1 => Godunov,  2 => Lax-Wendroff plus limiters
    clawdata.order = 2
    
    # Use dimensional splitting? (not yet available for AMR)
    clawdata.dimensional_split = 'unsplit'
    
    # For unsplit method, transverse_waves can be 
    #  0 or 'none'      ==> donor cell (only normal solver used)
    #  1 or 'increment' ==> corner transport of waves
    #  2 or 'all'       ==> corner transport of 2nd order corrections too
    clawdata.transverse_waves = 2

    # Number of waves in the Riemann solution:
    clawdata.num_waves = 3
    
    # List of limiters to use for each wave family:  
    # Required:  len(limiter) == num_waves
    # Some options:
    #   0 or 'none'     ==> no limiter (Lax-Wendroff)
    #   1 or 'minmod'   ==> minmod
    #   2 or 'superbee' ==> superbee
    #   3 or 'mc'       ==> MC limiter
    #   4 or 'vanleer'  ==> van Leer
    clawdata.limiter = [Param['limiter']]*3

    clawdata.use_fwaves = True    # True ==> use f-wave version of algorithms
    
    # Source terms splitting:
    #   src_split == 0 or 'none'    ==> no source term (src routine never called)
    #   src_split == 1 or 'godunov' ==> Godunov (1st order) splitting used, 
    #   src_split == 2 or 'strang'  ==> Strang (2nd order) splitting used,  not recommended.
    clawdata.source_split = 'godunov'

    # --------------------
    # Boundary conditions:
    # --------------------
    # Five cells close AVAC's second-order f-wave/static-yield stencil at
    # same-level patch interfaces.  Water and multilevel AMR retain the
    # established two-cell GeoClaw path because their relimiter is disabled.
    # AMRClaw consequently requires both base-grid axes to contain at least
    # ten cells for a single-level granular run.
    uses_positivity_relimit = (
        str(Rheol["model"]).strip() != "Water"
        and int(Param["refinement"]) == 1
    )
    clawdata.num_ghost = 5 if uses_positivity_relimit else 2

    # Choice of BCs at xlower and xupper:
    #   0 => user specified (must modify bcN.f to use this option)
    #   1 => AVAC one-way extrapolation (unchanged outflow; attempted inflow blocked)
    #   2 => periodic (must specify this at both boundaries)
    #   3 => solid wall for systems where q(2) is normal velocity
    if topo_source == 'real_world':
        clawdata.bc_lower[0] = Param['boundary']
        clawdata.bc_upper[0] = Param['boundary']
        clawdata.bc_lower[1] = Param['boundary']
        clawdata.bc_upper[1] = Param['boundary']
    else:
        clawdata.bc_lower[0] = Param['boundary_west']
        clawdata.bc_upper[0] = Param['boundary_east']
        clawdata.bc_lower[1] = Param['boundary_south']
        clawdata.bc_upper[1] = Param['boundary_north']

    # Specify when checkpoint files should be created that can be
    # used to restart a computation.
    clawdata.checkpt_style = 0

    if clawdata.checkpt_style == 0:
        # Do not checkpoint at all
        pass

    elif np.abs(clawdata.checkpt_style) == 1:
        # Checkpoint only at tfinal.
        pass

    elif np.abs(clawdata.checkpt_style) == 2:
        # Specify a list of checkpoint times.  
        clawdata.checkpt_times = [0.1,0.15]

    elif np.abs(clawdata.checkpt_style) == 3:
        # Checkpoint every checkpt_interval timesteps (on Level 1)
        # and at the final time.
        clawdata.checkpt_interval = 5

    # ---------------
    # AMR parameters:
    # ---------------
    amrdata = rundata.amrdata
    
    # maximum size of patches in each direction (matters in parallel):
    amrdata.max1d = 60

    # max number of refinement levels:
    amrdata.amr_levels_max = Param['refinement']

    # List of refinement ratios at each level (length at least mxnest-1)
    amrdata.refinement_ratios_x = [2,4,4]
    amrdata.refinement_ratios_y = [2,4,4]
    amrdata.refinement_ratios_t = [2,4,4]

    # Specify type of each aux variable in amrdata.auxtype.
    # This must be a list of length maux, each element of which is one of:
    #   'center',  'capacity', 'xleft', or 'yleft'  (see documentation).
    amrdata.aux_type = ['center', 'center']

    # Flag using refinement routine flag2refine rather than richardson error
    amrdata.flag_richardson = False    # use Richardson?
    amrdata.flag2refine     = True

    # steps to take on each level L between regriddings of level L+1:
    amrdata.regrid_interval = 3

    # width of buffer zone around flagged points:
    # (typically the same as regrid_interval so waves don't escape):
    amrdata.regrid_buffer_width  = 2

    # clustering alg. cutoff for (# flagged pts) / (total # of cells refined)
    # (closer to 1.0 => more small grids may be needed to cover flagged cells)
    amrdata.clustering_cutoff = 0.700000

    # print info about each regridding up to this level:
    amrdata.verbosity_regrid = 0  

    #  ----- For developers ----- 
    # Toggle debugging print statements:
    amrdata.dprint = False      # print domain flags
    amrdata.eprint = False      # print err est flags
    amrdata.edebug = False      # even more err est flags
    amrdata.gprint = False      # grid bisection/clustering
    amrdata.nprint = False      # proper nesting output
    amrdata.pprint = False      # proj. of tagged points
    amrdata.rprint = False      # print regridding summary
    amrdata.sprint = False      # space/memory output
    amrdata.tprint = False      # time step reporting each level
    amrdata.uprint = False      # update/upbnd reporting
    
    # More AMR parameters can be set -- see the defaults in pyclaw/data.py

    # == setregions.data values ==
    regions = rundata.regiondata.regions
    # to specify regions of refinement append lines of the form
    #  [minlevel,maxlevel,t1,t2,x1,x2,y1,y2]
    #regions.append([1, 1, 0., 1.e10, 925720,927160., 6451140.,6452155.])
    if use_zoom_output:
        regions.append([1, 3, 0., 1.e10, Refine['fine_dict']['xmin'], Refine['fine_dict']['xmax'], Refine['fine_dict']['ymin'], Refine['fine_dict']['ymax']])   
       
 

    # == setgauges.data values ==
    # for gauges append lines of the form  [gaugeno, x, y, t1, t2]
    # rundata.gaugedata.add_gauge()

    # gauges along x-axis:
    # gaugeno = 0
    # for r in np.linspace(-10, 10., 10):
    #     gaugeno = gaugeno+1
    #     x = r + .001  # shift a bit away from cell corners
    #     y = .001
     #    rundata.gaugedata.gauges.append([gaugeno, x, y, 0., 1e10])

    if Gauges['gauge_recording']:
        for jauge in Gauges['gauges']:
            gaugeno = jauge[0]
            x = jauge[1]
            y = jauge[2]
            rundata.gaugedata.gauges.append([gaugeno, x, y, 0., 1e10])




    ###############################
    #   fgmax_grids.data values   #  
    ###############################

    # set num_fgmax_val = 1 to save only max depth,
    #                     2 to also save max speed,
    #                     5 to also save max hs,hss,hmin
    rundata.fgmax_data.num_fgmax_val = 2  # Save depth and speed see https://www.clawpack.org/fgmax.html

    fgmax_grids = rundata.fgmax_data.fgmax_grids  # empty list to start

    # Now append to this list objects of class fgmax_tools.FGmaxGrid
    # specifying any fgmax grids.

    # Points on a uniform 2d grid:
    if ResultGrid:
        dx_fine = float(ResultGrid['cell_size'])
        dy_fine = dx_fine
    elif topo_source == 'real_world':
        dx_fine = Param['cell_size']
        dy_fine = dx_fine
    else:
        dx_fine = Param['dx']  # grid resolution at finest level
        dy_fine = Param['dy']
    fg = fgmax_tools.FGmaxGrid()
    fg.point_style = 2  # uniform rectangular x-y grid
    if ResultGrid:
        if int(ResultGrid['ncols']) < 2 or int(ResultGrid['nrows']) < 2:
            raise ValueError(
                "AVAC result_grid requires at least two centre samples along both x and y."
            )
        fg.x1 = float(ResultGrid['xllcenter'])
        fg.x2 = fg.x1 + (int(ResultGrid['ncols']) - 1) * dx_fine
        fg.y1 = float(ResultGrid['yllcenter'])
        fg.y2 = fg.y1 + (int(ResultGrid['nrows']) - 1) * dy_fine
    else:
        # Unlike FGout, GeoClaw FGmax ``point_style = 2`` interprets x1/x2
        # and y1/y2 as its first and last *sample points*, inclusively.
        # They must therefore be the finite-volume cell centres rather than
        # the computational edges.  Passing edges produces N+1 samples and
        # makes the QGIS maximum raster one cell wider than the AVAC domain.
        fg.x1 = clawdata.lower[0] + dx_fine / 2.0
        fg.x2 = clawdata.upper[0] - dx_fine / 2.0
        fg.y1 = clawdata.lower[1] + dy_fine / 2.0
        fg.y2 = clawdata.upper[1] - dy_fine / 2.0
    fg.dx = dx_fine
    fg.dy = dy_fine
    # A maximum-over-the-run product includes the initial release state.  In
    # particular, cells that immediately drain can attain their maximum at
    # t=0 and must not be omitted from the diagnostic.
    fg.tstart_max = 0.      # when to start monitoring max values
    fg.tend_max   = Param['t_max']       # when to stop monitoring max values
    # Peak values must be checked at every native solver step.  Reusing the
    # output-frame interval undersamples a fast front and imprints artificial
    # longitudinal bands in the maximum-depth raster.
    fg.dt_check   = 0.0
    # Start monitoring at level 1.  fgmax_frompatch retains values from the
    # finest grid that has covered each point, so this still prefers refined
    # data while avoiding holes/stale zeros wherever a transient level-2 patch
    # never exists.  Using amr_levels_max here made the summary product depend
    # on refinement coverage rather than only on the physical solution.
    fg.min_level_check = 1
    fg.arrival_tol = 1.e-2    # tolerance for flagging arrival

    fg.interp_method = 0      # 0 ==> pw const in cells, recommended
    fgmax_grids.append(fg)    # written to fgmax_grids.data

    if use_zoom_output:
        fine_nx = _whole_cell_count(
            Refine['fine_dict']['xmin'], Refine['fine_dict']['xmax'],
            Refine['fine_dict']['cell_size'], 'fine x',
        )
        fine_ny = _whole_cell_count(
            Refine['fine_dict']['ymin'], Refine['fine_dict']['ymax'],
            Refine['fine_dict']['cell_size'], 'fine y',
        )
        if fine_nx < 2 or fine_ny < 2:
            raise ValueError(
                "AVAC refined fixed-grid results require at least two cells along both x and y."
            )
        fg_zoom = fgmax_tools.FGmaxGrid()
        fg_zoom.point_style = 2  # uniform rectangular x-y grid
        fg_zoom.dx = Refine['fine_dict']['cell_size']
        fg_zoom.dy = fg_zoom.dx
        # FGmax endpoints are sample centres (not cell edges); retain the
        # fine QGIS footprint exactly when its samples are rasterized.
        fg_zoom.x1 = Refine['fine_dict']['xmin'] + fg_zoom.dx / 2.0
        fg_zoom.x2 = Refine['fine_dict']['xmax'] - fg_zoom.dx / 2.0
        fg_zoom.y1 = Refine['fine_dict']['ymin'] + fg_zoom.dy / 2.0
        fg_zoom.y2 = Refine['fine_dict']['ymax'] - fg_zoom.dy / 2.0
        fg_zoom.tstart_max = 0.      # when to start monitoring max values
        fg_zoom.tend_max   = Param['t_max']       # when to stop monitoring max values
        fg_zoom.dt_check   = 0.0
        fg_zoom.min_level_check = 1
        fg_zoom.arrival_tol = 1.e-2    # tolerance for flagging arrival

        fg_zoom.interp_method = 0      # 0 ==> pw const in cells, recommended
        fgmax_grids.append(fg_zoom)    # written to fgmax_grids.data
        

 


    # == fgout_grids.data values ==
    # NEW IN v5.9.0
    # Set rundata.fgout_data.fgout_grids to be a list of
    # objects of class clawpack.geoclaw.fgout_tools.FGoutGrid:
    fgout_grids = rundata.fgout_data.fgout_grids  # empty list initially

    fgout               = fgout_tools.FGoutGrid()
    fgout.fgno          = 1              # for listing the files see doc
    fgout.point_style   = 2       # will specify a 2d grid of points
    fgout.output_format = OUT['output_format']  # 4-byte, float32
    if ResultGrid:
        fgout.nx = int(ResultGrid['ncols'])
        fgout.ny = int(ResultGrid['nrows'])
        fgout.x1 = float(ResultGrid['xllcenter']) - dx_fine / 2.0
        fgout.x2 = fgout.x1 + fgout.nx * dx_fine
        fgout.y1 = float(ResultGrid['yllcenter']) - dy_fine / 2.0
        fgout.y2 = fgout.y1 + fgout.ny * dy_fine
    elif topo_source == 'real_world':
        fgout.nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['cell_size'], 'x')
        fgout.ny = _whole_cell_count(DEM['ymin'], DEM['ymax'], Param['cell_size'], 'y')
        fgout.x1 = DEM['xmin']
        fgout.x2 = DEM['xmax']
        fgout.y1 = DEM['ymin']
        fgout.y2 = DEM['ymax']
    else:
        fgout.nx = _whole_cell_count(DEM['xmin'], DEM['xmax'], Param['dx'], 'x')
        fgout.ny = _whole_cell_count(DEM['ymin'], DEM['ymax'], Param['dy'], 'y')
        fgout.x1 = DEM['xmin']
        fgout.x2 = DEM['xmax']
        fgout.y1 = DEM['ymin']
        fgout.y2 = DEM['ymax']
    fgout.tstart = 0.
    fgout.tend   = Param['t_max']
    fgout.nout   = Movie['n_out']
    fgout_grids.append(fgout)    # written to fgout_grids.data

    if use_zoom_output:
        fgout_zoom               = fgout_tools.FGoutGrid()
        fgout_zoom.fgno          = 2
        fgout_zoom.point_style   = 2
        fgout_zoom.output_format = OUT['output_format']
        fgout_zoom.nx = _whole_cell_count(
            Refine['fine_dict']['xmin'], Refine['fine_dict']['xmax'],
            Refine['fine_dict']['cell_size'], 'fine x',
        )
        fgout_zoom.ny = _whole_cell_count(
            Refine['fine_dict']['ymin'], Refine['fine_dict']['ymax'],
            Refine['fine_dict']['cell_size'], 'fine y',
        )
        fgout_zoom.x1 = Refine['fine_dict']['xmin']
        fgout_zoom.x2 = Refine['fine_dict']['xmax']
        fgout_zoom.y1 = Refine['fine_dict']['ymin']
        fgout_zoom.y2 = Refine['fine_dict']['ymax']
        fgout_zoom.tstart = 0.
        fgout_zoom.tend   = Param['t_max']
        fgout_zoom.nout   = Movie['n_out']
        fgout_grids.append(fgout_zoom)   # grille zoom — fgout0002.*

    #########################
    # setprob data parameters
    # Order must match read(7,*) statements in setprob.f90
    # to do: type:init

    probdata = rundata.new_UserData(name='probdata',fname='setprob.data')

    # ------------------------------------------------------------------
    # Rheological parameters — mu and xi can be scalars or lists.
    # If lists, z_breaks (n_zones-1 altitudes in m, ascending) must also
    # be provided in the YAML under rheology.z_breaks.
    #
    # Example (two zones separated at z = 2 300 m):
    #   mu:       [0.21, 0.35]
    #   xi:       [1200, 2000]
    #   z_breaks: [2300.0]
    # ------------------------------------------------------------------
    mu_vals  = Rheol["mu"]       if isinstance(Rheol["mu"], list)  else [Rheol["mu"]]
    xi_vals  = Rheol["xi"]       if isinstance(Rheol["xi"], list)  else [Rheol["xi"]]
    C_vals   = Rheol["C"]        if isinstance(Rheol["C"], list)  else [Rheol["C"]]
    z_breaks = Rheol.get("z_breaks", [])
    n_zones  = len(mu_vals)
    assert len(xi_vals) == n_zones, \
        f"rheology: mu and xi must have the same number of entries (got {len(mu_vals)} and {len(xi_vals)})"
    assert len(z_breaks) == n_zones - 1, \
        f"rheology: z_breaks must have {n_zones - 1} entry/entries for {n_zones} zone(s) (got {len(z_breaks)})"
    if n_zones > 1:
        assert all(z_breaks[k] < z_breaks[k+1] for k in range(len(z_breaks)-1)), \
            "rheology: z_breaks must be strictly ascending"

    probdata.add_param('rho',    Rheol["rho"],           'snow density (kg/m3)')
    #probdata.add_param('C',      Rheol.get("C", 0.0),   'cohesion (Pa)')
    probdata.add_param('u_cr',   Rheol.get("u_cr", 0.0),'legacy unused compatibility value (m/s)')
    probdata.add_param('velocity_depth_threshold',
                       Param.get("velocity_depth_threshold", 0.05),
                       'minimum depth for a reported velocity (m)')
    probdata.add_param('n_zones', n_zones,               'number of altitude rheology zones')
    for k, z in enumerate(z_breaks):
        probdata.add_param(f'z_break_{k}', float(z),
                           f'altitude lower bound of zone {k+1} (m)')
    for k, mv in enumerate(mu_vals):
        probdata.add_param(f'mu_{k}', float(mv),
                           f'Coulomb mu in zone {k} (z < {z_breaks[k]:.1f} m)' if k < n_zones-1
                           else f'Coulomb mu in zone {k} (z >= {z_breaks[-1]:.1f} m)' if n_zones > 1
                           else 'Coulomb friction coefficient (uniform)')
    for k, xv in enumerate(xi_vals):
        probdata.add_param(f'xi_{k}', float(xv),
                           f'Voellmy xi in zone {k} (m/s2)')
    for k, xv in enumerate(C_vals):
        probdata.add_param(f'C_{k}', float(xv),
                           f'cohesion in zone {k} (Pa)')
    probdata.add_param('constitutive_model', Rheol["model"],
                       'constitutive model (Coulomb, Voellmy, cohesive_Voellmy)')
    probdata.add_param('type_init', Files['type_init'],
                       'init type: 0=qinit.f90 (synthetic topo), 1=qinit raster file (real world topo)')
    if Files['type_init'] == 0:
        probdata.add_param('theta',        Release["theta"],  'theta')
        probdata.add_param('free_surface', Release["free_surface"],  'free surface shape')
        probdata.add_param('d0',           Release["d0"],  'initial depth')
        probdata.add_param('xb',           Release["xb"],  'back wall position')


    return rundata
    # end of function setrun
    # ----------------------

 

#-------------------
def setgeo(rundata):
#-------------------
    """
    Set GeoClaw specific runtime parameters.
    For documentation see ....
    """

    try:
        geo_data = rundata.geo_data
    except:
        print("*** Error, this rundata has no geo_data attribute")
        raise AttributeError("Missing geo_data attribute")


            
    # == Physics ==
    geo_data.gravity           = 9.81
    geo_data.coordinate_system = 1 #Cartesian
    geo_data.earth_radius      = 6367.5e3

    # == correctif val d'isère
    rundata.topo_data.topo_missing = DEM['nodata_value']

    # == Forcing Options
    geo_data.coriolis_forcing = False

    # == Algorithm and Initial Conditions ==
    # sea_level must be well BELOW the minimum bed elevation in the run-out zone.
    # GeoClaw's filpatch.f90 initialises new fine-grid patches by setting
    # eta_coarse = sea_level for any DRY coarse cell, then h_fine = max(eta-b, 0).
    # With sea_level=0 and b<0 in the run-out zone, filpatch would flood every
    # new fine patch with h = -b (up to 30 m), injecting O(2400 m^3) of spurious
    # mass into a domain that should start with 20 m^3.  Setting sea_level to
    # a very negative value ensures h_fine = max(sea_level - b, 0) = 0 for all
    # cells in the run-out zone, keeping them correctly dry.
    geo_data.sea_level           = -1.0e4  # must be << min(b) ≈ -30 m
    geo_data.dry_tolerance       = Param['dry_limit']
    # AVAC does not impose a solver-level velocity ceiling.  GeoClaw retains
    # ``speed_limit`` for water applications, but a finite default would clip
    # the conserved avalanche momentum before the rheology and diagnostics
    # are evaluated.  Use the same effectively infinite value as the ISeeSnow
    # validation workflow so all AVAC runs are uncapped.
    geo_data.speed_limit         = 1.0e99
    geo_data.friction_forcing    = True
    geo_data.manning_coefficient = 0.025
    geo_data.friction_depth      = 1.0e6   # apply friction at all depths

    # Refinement data
    # For granular flows, flag ONLY moving cells (speed > threshold).
    # wave_tolerance is set very large to disable the wave-height criterion:
    # with topography of O(metres), every wet cell would otherwise be flagged,
    # including the stopped deposit.  Refining the deposit halves the Coulomb
    # threshold (thresh = mu*cos(theta)*dx) without halving the inter-cell
    # height differences, causing the stopping criterion to fail on the fine grid.
    refinement_data                = rundata.refinement_data
    refinement_data.wave_tolerance = 1.e6   # disabled: use speed criterion only
    # One entry is required for every transition from level L to L+1.
    # A single value silently limits speed-based refinement to level 2 even
    # when ``amr_levels_max`` requests additional levels.
    refinement_data.speed_tolerance = [0.05] * max(1, int(Param['refinement']) - 1)
    refinement_data.deep_depth     = 1e2
    refinement_data.max_level_deep = 3
    refinement_data.variable_dt_refinement_ratios = True

    # == settopo.data values ==
    topo_data = rundata.topo_data
    topo_file = str(topo_dir / Files['topofile']) # for topography, append lines of the form
    topo_type = Files['type_dem'] 
    topo_data.topofiles.append([topo_type, 1, 3, 0., 1.e10, topo_file]) #    [topotype, minlevel, maxlevel, t1, t2, fname]
    if Refine['topo_refinement']:
        topo_data.topofiles.append([topo_type, 1, 3, 0., 1.e10, str(topo_dir / Refine['finer_dem'])])

    # == setdtopo.data values ==
    dtopo_data = rundata.dtopo_data
    # for moving topography, append lines of the form :   (<= 1 allowed for now!)
    #   [topotype, minlevel,maxlevel,fname]

    # == setqinit.data values ==
    if Files['type_init'] > 0:
        rundata.qinit_data.qinit_type = Files['type_init'] 
        rundata.qinit_data.qinitfiles = []
        # for qinit perturbations, append lines of the form: (<= 1 allowed for now!)
        initial_condition_file = Files['initiation_file']
        rundata.qinit_data.qinitfiles.append([1, 2, initial_condition_file]) #   [minlev, maxlev, fname]

    # == setfixedgrids.data values ==
    #fixedgrids = rundata.fixed_grid_data.fixedgrids
    # for fixed grids append lines of the form
    # [t1,t2,noutput,x1,x2,y1,y2,xpoints,ypoints,\
    #  ioutarrivaltimes,ioutsurfacemax]

    return rundata
    # end of function setgeo
    # ----------------------



if __name__ == '__main__':
    # Set up run-time parameters and write all data files.
    import sys
    rundata = setrun(*sys.argv[1:])
    rundata.write()
