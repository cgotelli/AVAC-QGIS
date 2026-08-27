/**
 * @file macdonaldb1.cpp
 * @author Pierre-Antoine Ksinant <pierreantoine.ksinantgarcia@gmail.com> (2011)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2011-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes Mac Donald pseudo 2d solutions
 * @details 
 * Analytic solution: Mac Donald pseudo 2d solutions with bottom B1, see \cite MacDonald96.
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

#include "macdonaldb1.hpp"

MacDonaldB1::MacDonaldB1(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters and prints the header with the configuration.\n 
	 * The solution is saved at the steady state. 
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#hex to have Mac Donald configuration. 
	 */	

	hpex.resize(NX_EX+1);
	b.resize(NX_EX+1);
	bp.resize(NX_EX+1);
	
	Q = 20. ;			//discharge
	Z=0.;				// slope of the boundaries of the channel
	L = 200;			// length of the domain 
	dx_ex = L/NX_EX;	// space step
	n=0.03;				// Manning friction coefficient
	
	expo_1=4./3.;		// temporary values for the formula of res
	expo_2=10./3.;

	res =0;
	
	for (int i=1 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = 0.;
		b[i]=10.-5.*exp(-10.*pow((xex[i]/200.)-0.5,2.));					// boundary
		bp[i]=0.5*((xex[i]/200.)-0.5)*exp(-10.*pow((xex[i]/200.)-0.5,2.));	// derivative of the boundary
	}
	
	if (1==par.get_choice()){ // subcritical
		head(par, "MacDonald pseudo2D", "Rectangular short channel B1 with subcritical flow");
		param(L, dx_ex, n);
		
		for (int i=1 ; i<=NX_EX ; i++){		
			hex[i]=0.9+0.3*exp(-20.*pow((xex[i]/200.)-0.5,2.));
			hpex[i]=-0.06*((xex[i]/200.)-0.5)*exp(-20.*pow((xex[i]/200.)-0.5,2.));
		}
		
		h_r_bound = 0.9+0.3*exp(-20.*pow(0.5,2.));
		
		cout << "# Initial conditions: h = max("<<h_r_bound << "- z(x), 0) m and q = 0 m^3/s" << endl; // note that z(L) = 0
		cout << "# Imposed discharge on the left boundary: " << Q << " m^3/s"<< endl;
		cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
		cout << "############################################################################## " << endl;
	}
	else if (2==par.get_choice()){ // supercritical
		head(par, "MacDonald pseudo2D", "Rectangular short channel B1 with supercritical flow");
		param(L, dx_ex, n);
		
		for (int i=1 ; i<=NX_EX ; i++){		
			hex[i]=0.5+0.5*exp(-20.*pow((xex[i]/200.)-0.5,2.));
			hpex[i]=-0.1*((xex[i]/200.)-0.5)*exp(-20*pow((xex[i]/200.)-0.5,2.));
		}
		
		h_l_bound = 0.5+0.5*exp(-20.*pow(-0.5,2.));
		
		cout << "# Initial conditions: h = 0 m and q = 0 m^3/s" << endl;
		cout << "# Imposed discharge on the left boundary: " << Q << " m^3/s"<< endl;
		cout << "# Imposed water height on the left boundary: "<< h_l_bound << " m" << endl;
		cout << "############################################################################## " << endl;
	}
	else if (3==par.get_choice()){ // smooth transition
		head(par, "MacDonald pseudo2D", "Rectangular short channel B1 with smooth transition");
		param(L, dx_ex, n);
		
		for (int i=1 ; i<=NX_EX ; i++){		
			hex[i]=1.-0.3*tanh(4.*((xex[i]/200.)-(1./3.)));
			hpex[i]=-0.006*pow(1./cosh(4.*((xex[i]/200.)-(1./3.))),2.);
		}
		
		cout << "# Initial conditions: h = 0 m and q = 0 m^3/s" << endl;
		cout << "# Imposed discharge on the left boundary: " << Q << " m^3/s"<< endl;
		cout << "############################################################################## " << endl;
	}
	else if (4==par.get_choice()){ // hydraulic jump
		head(par, "MacDonald pseudo2D", "Rectangular short channel B1 with hydraulic jump");
		param(L, dx_ex, n);
		
		for (int i=1 ; i<=NX_EX ; i++){	
			if(xex[i]<=120.){
				hex[i]=0.7+0.3*(expm1(xex[i]/200.)); // For small magnitude values of x, expm1 may be more accurate than exp(x)-1.
				hpex[i]=0.0015*exp(xex[i]/200.);
			}
			else{
				hex[i]=1.5*exp(0.1*((xex[i]/200.)-1.))+exp(-0.1*(xex[i]-120.))*(-0.154375-0.108189*((xex[i]-120.)/80.)-2.01431*pow((xex[i]-120.)/80.,2.));
				hpex[i]=0.00075*exp(0.1*((xex[i]/200.)-1.))+exp(-0.1*(xex[i]-120.))*((-0.108189/80.)-(2.014310/40.)*((xex[i]-120.)/80.))-0.1*exp(-0.1*(xex[i]-120.))*(-0.154375-0.108189*((xex[i]-120.)/80.)-2.01431*pow((xex[i]-120.)/80.,2.));
			}
		}
		
		h_l_bound = 0.7;
		h_r_bound = 1.5+exp(-0.1*(80.))*(-0.154375-0.108189*1.-2.01431*pow(1.,2.));
		
		cout << "# Initial conditions: h = max("<<h_r_bound << "- z(x), 0) m and q = 0 m^3/s" << endl; // note that z(L) = 0
		cout << "# Imposed discharge on the left boundary: " << Q << " m^3/s"<< endl;
		cout << "# Imposed water height on the left boundary: "<< h_l_bound << " m" << endl;
		cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
		cout << "############################################################################## " << endl;
	}
	
}


void MacDonaldB1::compute(){
	
	/**
	 * @details 
	 * Computes Mac Donald solutions with bottom B1, see \cite MacDonald96.
	 * @par Modifies 
	 * Solution#zex.
	 */
	
	// integration of the topography
	// res = - S_0(x) => z=int_L^x res => z(L) =0
	
	res = Delta_topo(hex[NX_EX], hpex[NX_EX], b[NX_EX], bp[NX_EX], Q, n, Z, expo_1, expo_2);
	zex[NX_EX] = -0.5* dx_ex*res;
	
	for (int i=NX_EX;i>=1;i--){
		res = Delta_topo(hex[i], hpex[i], b[i], bp[i], Q, n, Z, expo_1, expo_2);
		zex[i-1] = zex[i] -dx_ex*res; 
	}
	
	savefinalmu(xex, hex, zex);

}

SCALAR MacDonaldB1::Delta_topo(SCALAR h, SCALAR hp, SCALAR b, SCALAR bp, SCALAR Q, SCALAR n, SCALAR Z, SCALAR exp1, SCALAR exp2) const{
	
	/**
	 * @details
	 * @param[in] h water height
	 * @param[in] hp derivative of the water height
	 * @param[in] b boundary function
	 * @param[in] bp derivative of the boundary function
	 * @param[in] Q discharge
	 * @param[in] n friction coefficient
	 * @param[in] Z slope
	 * @param[in] exp1 exponent, equal to 4/3
	 * @param[in] exp2 exponent, equal to 10/3
	 * @return Value of \f$\displaystyle hp\left(\frac{Q^2(b+2Zh)}{g(h(b+Zh))^3}-1\right)-Q^2 n^2 \frac{(b+2h\sqrt{1+Z^2})^{exp1}}{(h(b+Zh))^{exp2}}+ \frac{Q^2bp}{gh^2(b+Zh)^3}\f$.
	 */	
	
	return hp*(((pow(Q,2.)*(b+2.*Z*h))/(GRAV*pow(h*(b+Z*h),3.)))-1.)-pow(Q*n,2.)*(pow(b+2.*h*sqrt(1.+pow(Z,2.)),exp1)/pow(h*(b+Z*h),exp2))+(pow(Q,2.)*bp)/(GRAV*pow(h,2.)*pow(b+Z*h,3.));
}

void MacDonaldB1::param(SCALAR L, SCALAR dx_ex, SCALAR n) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] dx_ex space step 
	 * @param[in] n friction coefficient 
	 */	
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step in x: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells in x: " << NX_EX << endl;
	cout << "# Topography: z(x) saved in the output"<<endl;
	cout << "# Solution at the steady state" << endl;
	cout << "# "<<endl;
	cout << "# Manning's friction coefficient: " << n << " m^-1/3 s" << endl;
	cout << "# " << endl;
	
}

MacDonaldB1::~MacDonaldB1(){
	hpex.clear();
	b.clear();
	bp.clear();
}



