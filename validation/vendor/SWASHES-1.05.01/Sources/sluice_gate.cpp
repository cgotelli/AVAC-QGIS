/**
 * @file sluice_gate.cpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.00
 * @date 2022-07-13
 *
 * @brief Computes dam break with a sluice gate solutions
 * @details
 * Analytic solution: dam break with a sluice gate without friction, see \cite Cozzolino15.
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

#include "sluice_gate.hpp"

Sluice_gate::Sluice_gate(Parameters& par) :Solution(par) {

	/**
	 * @details
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex, Sluice_gate#h_left, Sluice_gate#h_right, Sluice_gate#gate_size,
	 * Sluice_gate#solu, Sluice_gate#Cc, Sluice_gate#xdam
	 * to have the sluice gate opening configuration.
	 */
	Cc = 0.611;
	L = 10.;
	xdam = L / 2.;
	dx_ex = L / NX_EX;
	T = 6.;


	//we also initialize a few variable that will be usefull later:
	h_1 = 0.;
	h_2 = 0.;
	u_1 = 0.;
	u_2 = 0.;
	h_c = 0.;
	u_c = 0.;

	for (int i = 0; i <= NX_EX; i++) {
		xex[i] = (i - 0.5) * dx_ex;
		zex[i] = 0.0;
	}

	if (par.get_choice() == 1) {
		// sluice gate opening on dry domain
		h_left = 0.005;
		h_right = 0.;
		gate_size = 0.2 * h_left; //gate_size must be kept <4/9*h_left for the solution to be correct.
		solu = 1;
		head(par, "Sluice Gate", "on a dry domain without friction");
		param(L, xdam, gate_size, h_left, h_right, dx_ex, T);
	}
	else if (par.get_choice() == 2) {
		// sluice gate opening on wet domain
		h_left = 0.005;
		h_right = 0.002*h_left; //for this solution to hold h_right must be < Cc*a
		gate_size = 0.2 * h_left; //gate_size must be kept <4/9*h_left for the solution to be correct.
		solu = 2;
		head(par, "Sluice Gate", "on a slightly wet domain without friction");
		param(L, xdam, gate_size, h_left, h_right, dx_ex, T);
	}
	else {//par.get_choice ==3
		// sluice gate opening on wet domain
		h_left = 0.005;
		h_right = 0.2 * h_left; //for this solution to hold h_right must be < Cc*a
		gate_size = 0.2 * h_left; //gate_size must be kept <4/9*h_left for the solution to be correct.
		solu = 3;
		head(par, "Sluice Gate", "on a dry domain without friction");
		param(L, xdam, gate_size, h_left, h_right, dx_ex, T);
	}
}


Sluice_gate::~Sluice_gate() {

}


void Sluice_gate::compute() {

	/**
	 * @details
	 * Computes the chosen sluice gate solution.
	 * @par Modifies
	 * Solution#hex.
	 */

	// For the following solutions we will start each time by computing all the intermediate states: h_1,u_1,h_c,u_c as well as h_2,u_2 if necessary
	// Most intermediate states are found at the intersection of two locus of admissible states.
	// We will use a dichotomie function to find them.
	if (solu == 1) {
		
		//we find the first intermediate state at the intersection between the locus corresponding to the rarefaction wave 
		//and the locus of admissible discharge at the sluice gate.
		h_1 = dichotomie(1);
		//Since this state is in the rarefaction wave (in th efirst characteristic field) locus we use it to find u_1.
		u_1 = r1(h_1,h_left,0.0);
		//h_c is given by the definition of Cc
		h_c = Cc * gate_size;
		//There is a constant discharge at the sluice gate: h_1*u_1=h_c*u_c
		u_c = h_1 * u_1 / h_c;

		for (int i = 0; i <= NX_EX; i++) { //looks at all the different cases
			if (xex[i] <= xdam) {// we check on which side of the dam we are

				//water height of the left side rarefaction wave:
				SCALAR h_wave = pow(2 * sqrt(GRAV * h_left) - (xex[i] - xdam) / T, 2.) / (9. * GRAV);
				if (h_wave >= h_left) {
					hex[i] = h_left;
					uex[i] = 0.;
				}
				else if(h_wave >= h_1) {
					hex[i] = h_wave;
					uex[i] = r1(h_wave,h_left, 0.0);
				}
				else {
					hex[i] = h_1;
					uex[i] = u_1;
				}
			}
			else { //xex[i]>xdam

				//water height of the right side rarefaction wave:
				SCALAR h_wave = pow(u_c + 2 * sqrt(GRAV * h_c) - (xex[i] - xdam) / T, 2.) / (9. * GRAV);

				if (xex[i] >= xdam + T * (u_c + 2 * sqrt(GRAV * h_c))) {
					hex[i] = h_right;
					uex[i] = 0.;
				}
				else if (h_wave >= h_c) {
					hex[i] = h_c;
					uex[i] = u_c;
				}
				else {
					hex[i] = h_wave;
					uex[i] = r1(h_wave,h_c,u_c);
				}
			}

		}//end for
	}

	else if(solu==2) {
		//we find the first intermediate state at the intersection between the locus corresponding to the rarefaction wave 
		//and the locus of admissible discharge at the sluice gate.
		h_1 = dichotomie(1);
		//Since this state is in the rarefaction wave (in th efirst characteristic field) locus we use it to find u_1.
		u_1 = r1(h_1, h_left, 0.0);
		//h_c is given by the definition of Cc.
		h_c = Cc * gate_size;
		//There is a constant discharge at the sluice gate: h_1*u_1=h_c*u_c.
		u_c = h_1 * u_1 / h_c;
		//h_2 is found at the intersection between the locus of the rarefaction wave from the U_c and the shock with the state U_R.
		h_2 = dichotomie(2);
		//same as with u_1.
		u_2 = r1(h_2,h_c,u_c);

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
					uex[i] = r1(h_wave, h_left,0.0);
				}
				else {
					hex[i] = h_1;
					uex[i] = u_1;
				}
			}
			else { //xex[i]>xdam

				//water height of the right side rarefaction wave:
				SCALAR h_wave = pow(u_c + 2 * sqrt(GRAV * h_c) - (xex[i] - xdam) / T, 2.) / (9. * GRAV);

				if (xex[i] >= xdam + T * spshock2(h_2,u_2,h_right)) {
					hex[i] = h_right;
					uex[i] = 0.;
				}
				else if (h_wave >= h_c) {
					hex[i] = h_c;
					uex[i] = u_c;
				}
				else if (h_wave >= h_2) {
					hex[i] = h_wave;
					uex[i] = r1(h_wave,h_c,u_c);
				}
				else {
					hex[i] = h_2;
					uex[i] = u_2;
				}
			}
		}//end for
	}

	else {//solu =3
		//we find the first intermediate state at the intersection between the locus corresponding to the rarefaction wave 
		//and the locus of admissible discharge at the sluice gate.
		h_1 = dichotomie(1);
		//Since this state is in the rarefaction wave (in th efirst characteristic field) locus we use it to find u_1.
		u_1 = r1(h_1, h_left, 0.0);
		//h_c is given by the definition of Cc
		h_c = Cc * gate_size;
		//There is a constant discharge at the sluice gate: h_1*u_1=h_c*u_c
		u_c = h_1 * u_1 / h_c;
		//h_2 is found at the intersection between the locus of the shock wave from the U_c and the shock with the state U_R.
		h_2 = dichotomie(3);
		//same principle as with u_1.
		u_2 = s2(h_c, u_c, h_2);
	
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

				if (xex[i] >= xdam + T * spshock2(h_2, u_2, h_right)) {
					hex[i] = h_right;
					uex[i] = 0.;
				}
				else if (xex[i] <= xdam + T * spshock1(h_c, u_c, h_2)) {
					hex[i] = h_c;
					uex[i] = u_c;
				}
				else {
					hex[i] = h_2;
					uex[i] = u_2;
				}
			}
		}//end for
	}
	savefinalcritical(xex, hex, uex, zex);

}



void Sluice_gate::param(SCALAR L, SCALAR xdam, SCALAR gate_size, SCALAR h_left, SCALAR h_right, SCALAR dx_ex, SCALAR T) const {

	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] xdam position of the dam
	 * @param[in] gate_size size of the opening of the sluice gate
	 * @param[in] h_left height of the left side water
	 * @param[in] h_right height of the right side water
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters" << endl;
	cout << "# Space step: " << dx_ex << " meters" << endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Position of the dam: x=" << xdam << " meters" << endl;
	cout << "# Size of the gate: gate_size=" << gate_size << " meters" << endl;
	cout << "# height of water on the left side=" << h_left << " meters" << endl;
	cout << "# height of water on the right side=" << h_right << " meters" << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################" << endl;
}

SCALAR Sluice_gate::ff(SCALAR h){	
	/**
	 * @details
	 * Computes the value of the free flow function
	 * @param[in] h water height, corresponds here to the where we compute the function
	 */
	h_c = Cc * gate_size;
	return h_c * sqrt(2 * GRAV * h) / (h * sqrt(1 + h_c / h));
}

SCALAR Sluice_gate::r1(SCALAR h_r, SCALAR h_l, SCALAR u_l){
	/**
	 * @details
	 * Computes the value of the speed of the rarefaction function in the first characteristic field
	 * @param[in] h_r water height of the right side state
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 */
	return u_l + 2. * (sqrt(GRAV * h_l) - sqrt(GRAV * h_r));
}

SCALAR Sluice_gate::spshock1(SCALAR h_l, SCALAR u_l, SCALAR h_r) {
	/**
	 * @details
	 * Computes the speed of the shock wave in the first characteristic field
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 * @param[in] h_r water height of the right side state
	 */
	return u_l - h_r * sqrt(GRAV * (h_l + h_r) / (2 * h_l * h_r));
}

SCALAR Sluice_gate::spshock2(SCALAR h_l, SCALAR u_l, SCALAR h_r) {
	/**
	 * @details
	 * Computes the speed of the shock wave in the second characteristic field
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 * @param[in] h_r water height of the right side state
	 */
	return u_l + h_r * sqrt(GRAV * (h_l + h_r) / (2 * h_l * h_r));
}

SCALAR Sluice_gate::s2(SCALAR h_l, SCALAR u_l, SCALAR h_r){
	/**
	 * @details
	 * Computes the value of second characteristic field shock function
	 * @param[in] h_l water height of the left side state, origin of the rarefacion wave
	 * @param[in] u_l water speed of the left side state, origin of the rarefacion wave
	 * @param[in] h_r water height of the right side state
	 */
	return u_l - (h_r-h_l)*sqrt((GRAV/2)*(1/h_l+1/h_r));
}

SCALAR Sluice_gate::dichotomie(int choice){
	/**
	 * @details
	 * Finds the intersection between two locus of admissible states to, the locus are chosen with the variable choice
	 * @param[in] choice choice of which dichotomy to apply
	 */
	// Parameters for the dichotomy
	SCALAR eps = 0.0000001;
	int nmax = 1000;
	int iter = 0.;
	SCALAR h_a = eps;
	SCALAR h_b = h_left;
	SCALAR mid=0.0;
	SCALAR func=10,funca=10;

	switch (choice) {
	case 1: //finds the intersection between the free flow function and the rarefaction function

		while (fabs(func) > eps && iter < nmax) {
			iter = iter + 1;
			mid = (h_b + h_a) * 0.5;
			func = (ff(mid) - r1(mid, h_left, 0.0));
			funca = (ff(h_a) - r1(h_a, h_left, 0.0));
			if (func * funca >= 0.) {
				h_a = mid;
			}
			else {
				h_b = mid;
			}
		} //end while
		return mid;

	case 2: //finds the intersection between the rarefaction function and the shock function
		func = eps + 1;
		while (fabs(func) > eps && iter < nmax) {
			iter = iter + 1;
			mid = (h_b + h_a) * 0.5;
			func = (s2(mid, 0.0, h_right) - r1(mid, h_c, u_c));
			funca = (s2(h_a, 0.0, h_right) - r1(h_a, h_c, u_c));
			if (func * funca >= 0.) {
				h_a = mid;
			}
			else {
				h_b = mid;
			}
		} //end while
		return mid;
	case 3: //finds the intersection between two shock functions
		func = eps + 1;
		while (fabs(func) > eps && iter < nmax) {
			iter = iter + 1;
			mid = (h_b + h_a) * 0.5;
			func = (s2(mid, 0.0, h_right) - s2(h_c, u_c, mid));
			funca = (s2(h_a, 0.0, h_right) - s2(h_c, u_c, h_a));
			if (func * funca >= 0.) {
				h_a = mid;
			}
			else {
				h_b = mid;
			}
		} //end while
		return mid;
	default:
	break;
	}
	return 0.0;
}


