
# Makefile for Clawpack code in this directory.
# This version only sets the local files and frequently changed
# options, and then includes the standard makefile pointed to by CLAWMAKE.
CLAWMAKE = $(CLAW)/clawutil/src/Makefile.common

# See the above file for details and a list of make options, or type
#   make .help
# at the unix prompt.


# Adjust these variables if desired:
# ----------------------------------

CLAW_PKG = geoclaw                  # Clawpack package to use
EXE = xgeoclaw                 # Executable to create
SETRUN_FILE = setrun.py        # File containing function to make data
OUTDIR = _output               # Directory for output
SETPLOT_FILE = setplot.py      # File containing function to set plots
PLOTDIR = _plots               # Directory for plots

# Environment variable FC should be set to fortran compiler, e.g. gfortran

# Compiler flags can be specified here or set as an environment variable
# LAPACK/BLAS are link libraries, not compiler flags.  Keep OpenMP at link
# time too: Clawpack objects are compiled with it.
FFLAGS ?= -O2 -fopenmp
# The shared GeoClaw step2 source contains an AVAC-only conditional. WAVE
# preprocesses that source without defining the AVAC macro, retaining the
# upstream relimiter setting.
FFLAGS += -cpp
LFLAGS ?= -fopenmp -llapack -lblas
OMP_NUM_THREADS = 8


# ---------------------------------
# package sources for this program:
# ---------------------------------

GEOLIB = $(CLAW)/geoclaw/src/2d/shallow
include $(GEOLIB)/Makefile.geoclaw

# ---------------------------------------
# package sources specifically to exclude
# (i.e. if a custom replacement source 
#  under a different name is provided)
# ---------------------------------------

EXCLUDE_MODULES = \

EXCLUDE_SOURCES = \
	$(GEOLIB)/src2.f90 \
	$(GEOLIB)/b4step2.f90 \
	$(GEOLIB)/bc2amr.f90 \

# ----------------------------------------
# List of custom sources for this program:
# ----------------------------------------

MODULES = \
	./internal_inflow_module.f90 \
	./hydraulic_bc_module.f90 \
	./fgout_module.f90 \
	./qinit_module.f90 \


SOURCES = \
  ./setprob.f90 \
  ./src2.f90 \
  ./b4step2.f90 \
  ./bc2amr.f90 \
  $(CLAW)/riemann/src/rpn2_geoclaw.f \
  $(CLAW)/riemann/src/rpt2_geoclaw.f \
  $(CLAW)/riemann/src/geoclaw_riemann_utils.f \

#-------------------------------------------------------------------
# Include Makefile containing standard definitions and make options:
include $(CLAWMAKE)

# Construct the topography data
.PHONY: topo all
topo:
	python maketopo.py

all: 
	$(MAKE) topo
	$(MAKE) .plots
	$(MAKE) .htmls
