 /**
 * @file bedload.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2012)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2026)
 * @version 1.05.01
 * @date 2026-03-13
 *
 * @brief Computes solutions with bedload
 * @details 
 * Analytic solution: the bed is moving with bedload, see \cite Berthon12.
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

#include "bedload.hpp"


Bedload::Bedload(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @warning Problem: allocation of z0 failed
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex. 
	 * @note If the vector z0 cannot be allocated, the code will exit with failure termination code.
	 */	
	
	z0 = new SCALAR[NX_EX+1];
	if(NULL==z0){
		fprintf(stderr, "\nProblem: allocation of z0 failed\n");
		exit(EXIT_FAILURE);
	}
	
	L = 15.;
	dx_ex = L/NX_EX;
	T = 7.;	
	
	p = 1.5;
	alpha = 0.005;
	beta = 0.005;
	C = 1.0;
	q = 1.0;

	ue2 = 0;

	if (par.get_choice()==1){
		// bedload with Grass equation
		
		A = 0.005;
		ucr2 = 0.0;
		
		uexl = sqrt(pow((-alpha*0.5*dx_ex+beta)/A,1./p)+ucr2);
		hexl = q/uexl;
		z0l =- (pow(uexl,3.)+2.*GRAV*q)/(2.*GRAV*uexl)+ C;
		zexl =-alpha*T+z0l;
		
		uexr = sqrt(pow((alpha*(L+0.5*dx_ex)+beta)/A,1./p));
		hexr = q/uexr;
		z0r =- (pow(uexr,3.)+2.*GRAV*q)/(2.*GRAV*uexr)+ C;
		zexr =-alpha*T+z0r;
		
		head(par, "Bedload", "with Grass equation");
		param(L, dx_ex, T, uexl, hexl, z0l, zexl, uexr, hexr, z0r, zexr, alpha, beta, A, q, C, p);
		paramwarning();
		
	}else{ // par.get_choice()==2
		// bedload with Meyer-Peter and Muler equation
		
		k=8;
		f=0.25;
		d=0.0005;
		s= 2600.0/1000.0; // rho_s/rho_water
		tcr=0.047;
		
		c1 = f/(8.*(s-1.)*GRAV*d);
		c2 = sqrt((s-1.)*GRAV*pow(d,3.));
		ucr2 = tcr/c1;
		A = k*pow(c1,p)*c2;
		
		uexl = sqrt(pow((-alpha*0.5*dx_ex+beta)/A,1./p)+ucr2);
		hexl = q/uexl;
		z0l =- (pow(uexl,3.)+2.*GRAV*q)/(2.*GRAV*uexl)+ C;
		zexl =-alpha*T+z0l;
		
		uexr = sqrt(pow((alpha*(L+0.5*dx_ex)+beta)/A,1./p));
		hexr = q/uexr;
		z0r =- (pow(uexr,3.)+2.*GRAV*q)/(2.*GRAV*uexr)+ C;
		zexr =-alpha*T+z0r;
		
		head(par, "Bedload", "with Meyer-Peter and Muler equation");
		param(L, dx_ex, T, uexl, hexl, z0l, zexl, uexr, hexr, z0r, zexr, alpha, beta, A, q, C, p);
		cout << "# kappa="<<k<<", f="<<f<<", sedim. diam. d="<<d<<" m, sedim. density rs="<<s*1000.0<<" kg/m^3, Shields stress tau_cr="<<tcr << endl;
		paramwarning();
		
	}
	
	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		z0[i] = 0.0;
		zex[i] = 0.0;
		uex[i] = 0.0;
		hex[i] = 0.0;
	}
	
}


Bedload::~Bedload(){
	delete [] z0;
}


void Bedload::compute(){
	
	/**
	 * @details 
	 * Computes the chosen bedload solution, see \cite Berthon12.
	 * @par Modifies 
	 * Solution#hex, Solution#uex, Solution#zex.
	 */

	for(int i=1; i<=NX_EX; i++) {
		ue2 = pow((alpha*xex[i]+beta)/A,1./p);
		uex[i] = sqrt(ue2+ucr2);
		hex[i] = q/uex[i];
		z0[i] =- (pow(uex[i],3.)+2.*GRAV*q)/(2.*GRAV*uex[i])+ C;
		zex[i] =-alpha*T+z0[i];
	}
	savefinalcriticalinit(xex, hex, uex, zex, z0);
}


void Bedload::param(SCALAR L , SCALAR dx_ex, SCALAR T, SCALAR uexl, SCALAR hexl, SCALAR z0l, SCALAR zexl, SCALAR uexr, SCALAR hexr, SCALAR z0r, SCALAR zexr, SCALAR alpha, SCALAR beta, SCALAR A,SCALAR q, SCALAR C, SCALAR p) const {
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 * @param[in] uexl value of the velocity on the left boundary
	 * @param[in] hexl value of the water height on the left boundary
	 * @param[in] z0l value of the inital topography on the left boundary
	 * @param[in] zexl value of the final topography on the left boundary
	 * @param[in] uexr value of the velocity on the right boundary
	 * @param[in] hexr value of the water height on the right boundary
	 * @param[in] z0r value of the inital topography on the right boundary
	 * @param[in] zexr value of the final topography on the right boundary
	 * @param[in] alpha parameter for Exner equation
	 * @param[in] beta parameter for Exner equation
	 * @param[in] A parameter for Exner equation
	 * @param[in] q parameter for Exner equation
	 * @param[in] C parameter for Exner equation
	 * @param[in] p parameter for Exner equation
	 */
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "# " << endl;
	cout << "# Initial conditions: h, u and z0 (see solution and documentation)" << endl;
	cout << "# Left boundary conditions x="<<-0.5*dx_ex <<" m:" << endl;
	cout << "#   u="<< uexl<< " m/s, h=" << hexl<< " m, z0=" << z0l << " m and z=" <<zexl<<" m" << endl;
	cout << "# Right boundary conditions x="<<L+0.5*dx_ex <<" m:" << endl;
	cout << "#   u="<< uexr<< " m/s, h=" << hexr<< " m, z0=" << z0r << " m and z=" <<zexr<<" m" << endl;
	cout << "# alpha="<<alpha<<" m/s, beta="<<beta<<" m^2/s, A="<<A<<" s^2/m, q="<<q<<" m^2/s, C="<<C<<" m, p="<<p<< endl; 
}

void Bedload::paramwarning() const{
	
	/**
	 * @details
	 * @warning WARNING: to compare your numerical result to this solution, you must be able to remove friction from the Shallow-Water part (see doc).
	 */
	
	cout << "##############################################################################" << endl;
	cout << "# WARNING: to compare your numerical result to this solution,"<< endl;
	cout << "#    you must be able to remove friction from the Shallow-Water part (see doc)." << endl;
	cout << "##############################################################################" << endl;
}	
