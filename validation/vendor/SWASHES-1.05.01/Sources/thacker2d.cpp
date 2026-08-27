/**
 * @file thacker2d.cpp
 * @author Pierre-Antoine Ksinant <pierreantoine.ksinantgarcia@gmail.com> (2011)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2011-2015)
 * @version 1.03.00
 * @date 2015-10-28
 *
 * @brief Computes %Thacker solution in 2D
 * @details 
 * Analytic solution: %Thacker paraboloid, see \cite Thacker81.
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

#include "thacker2d.hpp"

Thacker2D::Thacker2D(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters, the final time and prints the header with the configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#l, Solution#T, Solution#xex, Solution#yex, Thacker2D#zex2D 
	 * to have %Thacker 2D configuration. 
	 */
	
	L = 4.;
	l = L;
	dx_ex = L/NX_EX;
	dy_ex = l/NY_EX;
	a = 1.;
	h0 = 0.1;

	for (int j=0 ; j<=NY_EX ; j++){
		yex[j] = (j-0.5)*dy_ex;
	}
	
	radius2.resize(NX_EX+1); // i : 0->NX_EX
	zex2D.resize(NX_EX+1); // i : 0->NX_EX
	uex2D.resize(NX_EX+1); // i : 0->NX_EX
	vex2D.resize(NX_EX+1); // i : 0->NX_EX
	hex2D.resize(NX_EX+1); // i : 0->NX_EX
	
	for (int i=0 ; i<=NX_EX ; i++){
		radius2[i].resize(NY_EX+1); // j : 0->NY_EX
		zex2D[i].resize(NY_EX+1); // j : 0->NY_EX
		uex2D[i].resize(NY_EX+1); // j : 0->NY_EX
		vex2D[i].resize(NY_EX+1); // j : 0->NY_EX
		hex2D[i].resize(NY_EX+1); // j : 0->NY_EX
		
		xex[i] = (i-0.5)*dx_ex;
		zmin = 1000;
		for (int j=0;j<=NY_EX;j++){
			radius2[i][j] = (xex[i]-L/2.)*(xex[i]-L/2.)+(yex[j]-l/2.)*(yex[j]-l/2.);
			zex2D[i][j] = h0*(radius2[i][j]/(a*a)-1.);
			if (zmin > zex2D[i][j]) zmin = zex2D[i][j];
		}
	}
		
	if(par.get_choice()==1){	
		solu =1;
		r0 = 0.8;
		omega=sqrt(8.*GRAV*h0)/a;
		T = 3; //in periods
		T = 2.*PI*T/omega; // in seconds
		A=(a*a-r0*r0)/(a*a+r0*r0);
		Aa=1.-A*A;
		cAa=1.-A*cos(omega*T);
		head(par, "Oscillations", "Radially-symmetrical paraboloid (Thacker's solution)");
		param(L,l, h0, a, dx_ex,dy_ex, T);
		cout << "# parameter r0 = "<< r0 << endl;
		cout << "##############################################################################"<<endl;

	}
	else{
		solu =2;
		eta = 0.5;
		omega=sqrt(2.*GRAV*h0)/a;
		T = 3; //in periods
		T = 2.*PI*T/omega; // in seconds
		head(par, "Oscillations", "Planar surface in a paraboloid (Thacker's solution)");
		param(L,l, h0, a, dx_ex,dy_ex, T);
		cout << "# parameter eta = "<< eta << endl;
		cout << "##############################################################################"<<endl;
		}
	
}

Thacker2D::~Thacker2D(){
	for (int i=0 ; i<=NX_EX ; i++){
		radius2[i].clear();
		zex2D[i].clear();
		uex2D[i].clear();
		vex2D[i].clear();
		hex2D[i].clear();
	}
	radius2.clear();
	zex2D.clear();
	uex2D.clear();
	vex2D.clear();
	hex2D.clear();
}


void Thacker2D::compute(){
	
	/**
	 * @details 
	 * Computes the chosen %Thacker 2D solution, see \cite Thacker81.
	 * @par Modifies 
	 * Thacker2D#hex2D, Thacker2D#uex2D, Thacker2D#vex2D.
	 */
	
	if(solu==1){
		for (int i=0;i<=NX_EX;i++){
			for (int j=0;j<=NY_EX;j++){	
				hex2D[i][j]=h0*((sqrt(Aa)/cAa)-1.-(radius2[i][j]/(a*a))*(Aa/(cAa*cAa)-1.)) - zex2D[i][j];
				if(hex2D[i][j]<0.) hex2D[i][j]=0.;
				uex2D[i][j]=(1./cAa)*(0.5*omega*(xex[i]-L/2)*A*sin(omega*T));
				vex2D[i][j]=(1./cAa)*(0.5*omega*(yex[j]-l/2)*A*sin(omega*T));
			}
		}
	}
	else{// choice=2
		for(int i=0;i<=NX_EX;i++){
			for(int j=0;j<=NY_EX;j++){	
				hex2D[i][j]=((eta*h0)/(a*a))*(2*(xex[i]-L/2)*cos(omega*T)+2*(yex[j]-l/2)*sin(omega*T)-eta) - zex2D[i][j];
				if(hex2D[i][j]<0.){
					hex2D[i][j]=0.;
				}
				uex2D[i][j]=-eta *omega*sin(omega*T);
				vex2D[i][j]=eta*omega*cos(omega*T);
			}
		}
	}
	
	savefinal2D(xex, yex, hex2D, uex2D, vex2D, zex2D);

}


void Thacker2D::param(SCALAR L, SCALAR l, SCALAR h0, SCALAR a, SCALAR dx_ex, SCALAR dy_ex, SCALAR T) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain in x
	 * @param[in] l length of the domain in y
	 * @param[in] h0 value of the topography in the center of the domain
	 * @param[in] a parameter of the topography
	 * @param[in] dx_ex space step in x
	 * @param[in] dy_ex space step in y
	 * @param[in] T final time
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Width of the domain: " << l << " meters" << endl;
	cout << "# Space step in x: "<< dx_ex << " meters"<< endl;
	cout << "# Space step in y: "<< dy_ex << " meters"<< endl;
	cout << "# Number of cells in x: " << NX_EX << endl;
	cout << "# Number of cells in y: " << NY_EX << endl;
	cout << "# Topography: z(x) = h0 (((x-L/2)^2+(y-l/2)^2)/a^2 -1), with h0="<< h0<< " meters and a=" << a <<" meters"<<endl;
	cout << "# Time value: " << T << " seconds" << endl;
}

