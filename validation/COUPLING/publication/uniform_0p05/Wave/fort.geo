  
 --------------------------------------------
 Physics Parameters:
 -------------------
    gravity:   9.8100000000000005     
    density water:   1025.0000000000000     
    density air:   1.1499999999999999     
    ambient pressure:   101300.00000000000     
    earth_radius:   6367500.0000000000     
    coordinate_system:           1
    sea_level:  -10000.000000000000     
  
    coriolis_forcing: F
    theta_0:   0.0000000000000000     
    friction_forcing: F
    manning_coefficient: not used
    friction_depth: not used
  
    dry_tolerance:   1.0000000000000000E-004
  
 --------------------------------------------
 Refinement Control Parameters:
 ------------------------------
    wave_tolerance:   1000000000000.0000     
    speed_tolerance:
    Variable dt Refinement Ratios: T
 
  
 --------------------------------------------
 SETDTOPO:
 -------------
    num dtopo files =            0
  
 --------------------------------------------
 SETTOPO:
 ---------
    mtopofiles =            1
    
    /Users/cmgotelli/Desktop/AVAC-QGIS/validation/COUPLING/publication/uniform_0p05/Topo/topography.asc                                                   
   itopotype =            3
   mx =           44   x = (  -7.5000000000000011E-002 ,   2.0750000000000002      )
   my =           24   y = (  -7.5000000000000011E-002 ,   1.0750000000000000      )
   dx, dy (meters/degrees) =    5.0000000000000003E-002   5.0000000000000003E-002
  
 Ranking of topography files  (including topo_for_dtopo) finest to coarsest: 
    (filenumber is order they appear in setrun.py, topofiles first)
  
rank =   1  filenumber =   1  dx*dy =     0.250000E-02
  
  
 --------------------------------------------
 SETQINIT:
 -------------
 /Users/cmgotelli/Desktop/AVAC-QGIS/validation/COUPLING/publication/uniform_0p05/Wave/initial_state.xyz                                                
   
 Reading qinit data from
 /Users/cmgotelli/Desktop/AVAC-QGIS/validation/COUPLING/publication/uniform_0p05/Wave/initial_state.xyz                                                
   
  
 --------------------------------------------
 Multilayer Parameters:
 ----------------------
    check_richardson: T
    richardson_tolerance:  0.94999999999999996     
    eigen_method:           4
    inundation_method:           2
    dry_tolerance:   1.0000000000000000E-004
