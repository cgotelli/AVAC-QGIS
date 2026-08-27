/**
 * @file dam_break.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes dam break solutions
 * @details 
 * Analytic solution: dam break without friction, see \cite Ritter92 \cite Stoker57.
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

#include "dam_break.hpp"

Dam_break::Dam_break(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex to have the dam break configuration. 
	 */

	L = 10.;
	xdam = L/2.;
	dx_ex = L/NX_EX;
	T = 6.;

	x_a=0;
	x_b=0;
	mid =0;
	h_mid=0;
	u_mid=0;
	c_mid=0;
	v=0;
	func=0;
		
	// Parameters for the dichotomy
	eps = 0.000001;
	nmax = 1000;
	iter = 0.;

	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = 0.0;
	}

	if (par.get_choice()==1){
		// dam break on a wet domain without friction (Stoker's solution)
		h_left = 0.005;
		h_right = 0.001;
		
		head(par, "Dam break", "on a wet domain without friction (Stoker's solution)");
		param(L, xdam, dx_ex, T);
		
	}else{ // par.get_choice()==2
		// dam break on a dry domain without friction (Ritter's solution)
		h_left = 0.005;
		h_right = 0.;
		
		head(par, "Dam break", "on a dry domain without friction (Ritter's solution)");
		param(L, xdam, dx_ex, T);
	}

	c_left = pow(GRAV*h_left,0.5); // cl left wave velocity
	c_right = pow(GRAV*h_right,0.5); // cr right wave velovity

}


Dam_break::~Dam_break(){

}


void Dam_break::compute(){
	
	/**
	 * @details 
	 * Computes the chosen dam break solution, see \cite Ritter92 \cite Stoker57.
	 * @par Modifies 
	 * Solution#hex.
	 */

	func = function(c_left,c_left,c_right);
	if (func <0.){
		x_a = c_left; // func(cl)<0
	}else{
		x_b = c_left; // func(cl)>0
	}//end if

	func = function(c_right,c_left,c_right);
		if (func <0.){
		x_a = c_right; // func(cr)<0
	}else{
		x_b = c_right; // func(cr)>0
	}//end if


	/* dichotomy in order to solve the equation in cm
	 * cm^6-9*cr^2*cm^4+16*cl*cr^2*cm^3-cr^2*(cr^2+8*cl^2)*cm^2+cr^6=0
	 * in order to get the water height hm (when hr is not null)
	 */
	while(fabs(x_a-x_b)>eps && iter<nmax){
		iter = iter+1;
		mid = (x_a+x_b)*0.5;

		func = function(mid,c_left,c_right);

		if (func<0.){
			x_a = mid;
		}else{
			x_b = mid;
		}
	} //end while

	c_mid = (x_a+x_b)*0.5; //cm

	if (abs(h_right) < EPSILON){
		c_mid = 0.;
	} // the dam break on dry soil

	h_mid = c_mid*c_mid/GRAV; //the water height hm
	u_mid = 2.*(c_left-c_mid); //the velocity um
	v = h_mid*u_mid/(h_mid-h_right); //the velocity of the shock

	for (int i=0 ; i<=NX_EX ; i++){
		if (xex[i] <= xdam-c_left*T){
			hex[i] = h_left;
			uex[i] = 0.;
		}else{
			if (xex[i] <= xdam+(2.*c_left-3.*c_mid)*T){
				hex[i] = (4./(9.*GRAV))*(c_left*c_left-c_left*(xex[i]-xdam)/T+(xex[i]-xdam)*(xex[i]-xdam)/(4.*T*T));
				uex[i] = ((xex[i]-xdam)/T+c_left)*2./3.;
			}else{
				if (xex[i] <= xdam+v*T){
					hex[i] = h_mid;
					uex[i] = u_mid;
				}else{
					hex[i] = h_right;
					uex[i] = 0.;
				}
			}
		}
	}//end for
	
	savefinalcritical(xex, hex, uex, zex);
	
}

SCALAR Dam_break::function(SCALAR x, SCALAR v_left, SCALAR v_right) const{
	
	/**
	 * @details 
	 * Function to solve by dichotomy the equation
	 * \f$ cm^6-9v_{right}^2cm^4+16v_{left}\, v_{right}^2cm^3-v_{right}^2(v_{right}^2+8v_{left}^2)cm^2+v_{right}^6=0\f$.
	 * @return Value of \f$x^6-9v_{right}^2x^4+16v_{left}\, v_{right}^2x^3-v_{right}^2(v_{right}^2+8v_{left}^2)x^2+v_{right}^6\f$.
	 */
	
	return pow(x,6.)-9.*pow(v_right,2.)*pow(x,4.)+16.*v_left*pow(v_right,2.)*pow(x,3.)-pow(v_right,2.)*(pow(v_right,2.)+8.*pow(v_left,2.))*pow(x,2.)+pow(v_right,6.);
}

void Dam_break::param(SCALAR L, SCALAR xdam, SCALAR dx_ex, SCALAR T) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] xdam position of the dam
	 * @param[in] dx_ex space step 
	 * @param[in] T final time
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Position of the dam: x=" << xdam << " meters" << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################" << endl;
}	
