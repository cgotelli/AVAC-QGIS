/**
 * @file step.cpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2024)
 * @version 1.04.02
 * @date 2024-10-24
 *
 * @brief Computes dam break with a step solutions
 * @details
 * Analytic solution: dam break with a step without friction, see \cite Han14.
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

#include "step.hpp"

Step::Step(Parameters& par) :Solution(par) {

	/**
	 * @details
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex, Step#h_left, Step#h_right, Step#step_size,
	 * Step#solu, Step#Cc, Step#xdam
	 * to have the step opening configuration.
	 */
	L = 20.;
	xdam = L / 2.;
	dx_ex = L / NX_EX;
	T = 1.;


	//we also initialize a few variable that will be usefull later:
	h_1 = 0.;
	h_2 = 0.;
	u_1 = 0.;
	u_2 = 0.;

	for (int i = 0; i <= NX_EX; i++) {
		xex[i] = (i - 0.5) * dx_ex;
	}

	if (par.get_choice() == 1) {
		// Case where: h_l>h_r+step_size and u_l=u_r=0
		
		//WARNING: Since this solution required calculations we didn't implement in SWASHES for simplicity's sake,
		//the values of h_left, u_left, h_right and u_right must not be changed. 
		//See the function compute for more details.
		h_left = 4.;
		h_right = 1.;
		u_left = 0.;
		u_right = 0.;
		step_size = 1.;
		solu = 1.;
		for (int i = 0; i <= NX_EX; i++) {
			if (xex[i] <= xdam) {
				zex[i] = 0.;
			}
			else {
				zex[i] = step_size;
			}
		}
		head(par, "Step", "h_l>h_r+step_size and u_l=u_r=0");
		param(L, xdam, step_size, h_left, h_right,u_left,u_right, dx_ex, T);
	}
	else {//nothing for now

	}
}


Step::~Step() {

}


void Step::compute() {

	/**
	 * @details
	 * Computes the chosen step solution.
	 * @par Modifies
	 * Solution#hex.
	 */
	if (solu == 1) {

		//h_1 and h_2 are linked to h_L and h_R respectively by a rarefaction wave for h_1 and a shock wave for h_2.
		//Using the locus of those 2 waves this gives us a system of equation to find the points compatible 
		//with the ideal steady step transition. 
		//Those heights can be found using solving methods such as Newton-Raphson. 
		//We didn't implement it in this code to keep it light.
		//Here is a sagemath code one can use to find the values of h_1 and h_2 in other cases:
		/*	reset()
			hr = 1
			hl = 4
			g = 9.81
			z = 1
			var('h1,h2')
			solve([ h1*(2*sqrt(g*hl)-2*sqrt(g*h1))-h2*sqrt(g/2*(h2-hr)^2*(1/h2+1/hr))==0, (2*sqrt(g*hl)-2*sqrt(g*h1))^2/2+g*h1-g/4*(h2-hr)^2*(1/h2+1/hr)-g*(h2+z)==0], h1,h2)*/
		
		h_1 = 3.0923;
		h_2 = 1.8999;
		//Since the state U_1 is in the rarefaction wave (in the first characteristic field) locus, we use it to find u_1.
		u_1 = r1(h_1, h_left, 0.0);

		//There is a constant discharge at the step: h_1*u_1=h_c*u_c
		u_2 = h_1 * u_1 / h_2;
		for (int i = 0; i <= NX_EX; i++) { //looks at all the different cases
			if (xex[i] <= xdam) {// we check on which side of the dam we are

				//water height of the left side rarefaction wave:
				SCALAR h_wave = pow(2 * sqrt(GRAV * h_left) - (xex[i] - xdam) / T, 2.) / (9. * GRAV);
				if (h_wave >= h_left) {
					hex[i] = h_left;
					uex[i] = 0.;
				}
				else if (h_wave >= h_1) {
					hex[i] = h_wave;
					uex[i] = r1(h_wave, h_left, 0.0);
				}
				else {
					hex[i] = h_1;
					uex[i] = u_1;
				}
			}
			else { //xex[i]>xdam

				if (xex[i] >= xdam + T * spshock(h_2, u_2, h_right)) {
					hex[i] = h_right;
					uex[i] = 0.;
				}
				else {
					hex[i] = h_2;
					uex[i] = u_2;
				}
			}
		}//end for
	}
	else {//only one solution so far

	}
	savefinalcritical(xex, hex, uex, zex);

}



void Step::param(SCALAR L, SCALAR xdam, SCALAR step_size, SCALAR h_left, SCALAR h_right, SCALAR u_left, SCALAR u_right, SCALAR dx_ex, SCALAR T) const {

	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] xdam position of the dam
	 * @param[in] step_size size of the opening of the step
	 * @param[in] h_left height of the left side water
	 * @param[in] u_left water speed on the left of the step
	 * @param[in] h_right height of the right side water
	 * @param[in] u_right water speed on the right of the step
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters" << endl;
	cout << "# Space step: " << dx_ex << " meters" << endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Position of the dam: x=" << xdam << " meters" << endl;
	cout << "# Size of the step: step_size=" << step_size << " meters" << endl;
	cout << "# height of water on the left side=" << h_left << " meters" << endl;
	cout << "# speed of water on the left side=" << u_left << " meters/second" << endl;
	cout << "# height of water on the right side=" << h_right << " meters" << endl;
	cout << "# speed of water on the right side=" << u_right << " meters/second" << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################" << endl;
}

SCALAR Step::r1(SCALAR h_r, SCALAR h_l, SCALAR u_l) {
	/**
	 * @details
	 * Computes the value of the speed of the rarefaction function in the first characteristic field
	 * @param[in] h_r water height of the right side state
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 */
	return u_l + 2. * (sqrt(GRAV * h_l) - sqrt(GRAV * h_r));
}

SCALAR Step::spshock(SCALAR h_l, SCALAR u_l, SCALAR h_r) {
	/**
	 * @details
	 * Computes the speed of the shock wave in the second characteristic field
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 * @param[in] h_r water height of the right side state
	 */
	return u_l + h_r * sqrt(GRAV * (h_l + h_r) / (2 * h_l * h_r));
}
