/**
 * @file dressler_dam.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes Dressler dam break solution
 * @details 
 * Analytic solution: dam break with friction, see \cite Dressler52.
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

#include "dressler_dam.hpp"



Dressler_dam::Dressler_dam(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @warning Problem: allocation of hexd failed.
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#zex to have Dressler dam break configuration. 
	 * @note If the vector hexd cannot be allocated, the code will exit with failure termination code.
	 */
	
	L = 2000.;
	dx_ex = L/NX_EX;
	T = 40.; //ttot
	h0 = 6.; //water height behind the dam
	xdam = L/2; //dam location
	C = 40.; //Chezy friction coefficient
	dt = 0.1; //time step for the tip location
	t = dt; //current time for the tip location

	uTip=0;
	xa=0;
	xb=0;
	alpha1=0;
	alpha2=0;
	Tg=0;
	c2=0;
	a=0;
	b=0;
	mEnd=0;
	miTip=0;
	mEndTip=0;
	
	hexd = new SCALAR[NX_EX+1];

	if (NULL==hexd){
		fprintf(stderr,"\nProblem: allocation of hexd failed\n");
		exit(EXIT_FAILURE);
	}

	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex; //the domain definition
		zex[i] = 0.; //flat topography
	}

	c0 = pow(GRAV*h0,0.5); //wave speed
	Cst = GRAV/(C*C); //constant linked to the friction
	uTip0 = 0.; //initialization of the velocity of the tip
	xf = xdam; //position of the wet/dry position
	
	head(par, "Dam break", "on a dry domain with friction (Dressler's solution)");
	param( L, xdam, C, dx_ex, T);
}

Dressler_dam::~Dressler_dam(){
	delete [] hexd;
}

void Dressler_dam::compute(){
	
	/**
	 * @details 
	 * Computes Dressler solution, see \cite Dressler52.
	 * @par Modifies 
	 * Solution#hex, Solution#uex.
	 */

	for (int i=0 ; i<=NX_EX ; i++){
		hex[i] = 0.;
		uex[i] = 0.;
	}


	while(t<T){
		xa = xdam-c0*t; //location of the plateau h=h0 
		xb = xdam+2.*c0*t; //location of the plateau h=0 for the Ritter solution, the wet/dry transition is behind this location because of friction

		for (int i=0 ; i<=NX_EX ; i++){
			if (xex[i]<xa){
				uex[i] = 0.;
				hex[i] = h0; //the plateau
				hexd[i] = h0; //the plateau
			}else{
				if (xex[i]>xb){
					uex[i] = 0.;
					hex[i] = 0.;
					hexd[i] = 0.;
				}else{
					alpha1 = 6./(5.*(2.-(xex[i]-xdam)/(c0*t)))-2./3.+4.*pow(3.,0.5)/135.*pow(2.-(xex[i]-xdam)/(c0*t),3./2.);
					alpha2 = 12./(2.-(xex[i]-xdam)/(c0*t))-8./3.+8.*pow(3.,0.5)/189.*pow(2.-(xex[i]-xdam)/(c0*t),3./2.)-108./(7.*pow(2.-(xex[i]-xdam)/(c0*t),2.));

					uex[i] = 2./3.*c0*(1.+(xex[i]-xdam)/(c0*t))+Cst*GRAV*alpha2*t;
					hex[i] = pow(c0/3.*(2.-(xex[i]-xdam)/(c0*t))+Cst*GRAV*alpha1*t,2.)/GRAV;
					hexd[i] = hex[i];

					mEnd = i;
				}//end if
			}//end if
		}//end for

		uTip = 0.; //intialization of the tip velocity

		/*
		 * Loop to get the tip velocity at time t
		 */
		for (int i=0 ; i<=NX_EX ; i++){
			uTip = max(uTip,uex[i]);//the velocity in the tip is maximum
		}

		xf = xf+dt*(uTip0+uTip)/2.; //location of the tip at time t by an iterative method (wet/dry transition)
		uTip0 = uTip; //velocity of the tip at time t

		t = t+dt; //incrementation of the time variable
	}//end while

	for (int i=0 ; i<=NX_EX ; i++){
		if (abs(uex[i]-uTip0)<EPSILON){
			miTip = i; //location (indice) of the begining of the tip thanks to the velocity: the velocity is constant in the tip
		}
	}

	for (int i=0 ; i<=NX_EX ; i++){
		if (xf>xex[i]){
			mEndTip = i; //location (indice) of the end (front) of the tip
		}
	}


	for (int i=miTip ; i<=mEndTip ; i++){
		uex[i] = uTip0; //the velocity in the tip is constant
	}

	/*
	 * Second order interpolation in the tip to have an idea of the water height
	 * personnal communication with Valerio Caleffi
	 */

	Tg = (xex[miTip]-xex[miTip-1])/(hex[miTip]-hex[miTip-1]);

	c2 = xex[mEndTip];
	a = (Tg*hex[miTip]+c2-xex[miTip])/pow(hex[miTip],2.);
	b = Tg-2.*a*hex[miTip];

	for (int i=miTip ; i<=mEndTip ; i++){
		hex[i] = (-b-pow(pow(b,2.)-4.*a*(c2-xex[i]),1./2.))/(2.*a);
	}


	for (int i=mEndTip+1 ; i<=mEnd ; i++){
		uex[i] = 0.;
		hex[i] = 0.;
		hexd[i] = 0.;
	}
	

	savefinalcritical(xex, hex, uex, zex);
	
}

void Dressler_dam::param(SCALAR L, SCALAR xdam, SCALAR C, SCALAR dx_ex, SCALAR T) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] xdam position of the dam
	 * @param[in] C Chezy friction coefficient
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Position of the dam: x=" << xdam << " meters" << endl;
	cout << "# Chezy friction coefficient: " << C << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################"<<endl;
}	


