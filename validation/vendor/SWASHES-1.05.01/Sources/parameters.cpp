/**
 * @file parameters.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2026)
 * @author Rougier Maxime <maximerougier01@gmail.com> (2022)
 * @version 1.05.01
 * @date 2026-03-17
 *
 * @brief Gets parameters
 * @details 
 * Reads the parameters, checks their values, returns the use if needed.
 *
 * @copyright License Cecill-V2 \n
 * <http://www.cecill.info/licences/Licence_CeCILL_V2-en.html>
 *
 * (c) CNRS - Universite d'Orleans - INRA (France)
 */
/*
 * This file is part of SWASHES software.
 * <https://sourcesup.renater.fr/projects/swashes/>
 *
 * SWASHES = Shallow-Water Analytic Solutions for Hydraulic and
 * Environmental Studies.
 * This software is a computer program whose purpose is to compute analytic
 * solutions for Shallow-Water equations.
 *
 * LICENSE
 *
 * This software is governed by the CeCILL license under French law and
 * abiding by the rules of distribution of free software. You can use,
 * modify and/ or redistribute the software under the terms of the CeCILL
 * license as circulated by CEA, CNRS and INRIA at the following URL
 * <http://www.cecill.info>.
 *
 * As a counterpart to the access to the source code and rights to copy,
 * modify and redistribute granted by the license, users are provided only
 * with a limited warranty and the software's author, the holder of the
 * economic rights, and the successive licensors have only limited
 * liability.
 *
 * In this respect, the user's attention is drawn to the risks associated
 * with loading, using, modifying and/or developing or reproducing the
 * software by the user in light of its specific status of free software,
 * that may mean that it is complicated to manipulate, and that also
 * therefore means that it is reserved for developers and experienced
 * professionals having in-depth computer knowledge. Users are therefore
 * encouraged to load and test the software's suitability as regards their
 * requirements in conditions enabling the security of their systems and/or
 * data to be ensured and, more generally, to use and operate it in the
 * same conditions as regards security.
 *
 * The fact that you are presently reading this means that you have had
 * knowledge of the CeCILL license and that you accept its terms.
 *
 ******************************************************************************/

#include "parameters.hpp"

Parameters::Parameters(int argc, char ** argv){
	
	/**
	 * @details	 
	 * Checks the arguments
	 * @param[in] argc number of arguments
	 * @param[in] argv value of the arguments
	 * @warning The number of cells in x must be positive!
	 * @warning The number of cells in y must be positive!
	 * @par Modifies 
	 * Parameters#choicedim, Parameters#choicetype, Parameters#choicedomain, Parameters#choice 
	 * with the values given in argument. 
	 * @note If the arguments are incompatible, the code will exit with failure termination code.
	 */		
	
	ny_ex=0;
	if (argc!=6 && argc !=7){ // the number of arguments is wrong
		help();
		exit(EXIT_FAILURE);
	}
	else {
		choicedim = atof(argv[1]);
		if ((abs(1-choicedim)<EPSILON || abs(1.5-choicedim)<EPSILON) && argc != 6){ // 1d but wrong number of arguments
			help();
			exit(EXIT_FAILURE);
		}
		else if (abs(2-choicedim)<EPSILON) { // 2d but wrong number of arguments
			if (argc !=7){
				help();
				exit(EXIT_FAILURE);
			}
			else{
				ny_ex = atoi(argv[6]);
				if (ny_ex<=0){ 
					cerr << "The number of cells in y must be positive!" << endl;
					exit(EXIT_FAILURE);
				}
			}
		}
		nx_ex = atoi(argv[5]);
		if (nx_ex<=0){ 
			cerr << "The number of cells in x must be positive!" << endl;
			exit(EXIT_FAILURE);
		}
		choicetype = atoi(argv[2]);
		choicedomain = atoi(argv[3]);
		choice = atoi(argv[4]);
		
	}
}

Parameters::~Parameters(){
}

void Parameters::help() const{
	
	/**
	 * @details	 
	 * Prints how to use the code.
	 */
	
	cerr << VERSION << endl;
	cerr << endl;
	cerr << "USE: swashes dimension type domain choice NumberCellx [NumberCelly]" << endl;
	cerr << endl;
	cerr << "Available solutions: " << endl;
	cerr << "DIMENSION = 1" << endl;
	cerr << " ******* type = 0 Inclined plane *************************************************** " << endl;
	cerr << " - - - - domain = 1 L=10 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: supercritical flow [2]" << endl;
	cerr << " - - - - domain = 2 L=20 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: transient solution [3]" << endl;
	cerr << "	2: periodic wave [3]" << endl;
	cerr << " ******* type = 1 Bumps ************************************************************ " << endl;
	cerr << " - - - - domain = 1 L=25 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow [1]" << endl;
	cerr << "	2: transcritical flow without shock (sub- to super-critical) [1]" << endl;
	cerr << "	3: transcritical flow with shock (sub- to super- to sub-critical) [1]" << endl;
	cerr << "	4: lake at rest with an immersed bump [1]" << endl;
	cerr << "	5: lake at rest with an emerged bump [1]" << endl;
	cerr << " ******* type = 2 MacDonald ******************************************************** " << endl;
	cerr << " - - - - domain = 1 Long channel: L=1000 m - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow (Darcy-Weisbach) [1]               2: (Manning) [1]" << endl;
	cerr << "	3: supercritical flow (Darcy-Weisbach) [1]             4: (Manning) [1]" << endl;
	cerr << "	5: sub- to super-critical flow (Darcy-Weisbach) [1]    6: (Manning) [1]" << endl;
	cerr << "	7: super- to sub-critical flow (Darcy-Weisbach) [1]    8: (Manning) [1]" << endl;
	cerr << " - - - - domain = 2 Short channel: L=100 m - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	2: smooth transition and shock (Manning) [1]" << endl;
	cerr << "	4: supercritical flow (Manning) [1]" << endl;
	cerr << "	6: sub- to super-critical flow (Manning)  [1]" << endl;
	cerr << " - - - - domain = 3 Very long, undulating, periodic channel: L=5000 m - - - - - - - - " << endl;
	cerr << "	2: subcritical flow (Manning) [1]" << endl;
	cerr << " - - - - domain = 4 Long channel: L=1000 m with rain - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow (Darcy-Weisbach) [1]               2: (Manning) [1]" << endl;
	cerr << "	3: supercritical flow (Darcy-Weisbach) [1]             4: (Manning) [1]" << endl;
	cerr << " - - - - domain = 5 Long channel: L=1000 m with diffusion - - - - - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow [1]" << endl;
	cerr << "	2: supercritical flow [1]" << endl;
	cerr << " ******* type = 3 Dam breaks ******************************************************* " << endl;
	cerr << " - - - - domain = 1 L=10 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: dam break on a wet domain without friction (Stoker's solution) [1]" << endl;
	cerr << "	2: dam break on a dry domain without friction (Ritter's solution) [1]" << endl;
	cerr << "	3: dam break on a dry domain with friction (Dressler's solution) [1]" << endl;
	cerr << " - - - - domain = 2 L=20 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: self-similar dam break on a flat bottom with a laminar friction [4]" << endl;
	cerr << "	2: self-similar dam break on an inclined plane with a laminar friction [4]" << endl;
	cerr << " ******* type 4 = Oscillations ***************************************************** " << endl;
	cerr << " - - - - domain = 1 L=4 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: planar surface in a parabola without friction (Thacker's solution) [1]" << endl;
	cerr << " - - - - domain = 2 L=10000 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: planar surface in a parabola with a linear friction (Sampson's solution) [1]" << endl;
	cerr << " ******* type 5 = Bedload (Exner) ************************************************** " << endl;
	cerr << " - - - - domain = 1 L=15 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: Grass eq. [5]" << endl;
	cerr << "	2: Meyer-Peter & Muler eq. [5]" << endl;
	cerr << " ******* type = 6 Sluice gates ***************************************************** " << endl;
	cerr << " - - - - domain = 1 L=10 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - -  " << endl;
	cerr << "	1: sluice gate opening on a dry domain [6]" << endl;
	cerr << "	2: sluice gate opening on a wet domain with free flow and low h_right = 0.01 * gate_size [6]" << endl;
	cerr << "	3: sluice gate opening on a wet domain with free flow and h_right = gate_size [6]" << endl;
	cerr << " ******* type = 7 Dam break with a step ******************************************** " << endl;
	cerr << " - - - - domain = 1 L=20 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - -  " << endl;
	cerr << "	1: dam break problem with a discontinuous topography [6]" << endl;
	cerr << " ******* type = 8 Solute model ***************************************************** " << endl;
	cerr << " - - - - domain = 1 L=1000 m  - - - - - - - - - - - - - - - - - - - - - - - - - - - -  " << endl;
	cerr << "	1: no degradation with initial dissolved concentration [7]" << endl;
	cerr << "	2: no degradation with boundary dissolved concentration [7]" << endl;
	cerr << "	3: degradation with initial dissolved concentration [7]" << endl;
	cerr << "	4: degradation with boundary dissolved concentration [7]" << endl;
	cerr << " ******* type = 9 Mobile rain ****************************************************** " << endl;
	cerr << " - - - - domain = 1 L=18000 m  - - - - - - - - - - - - - - - - - - - - - - - - - - -  " << endl;
	cerr << "	1: rain with the same velocity as the flow [8]" << endl;
	cerr << "	2: rain with a velocity smaller than the flow [8]" << endl;
	cerr << "	3: rain with a velocity larger than the flow [8]" << endl;
	cerr << endl;
	cerr << "DIMENSION = 1.5 (pseudo 2D)" << endl;
	cerr << " ******* type = 1 MacDonald PSEUDO 2D ********************************************** " << endl;
	cerr << " - - - - domain = 1 Rectangular short channel, shape B1: L=200 m - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow [1]" << endl;
	cerr << "	2: supercritical flow [1]" << endl;
	cerr << "	3: smooth transition [1]" << endl;
	cerr << "	4: hydraulic jump [1]" << endl;
	cerr << " - - - - domain = 2 Trapezoidal long channel, shape B2: L=400 m - - - - - - - - - - " << endl;
	cerr << "	1: subcritical flow [1]" << endl;
	cerr << "	2: smooth transition and hydraulic jump [1]" << endl;
	cerr << endl;
	cerr << "DIMENSION = 2" << endl;
	cerr << " ******* type 1 = Oscillations ***************************************************** " << endl;
	cerr << " - - - - domain = 1 L=l=4 m - - - - - - - - - - - - - - - - - - - - - - - - - - - - " << endl;
	cerr << "	1: radially-symmetrical paraboloid (Thacker's solution) [1]" << endl;
	cerr << "	2: planar surface in a paraboloid (Thacker's solution) [1]" << endl;
	cerr << " ******* type 2 = Dam in 2D ******************************************************** " << endl;
	cerr << " - - - - domain = 1 L=25 m  l=10 m - |!| Use at least 50 points" << endl;
	cerr << "	1: dam with a parabolic shape [6]" << endl;
	cerr << " - - - - domain = 2 L=10 m  l=10 m - |!| Use at least 20 points" << endl;
	cerr << "	1: cross shaped Dam with a higher central ring [6]" << endl;
	cerr << " ******* type 3 = Spherical geometry************************************************ " << endl;
	cerr << " - - - - domain = 1 Earth like parameters with alpha=0 rad - - - - - - - - - - - - - " << endl;
	cerr << "	1: global steady state nonlinear zonal geostrophic flow [6]" << endl;
	cerr << " - - - - domain = 2 Earth like parameters with alpha=0.406 rad - - - - - - - - - - - " << endl;
	cerr << "	1: global steady state nonlinear zonal geostrophic flow [6]" << endl;
	cerr << "--------------------------------------------------------------------------------------" << endl;
	cerr << endl;
	cerr << "for more details, see "<< endl;
	cerr << " [1] 'SWASHES: a compilation of Shallow Water Analytic Solutions for Hydraulic and Environmental Studies', " << endl;
	cerr << "   O. Delestre, C. Lucas, P.-A. Ksinant, F. Darboux, C. Laguerre, T.N.T. Vo, F. James, S. Cordier"<< endl;
	cerr << "   International Journal of Numerical Methods in Fluids, 2013, 72(3): 269-300"<< endl;
	cerr << "   DOI: 10.1002/fld.3741 . URL: https://hal.archives-ouvertes.fr/hal-00628246"<< endl;
	cerr << " [2] 'A limitation of the hydrostatic reconstruction technique for Shallow Water equations', " << endl;
	cerr << "   O. Delestre, S. Cordier, F. Darboux, F. James" << endl;
	cerr << "   Comptes Rendus Mathématique, 2012,  350(13-14):677– 681" << endl;
	cerr << "   DOI: 10.1016/J.crma.2012.08.004, https://hal.science/hal-00710654"<< endl;
	cerr << " [3] 'Etude et programmation de la solution analytique du Swash', " << endl;
	cerr << "   N. Gaveau" << endl;
	cerr << "   Rapport de stage 1A, École Normale Supérieure de Rennes, 2015" << endl;
	cerr << "   https://hal.inrae.fr/hal-04959018 (In French)"<< endl;
	cerr << " [4] 'Self-similar solutions for dam breaks computed by SWASHES',"<<endl;
	cerr << "   F. James, C. Lucas" <<endl;
	cerr << "   Working paper, 2014" <<endl;  
	cerr << "   https://hal.science/hal-05549326" << endl;
	cerr << " [5] 'Bedload solutions computed by SWASHES',"<<endl;
	cerr << "   C Lucas" << endl;
	cerr << "   Working paper, 2026" << endl;
	cerr << "   https://hal.science/hal-05555922" << endl;
	cerr << " [6] 'Addition of 8 analytical solutions to the SWASHES software', " << endl;
	cerr << "   M. Rougier" << endl;
	cerr << "   Research report, Institut Denis Poisson - Université d’Orléans, 2022" << endl;  
	cerr << "   https://hal.science/hal-03762587"<< endl;
	cerr << " [7] 'Modeling solute transport in rivers: Analytical and numerical solutions', " <<endl;
	cerr << "   M. Bey-Zekkoub, P. Tassi, C. Lucas, N. Chhim" << endl;
	cerr << "   Environmental Modelling & Software, 2025, 193:106580" << endl;
	cerr << "   DOI: https://doi.org/10.1016/j.envsoft.2025.106580 "<< endl;
	cerr << " [8] 'Analytic solutions to the kinematic wave model with mobile rain and comparisons with the Shallow Water equations', " << endl;
	cerr << "   O. Delestre, C. Lucas" << endl;
	cerr << "   In Tanguy, J.-M., editor, Analytical solutions in free surface hydraulics. Wiley" << endl;
	cerr << "   Provisional titles, in preparation, 2026"<< endl;
	cerr << endl;
}

int Parameters::get_nxex() const {
	
	/**
	 * @details	 
	 * @return The number of cells in x.
	 */
	
	return nx_ex;
}

int Parameters::get_nyex() const {
	
	/**
	 * @details	 
	 * @return The number of cells in y.
	 */
	
	return ny_ex;
}

int Parameters::get_choice() const {
	
	/**
	 * @details	 
	 * @return The chosen solution.
	 */
	
	return choice;
}

SCALAR Parameters::get_choicedim() const {
	
	/**
	 * @details	 
	 * @return The dimension of the solution.
	 */
	
	return choicedim;
}

int Parameters::get_choicetype() const {
	
	/**
	 * @details	 
	 * @return The type of the solution.
	 */
	
	return choicetype;
}

int Parameters::get_choicedomain() const {
	
	/**
	 * @details	 
	 * @return The domain of the solution.
	 */
	
	return choicedomain;
}

