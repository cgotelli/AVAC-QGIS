/**
 * @file solution.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2026)
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.05.01
 * @date 2025-04-17
 *
 * @brief Common file
 * @details 
 * Common part for all the solutions.
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

#include "solution.hpp"

Solution::Solution(Parameters & par):NX_EX(par.get_nxex()),NY_EX(par.get_nyex()){
	
	/**
	 * @details	 
	 * @param[in] par contains all the values from the parameters file
	 */	
	
	allocation();

	T=0;
	L=0;
	l=0;
	dx_ex=0;
	dy_ex=0;

}


void Solution::savefinalcritical(const SCALAR * xex, const SCALAR* hex, SCALAR* uex, const SCALAR * zex) const{
	
	/**
	 * @details	 
	 * Saves x (the position), h (the water height), u (the flow velocity), z (the topography), q (the flow discharge), 
	 * z+h (the free surface), Fr (the Froude number) and z+hc (the critical surface). 
	 * @param[in] xex abscissae
	 * @param[in] hex water height
	 * @param[in] uex flow velocity
	 * @param[in] zex topography
	 */	
	
	cout << "#(i-0.5)*dx " << "\t" << setw(9) << " h[i] " << "\t"<< setw(9) << " u[i] " << "\t"<< setw(9) << " topo[i] " << "\t"<< setw(9) << " q[i] " << "\t"<< setw(9) << " topo[i]+h[i] " <<"\t" <<setw(9) << "Fr[i]=Froude" << "\t"<< setw(9) << " topo[i]+hc[i] " << "\t"<< endl;
	for (int i=1;i<NX_EX+1;i++){
		if (hex[i]<EPSILON_H){
			cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << "0.0" << "\t"<< setw(9) <<"0.0" << "\t" << setw(9) <<zex[i] << "\t" << setw(9) <<"0.0"<< "\t" << setw(9) <<zex[i]<< "\t"<< setw(9) << "NaN" << "\t"<< setw(9) << pow(uex[i]*uex[i]*hex[i]*hex[i]/GRAV,1./3.)+zex[i]<< "\t"<< endl;
		}
		else{
			cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << hex[i] << "\t"<< setw(9) <<uex[i] << "\t" << setw(9) <<zex[i] << "\t" << setw(9) <<uex[i]*hex[i]<< "\t" << setw(9) <<hex[i]+zex[i]<< "\t"<< setw(9) << abs(uex[i])/sqrt(GRAV*hex[i]) << "\t"<< setw(9) << pow(uex[i]*uex[i]*hex[i]*hex[i]/GRAV,1./3.)+zex[i]<< "\t"<< endl;
		}
	}// end of i loop
}


void Solution::savefinalcriticalinit(const SCALAR * xex, const SCALAR* hex, SCALAR* uex, const SCALAR * zex, const SCALAR* z0) const{
	
	/**
	 * @details	 
	 * Saves x (the position), h (the water height), u (the flow velocity), z (the topography), q (the flow discharge), 
	 * z+h (the free surface), Fr (the Froude number), z+hc (the critical surface),
	 * z0 (the initial topography) and z0+h (the initial surface).
	 * @param[in] xex abscissae
	 * @param[in] hex water height
	 * @param[in] uex flow velocity 
	 * @param[in] zex topography
	 * @param[in] z0 initial topography
	 */	
	
	cout << "#(i-0.5)*dx " << "\t" << setw(9) << " h[i] " << "\t"<< setw(9) << " u[i] " << "\t"<< setw(9) << " topo[i] " << "\t"<< setw(9) << " q[i] " << "\t"<< setw(9) << " topo[i]+h[i] " <<"\t" <<setw(9) << "Fr[i]=Froude" << "\t"<< setw(9) << " topo[i]+hc[i] " << "\t"<< setw(9) << "z0[i]=InitialTopo" << "\t"<< setw(9) << " z0[i]+h[i] " << "\t"<< endl;
	for (int i=1;i<NX_EX+1;i++){
		if (hex[i]<EPSILON_H){
			cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << "0.0" << "\t"<< setw(9) <<"0.0" << "\t" << setw(9) <<zex[i] << "\t" << setw(9) <<"0.0"<< "\t" << setw(9) <<zex[i]<< "\t"<< setw(9) << "NaN" << "\t"<< setw(9) << pow(uex[i]*uex[i]*hex[i]*hex[i]/GRAV,1./3.)+zex[i]<< "\t"<< setw(9) << z0[i] << "\t"<< setw(9) << z0[i] + hex[i] << "\t"<< endl;
		}
		else{
			cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << hex[i] << "\t"<< setw(9) <<uex[i] << "\t" << setw(9) <<zex[i] << "\t" << setw(9) <<uex[i]*hex[i]<< "\t" << setw(9) <<hex[i]+zex[i]<< "\t"<< setw(9) << abs(uex[i])/sqrt(GRAV*hex[i]) << "\t"<< setw(9) << pow(uex[i]*uex[i]*hex[i]*hex[i]/GRAV,1./3.)+zex[i]<< "\t"<< setw(9) << z0[i] <<"\t"<< setw(9) << z0[i]+hex[i] << "\t"<< endl;
		}
	}// end of i loop
}

void Solution::savefinalmu(const SCALAR * xex, const SCALAR* hex, const SCALAR * zex) const{
	
	/**
	 * @details	 
	 * Saves x (the position), h (the water height),
	 * z (the topography) and z+h (the free surface). 
	 * @param[in] xex abscissae
	 * @param[in] hex water height
	 * @param[in] zex topography
	 */	
	
	cout << "#(i-0.5)*dx " << "\t" << setw(9) << " h[i] " << "\t"<< setw(9) <<" topo[i] " << "\t"<< setw(9) << " topo[i]+h[i] " << "\t"<< endl;
	for (int i=1;i<NX_EX+1;i++){
		cout << setprecision(7)<< setw(9) << xex[i] << "\t"<< setw(9) << hex[i] << "\t"<< setw(9) << zex[i]<< "\t" << setw(9) <<hex[i]+zex[i]<< "\t"<< endl;
	}// end of i loop
}

void Solution::savefinal2D(const SCALAR * xex, const SCALAR * yex, TAB hex2D, TAB uex2D, TAB vex2D, TAB zex2D) const{
	
	/**
	 * @details	 
	 * Saves x and y (the position), h (the water height), u and v (the flow velocities in x and y),
	 * z+h (the free surface), z (the topography), U (the norm of the velocity), Fr (the Froude number), 
	 * qx, qy and q (the flow discharge in x, y and its norm).
	 * @param[in] xex abscissae
	 * @param[in] yex ordinates
	 * @param[in] hex2D water height
	 * @param[in] uex2D flow velocity in x
	 * @param[in] vex2D flow velocity in y
	 * @param[in] zex2D topography
	 */		
	
	cout << "#(i-0.5)*dx " << "\t" << setw(9) << "(j-0.5)*dy " << "\t" << setw(9) << " h[i][j] " << "\t"<< setw(9) << " u[i][j] " << "\t"<< setw(9) << " v[i][j] " << "\t"<< setw(9) << " topo[i][j]+h[i][j] "<< "\t"<< setw(9) << " topo[i][j] "<< "\t"<< setw(9) <<" ||U||[i][j] "<< "\t"<< setw(9) <<" Fr[i][j] "<< "\t"<< setw(9) <<" qx[i][j] "<< "\t"<< setw(9) <<" qy[i][j] " << "\t"<< setw(9) << "q[i][j]"<< endl;
	for (int i=1;i<NX_EX+1;i++){
		for (int j = 1 ; j< NY_EX+1;j++){
			if (hex2D[i][j]<EPSILON_H){
				cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << yex[j] << "\t"<< setw(9) << "0.0" << "\t"<< setw(9) <<"0.0" << "\t"<< setw(9) <<"0.0" << "\t" << setw(9) <<zex2D[i][j] << "\t" << setw(9) <<zex2D[i][j]<< "\t"<< setw(9) <<"0.0"<< "\t" << setw(9) <<"NaN" << "\t"<< setw(9) <<"0.0" << "\t" << setw(9) <<"0.0" << "\t"<< setw(9) << "0.0" << endl;
			}
			else{
				cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << yex[j] << "\t"<< setw(9) << hex2D[i][j] << "\t"<< setw(9) <<uex2D[i][j] << "\t"<< setw(9) <<vex2D[i][j] << "\t" << setw(9) <<hex2D[i][j]+zex2D[i][j] << "\t" << setw(9) <<zex2D[i][j]<< "\t"<< setw(9) << sqrt(uex2D[i][j]*uex2D[i][j] + vex2D[i][j]*vex2D[i][j])<< "\t" << setw(9) <<sqrt(pow(uex2D[i][j],2) + pow(vex2D[i][j],2))/sqrt(GRAV*hex2D[i][j]) << "\t"<< setw(9) <<hex2D[i][j]*uex2D[i][j] << "\t" << setw(9) <<hex2D[i][j]*vex2D[i][j] << "\t"<< setw(9) << hex2D[i][j]*sqrt(uex2D[i][j]*uex2D[i][j] + vex2D[i][j]*vex2D[i][j]) << endl;
			}
		}
		cout << endl;
		
	}// end of i loop
}

void Solution::savefinalSpherical(const SCALAR* lambdaex,const SCALAR* thetaex, TAB hex2D, TAB uex2D, TAB vex2D, TAB rhoex) const{
	/**
	 * @details
	 * Saves x and y (the position), h (the water height), u and v (the flow velocities in x and y),
	 * z+h (the free surface), z (the topography), U (the norm of the velocity), Fr (the Froude number),
	 * qx, qy and q (the flow discharge in x, y and its norm).
	 * @param[in] lambdaex longitudinal angle
	 * @param[in] thetaex latitudinal angle
	 * @param[in] hex2D water height
	 * @param[in] uex2D longitudinale flow velocity component
	 * @param[in] vex2D latitudinale flow velocity component
	 * @param[in] rhoex topography
	 */

	cout << "#lambda " << "\t" << setw(9) << "theta " << "\t" << setw(9) << " h[i][j] " << "\t" << setw(9) << " u[i][j] " << "\t" << setw(9) << " v[i][j] " << "\t" << setw(9) << " topo[i][j]+h[i][j] " << "\t" << setw(9) << " topo[i][j] " << "\t" << setw(9) << " ||U||[i][j] " << "\t" << setw(9) << " Fr[i][j] " << "\t" << setw(9) << " qx[i][j] " << "\t" << setw(9) << " qy[i][j] " << "\t" << setw(9) << "q[i][j]" << endl;
	for (int i = 0; i < NX_EX+1; i++) {
		for (int j = 0; j < NY_EX ; j++) {
			if (hex2D[i][j] < EPSILON_H) {
				cout << setprecision(7)<< setw(9)<< lambdaex[i] << "\t" << setw(9) << thetaex[j] << "\t" << setw(9) << "0.0" << "\t" << setw(9) << "0.0" << "\t" << setw(9) << "0.0" << "\t" << setw(9) << rhoex[i][j] << "\t" << setw(9) << rhoex[i][j] << "\t" << setw(9) << "0.0" << "\t" << setw(9) << "NaN" << "\t" << setw(9) << "0.0" << "\t" << setw(9) << "0.0" << "\t" << setw(9) << "0.0" << endl;
			}
			else {
				cout << setprecision(7)<< setw(9)<< lambdaex[i] << "\t" << setw(9) << thetaex[j] << "\t" << setw(9) << hex2D[i][j] << "\t" << setw(9) << uex2D[i][j] << "\t" << setw(9) << vex2D[i][j] << "\t" << setw(9) << hex2D[i][j] + rhoex[i][j] << "\t" << setw(9) << rhoex[i][j] << "\t" << setw(9) << sqrt(uex2D[i][j] * uex2D[i][j] + vex2D[i][j] * vex2D[i][j]) << "\t" << setw(9) << sqrt(pow(uex2D[i][j], 2) + pow(vex2D[i][j], 2)) / sqrt(GRAV * hex2D[i][j]) << "\t" << setw(9) << hex2D[i][j] * uex2D[i][j] << "\t" << setw(9) << hex2D[i][j] * vex2D[i][j] << "\t" << setw(9) << hex2D[i][j] * sqrt(uex2D[i][j] * uex2D[i][j] + vex2D[i][j] * vex2D[i][j]) << endl;
			}
		}
		cout << endl;

	}// end of i loop
}

void Solution::savefinalConcentrations(const SCALAR* xex, SCALAR* phiex, SCALAR* psiex, SCALAR* phi0, SCALAR* psi0) const{
	/**
	 * @details
	 * Saves x (the position), phi (the dissolved solute concentration), psi (the adsorbed solute concentration),
	 * and phi0 (the initial dissolved concentration), psib (the initial adsorbed solute concentration).
	 * @param[in] xex abscissae
	 * @param[in] phiex dissolved solute concentration
	 * @param[in] psiex adsorbed solute concentration
	 * @param[in] phi0 initial dissolved solute concentration
	 * @param[in] psi0 initial adsorbed solute concentration
	 */

	cout << "# (i-0.5)*dx " << "\t" << setw(9) << " phi[i] " << "\t" << setw(9) << " psi[i] " << "\t" << setw(9) << " phi0[i]"<< "\t" << setw(9) << " psi0[i]" << "\t"<< endl;
	for (int i=1;i<NX_EX+1;i++){
		cout << setprecision(7)<< setw(9)<< xex[i] << "\t"<< setw(9) << phiex[i] << "\t"<< setw(9) << psiex[i]<< "\t" << setw(9) << phi0[i]<< "\t" << setw(9) << psi0[i]<< "\t"<< endl;
	}// end of i loop
}


void Solution::head(const Parameters & par, const string & solutiontype, const string & solutionchoice) const{
	
	/**
	 * @details	 
	 * @param[in] par parameter, contains all the values from the parameters file
	 * @param[in] solutiontype name of the type of the solution
	 * @param[in] solutionchoice name of the solution
	 */	
	
	cout << "##############################################################################" << endl;
	cout << "# Generated by " << VERSION <<endl;
	cout << "##############################################################################" << endl;
	cout << "# Dimension: " << par.get_choicedim() << endl;
	cout << "# Type: "<< par.get_choicetype() <<" (="<< solutiontype << ")"<< endl;
	cout << "# Domain: " << par.get_choicedomain() << endl;
	cout << "# Choice: "<< par.get_choice() <<" (="<< solutionchoice<<")" << endl;
	cout << "##############################################################################" << endl;
}


Solution::~Solution(){
	deallocation();
}


void Solution::allocation(){
	
	/**
	 * @details	 
	 * Allocation of Solution::xex, Solution::yex, Solution::hex, Solution::uex, Solution::qex, Solution::zex.
	 * @warning Problem: allocation of xex failed.
	 * @warning Problem: allocation of yex failed.
	 * @warning Problem: allocation of hex failed.
	 * @warning Problem: allocation of uex failed.
	 * @warning Problem: allocation of qex failed.
	 * @warning Problem: allocation of zex failed.
	 * @note If a vector cannot be allocated, the code will exit with failure termination code.
	 */	
	
	xex = new SCALAR[NX_EX+1];
	if(NULL==xex){
		fprintf(stderr, "\nProblem: allocation of xex failed\n");
		exit(EXIT_FAILURE);
	}
	
	yex = new SCALAR[NY_EX+1];
	if(NULL==yex){
		fprintf(stderr, "\nProblem: allocation of yex failed\n");
		exit(EXIT_FAILURE);
	}
	
	hex = new SCALAR[NX_EX+1];
	if(NULL==hex){
		fprintf(stderr, "\nProblem: allocation of hex failed\n");
		exit(EXIT_FAILURE);
	}
	
	uex = new SCALAR[NX_EX+1];
	if(NULL==uex){
		fprintf(stderr, "\nProblem: allocation of uex failed\n");
		exit(EXIT_FAILURE);
	}
	
	qex = new SCALAR[NX_EX+1];
	if(NULL==qex){
		fprintf(stderr, "\nProblem: allocation of qex failed\n");
		exit(EXIT_FAILURE);
	}
	
	zex = new SCALAR[NX_EX+1];
	if(NULL==zex){
		fprintf(stderr, "\nProblem: allocation of zex failed\n");
		exit(EXIT_FAILURE);
	}
	
}

void Solution::deallocation(){
	
	/**
	 * @details	 
	 * Deallocation of Solution::xex, Solution::yex, Solution::hex, Solution::uex, Solution::qex, Solution::zex.
	 */	
	
	delete [] xex;
	delete [] yex;
	delete [] hex;
	delete [] uex;
	delete [] qex;
	delete [] zex;
}

