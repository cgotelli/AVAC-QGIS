/**
 * @file thacker.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes %Thacker solution
 * @details 
 * Analytic solution: %Thacker parabola, see \cite Thacker81.
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

#include "thacker.hpp"

Thacker::Thacker(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex to have %Thacker configuration. 
	 */
	
	L = 4.;
	dx_ex = L/NX_EX;
	a = 1.;
	h0 = 0.5;

	x1=0;
	x2=0;
	
	omega = pow(2.*GRAV*h0/(a*a),0.5);
	B = 0.5*omega;
	T = 5; //in periods
	T = 2.*PI*T/omega; // in seconds

	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = h0*(pow((xex[i]-L/2.)/a,2.)-1.);
	}
	
	head(par, "Oscillations", "Planar surface in a parabola without friction (Thacker's solution)");
	param(L, h0, a, dx_ex, T);

}

Thacker::~Thacker(){

}


void Thacker::compute(){
	
	/**
	 * @details 
	 * Computes %Thacker solution, see \cite Thacker81.
	 * @par Modifies 
	 * Solution#hex, Solution#uex.
	 */

	x1 = -B*cos(omega*T)/omega-a+L/2.;
	x2 = -B*cos(omega*T)/omega+a+L/2.;

	for (int i=0 ; i<=NX_EX ; i++){
		if (xex[i]>x1 && xex[i]<x2){
			uex[i] = B*sin(omega*T);
			// (x-y)(x+y) instead of x^2-y^2
			hex[i] = -h0*(xex[i]-L/2.+B*cos(omega*T)/omega-a)*(xex[i]-L/2.+B*cos(omega*T)/omega+a)/pow(a,2.);
		}else{
			uex[i] = 0.;
			hex[i] = 0.;
		}
		
	}

	savefinalcritical(xex, hex, uex, zex);

}


void Thacker::param(SCALAR L, SCALAR h0, SCALAR a, SCALAR dx_ex, SCALAR T) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] h0 value of the topography in the center of the domain
	 * @param[in] a parameter of the topography
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Topography: z(x) = h0 ((x-L/2)^2/a^2 -1), with h0="<< h0<< " meters and a=" << a <<" meters"<<endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################"<<endl;
}

