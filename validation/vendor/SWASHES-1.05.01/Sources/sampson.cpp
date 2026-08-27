/**
 * @file sampson.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes %Sampson solution
 * @details 
 * Analytic solution: %Sampson parabola with friction, see \cite Sampson06 \cite Sampson08.
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

#include "sampson.hpp"

Sampson::Sampson(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, Solution#zex to have %Sampson configuration. 
	 */
	
	L = 10000.;
	dx_ex = L/NX_EX;
	a = 3000.;
	h0 = 10.;

	x1=0;
	x2=0;
	
	B=5.;
	tau=0.001;
	p = pow(8.*GRAV*h0/(a*a),1./2.);
	s = pow(p*p-tau*tau,1./2.)/2.;
	
	T = 6000.; //in seconds
	
	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = h0*pow((xex[i]-L/2.)/a,2.);
	}
	
	head(par, "Oscillations", "Planar surface in a parabola with a linear friction (Sampson's solution)");
	param(L, h0, a, B, tau, dx_ex, T);
	
}

Sampson::~Sampson(){
}


void Sampson::compute(){
	
	/**
	 * @details 
	 * Computes %Sampson solution, see \cite Sampson06 \cite Sampson08.
	 * @par Modifies 
	 * Solution#hex, Solution#uex.
	 */
	
	x1 = a*a*exp(-tau*T/2.)/(2.*GRAV*h0)*(-B*s*cos(s*T)-tau*B*sin(s*T)/2.)-a +L/2;
	x2 = a*a*exp(-tau*T/2.)/(2.*GRAV*h0)*(-B*s*cos(s*T)-tau*B*sin(s*T)/2.)+a+L/2;
	
	for (int i=0 ; i<=NX_EX ; i++){
		if (xex[i]>x1 && xex[i]<x2){
			uex[i] = B*exp(-tau*T/2.)*sin(s*T);
			hex[i] = h0+pow(a*B,2.)*exp(-tau*T)/(8.*pow(GRAV,2.)*h0) *(-s*tau*sin(2.*s*T)+(tau/2.-s)*(tau/2. +s)*cos(2.*s*T))- pow(B,2.)*exp(-tau*T)/(4.*GRAV)-exp(-tau*T/2.)*(B*s*cos(s*T)+tau*B*sin(s*T)/2.)*(xex[i]-L/2)/GRAV-zex[i];
		}else{
			uex[i] = 0.;
			hex[i] = 0.;
		}
	}
	
	savefinalcritical(xex, hex, uex, zex);

}


void Sampson::param(SCALAR L, SCALAR h0, SCALAR a, SCALAR B, SCALAR tau, SCALAR dx_ex, SCALAR T) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] h0 value of the topography in the center of the domain
	 * @param[in] a parameter of the topography
	 * @param[in] B constant for the initial condition
	 * @param[in] tau friction coefficient
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "# " << endl;
	cout << "# Topography: z(x) = h0 (x-L/2)^2/a^2, with h0="<< h0<< " meters and a=" << a <<" meters"<<endl;
	cout << "# Constant B for the initial condition B=" << B<< " m/s"<< endl;
	cout << "# Friction coefficient tau=" << tau<< " s^-1" << endl;
	cout << "##############################################################################"<<endl;
}	


