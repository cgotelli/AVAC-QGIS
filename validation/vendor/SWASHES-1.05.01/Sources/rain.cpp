/**
 * @file rain.cpp
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2025)
 * @version 1.05.00
 * @date 2025-04-17
 *
 * @brief Computes a solution with mobile rain
 * @details
 * Analytic solution: mobile rain, with different velocities compared to the flow, see \cite DeLu25.
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

#include "rain.hpp"

Rain::Rain(Parameters& par) :Solution(par) {
	/**
	 * @details
	 * Defines the physical parameters, the final time, and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex, Rain#
	 * to have the mobile rain configuration.
	 */
	T = 1000.;
	L = 18000;
	h0 = 0.25;
	q0 = 2;
	S0 = 0.09;
	C = S0*h0/q0;
	R0 = 0.00005;


	//we also initialize a few variables that will be usefull (and overwritten) later:
	raincase = 0;
	vr = 0.;
	
	if (par.get_choicedomain()==1 && par.get_choice() == 1) { // rain velocity same as the flow
		vr = S0/C;
		raincase = 1;
		head(par, "Mobile rain", "Same velocity as the flow");
	}
	else if (par.get_choicedomain()==1 && par.get_choice() == 2) { // rain velocity smaller than the flow
		vr = S0/C*0.2;
		raincase = 2;
		head(par, "Mobile rain", "Rain velocity smaller than the flow");
	}
	else if (par.get_choicedomain()==1 && par.get_choice() == 3) { // rain velocity larger than the flow
		vr = S0/C*1.3;
		raincase = 3;
		head(par, "Mobile rain", "Rain velocity larger than the flow");
	}
	else {//nothing for now

	}
	
	dx_ex = L / NX_EX;
	
	Lr = L/5;
	x0 = L/8;
	
	for (int i = 0; i <= NX_EX; i++) {
		xex[i] = (i - 0.5) * dx_ex;
		zex[i] = -S0 * xex[i];
	}
	
	param(L, dx_ex, R0, x0, Lr, vr, S0, C, h0, q0, T);
	
}


Rain::~Rain() {

}


void Rain::compute() {

	/**
	 * @details
	 * Computes the chosen rain solution.
	 * @par Modifies
	 * Solution#hex.
	 */
	/*      If we need more times
	computet(T/4);
	
	cout << "# time = " << T/4 << endl;  // Saves the solution at 1/4 of the simulation duration to better see the profile of the flow
	savefinalmu(xex, hex, zex);
	cout << endl;
	cout << endl;
	*/
	
	computet(T/2);
	
	cout << "# time = " << T/2 << endl;  // Saves the solution at half the simulation duration to better see the profile of the flow
	savefinalmu(xex, hex, zex);
	cout << endl;
	cout << endl;
	
	/*      If we need more times
	computet(3*T/4);
	
	cout << "# time = " << T*3/4 << endl;  // Saves the solution at 3/4 of the simulation duration to better see the profile of the flow
	savefinalmu(xex, hex, zex);
	cout << endl;
	cout << endl;
	*/
	
	computet(T); 
	
	cout << "# time = " << T << endl; // Saves the solution at the end of the simulation
	savefinalmu(xex, hex, zex);
	

}



void Rain::param(SCALAR L, SCALAR dx_ex, SCALAR R0, SCALAR x0, SCALAR Lr, SCALAR vr, SCALAR S0, SCALAR C, SCALAR h0, SCALAR q0, SCALAR T) const {

	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] dx_ex space step
	 * @param[in] R0 maximal rain intensity
	 * @param[in] x0 left bound of the rain
	 * @param[in] Lr length of the support of the rain (where it does not vanish)
	 * @param[in] vr velocity of the rain
	 * @param[in] S0 opposite of the slope of the topography
	 * @param[in] C friction coefficient
	 * @param[in] h0 water height of the flow
	 * @param[in] q0 water discharge of the flow
	 * @param[in] T final time
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters" << endl;
	cout << "# Space step: " << dx_ex << " meters" << endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Mobile rain: sin(pi*t/T)*rshape(x-vr*t)"<< endl;
	cout << "#   with rshape(x) = R0/2*(sin((x-x0-Lr/4)*2pi/Lr)+1)  if x0 <= x <= x0+Lr" << endl;
	cout << "#        rshape(x) = 0  else" << endl;
	cout << "#   Max intensity of the rain R0=" << R0 << " meters/second" << endl;
	cout << "#   Parameters of the rain: x0="<< x0 << " meters, Lr="<< Lr <<" meters"<< endl;
	cout << "#   Velocity of the rain: vr=" << vr << " meters/second" << endl;
	cout << "# Topography: slope -S0=" << -S0 << ", friction coefficient: C=" << C << endl;
	cout << "# Parameters of the flow: h0="<< h0 << " meters, q0="<< q0 <<" meters^2/second"<< endl;
	cout << "# Velocity of the flow: S0/C=" << S0/C << " meters/second" << endl;
	cout << "# Time values: " << T/2 << " and " << T << " seconds" << endl;
	cout << "##############################################################################" << endl;
}

void Rain::computet(SCALAR t) {

	/**
	 * @details
	 * Computes the chosen rain solution.
	 * @param[in] t time of the computation
	 * @par Modifies
	 * Solution#hex.
	 */

	if (raincase == 1) { // same velocity
		for (int i = 0; i <= NX_EX; i++) {
			if ((xex[i]-S0/C*t<x0) || (xex[i]-S0/C*t>x0 + Lr)){
				hex[i] = h0 ;
			}
			else if (xex[i]>=S0*t/C){
				hex[i] = h0 + R0/2*(sin((-S0/C*t + xex[i] -x0 - Lr/4 )*2*PI/Lr)+1) * T/PI*(1 - cos(PI*t/T) );
			}
			else {
				t0 = t-C/S0*xex[i];
				hex[i] = h0 + R0/2*(sin((-S0/C*t + xex[i] -x0 - Lr/4 )*2*PI/Lr)+1) * T/PI*(cos(PI*t0/T) - cos(PI*t/T) );
			}
		}
	}
	else if (raincase == 2) { // rain velocity smaller
		for (int i = 0; i <= NX_EX; i++) {
			if (1/(S0/C-vr)*(x0-xex[i]+S0/C*t)>t ||  1/(S0/C-vr)*(x0-xex[i]+S0/C*t+Lr)<0){
				hex[i] = h0;
			}
			else{
				tl = MAX(0, 1/(S0/C-vr)*(x0-xex[i]+S0/C*t));
				tr = MIN(t, 1/(S0/C-vr)*(x0-xex[i]+S0/C*t+Lr));
				if (xex[i]>=S0*t/C){
					hex[i] = h0 + rainint(tr,t,xex[i])-rainint(tl,t,xex[i]);
				}
				else {
					t0 = t-C/S0*xex[i] ;
					t0l = MAX(t0, tl);
					hex[i] = h0 +  rainint(tr, t,xex[i]) - rainint(t0l,t,xex[i]); 
				}
			}
		}
	}
	else if (raincase == 3) { // rain velocity larger
		for (int i = 0; i <= NX_EX; i++) {
			if (1/(vr-S0/C)*(xex[i]-x0-S0/C*t-Lr)>t ||  1/(vr-S0/C)*(xex[i]-x0-S0/C*t)<0){ 
				hex[i] = h0;
			}
			else {
				tl = MAX(0, 1/(vr-S0/C)*(xex[i]-x0-S0/C*t-Lr));
				tr = MIN(t, 1/(vr-S0/C)*(xex[i]-x0-S0/C*t));
				if (xex[i]>=S0*t/C){
					hex[i] = h0 + rainint(tr,t,xex[i])-rainint(tl,t,xex[i]);
				}
				else {
					t0 = t-C/S0*xex[i];
					t0l = MAX(t0, tl);
					hex[i] = h0 +  rainint(tr, t,xex[i]) - rainint(t0l,t,xex[i]); 
				}
			}
		}
	}
	else {//nothing more so far
	}
}
	

SCALAR Rain::rainint(SCALAR tau, SCALAR t, SCALAR x) {
	/**
	 * @details
	 * Computes the integral of the rain r(t,x) over the domain [0, tau]
	 * @param[in] tau bound of the integral
	 * @param[in] t time of the current point
	 * @param[in] x position of the current point
	 * @return Value of the integral
	*/
	
	SCALAR A = PI/T;
	SCALAR B = R0/2.;
	SCALAR E = (S0/C-vr)*2*PI/Lr;
	SCALAR D = (x-S0/C*t -x0-Lr/4.)*2.*PI/Lr;
	
	return 1./2.*B*(2*(pow(A,2)*sin(D) + pow(A,2) - pow(E,2))/(pow(A,3) - A*pow(E,2)) - (2*(pow(A,2) - pow(E,2))*cos(A*tau) + (pow(A,2) - A*E)*sin((A + E)*tau + D) + (pow(A,2) + A*E)*sin(-(A - E)*tau + D))/(pow(A,3) - A*pow(E,2)));
}




