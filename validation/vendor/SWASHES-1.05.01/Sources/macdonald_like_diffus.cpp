/**
 * @file macdonald_like_diffus.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes Mac Donald solutions with diffusion
 * @details 
 * Analytic solution: Mac Donald solutions in 1d with diffusion, see \cite Delestre10.
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

#include "macdonald_like_diffus.hpp"

MacDonald_like_diffus::MacDonald_like_diffus(Parameters & par):Solution(par){
	
	/** 
	 * @details 
	 * Defines the physical parameters and prints the header with the configuration.\n 
	 * The solution is saved at the steady state. 
	 * @param[in] par contains all the values from the parameters
	 * @warning Problem: allocation of dhex failed.
	 * @warning Problem: allocation of ddhex failed.
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#hex, Solution#qex to have Mac Donald configuration. 
	 * @note If the vector dhex (or ddhex) cannot be allocated, the code will exit with failure termination code.
	 */	

	varz=0;

	dhex = new SCALAR[NX_EX+1];//array for the water height variations
	if(NULL==dhex){
		fprintf(stderr, "\nProblem: allocation of dhex failed\n");
		exit(EXIT_FAILURE);
	}
	
	ddhex = new SCALAR[NX_EX+1];//array for the diffusion term (second order derivative)
	if(NULL==ddhex){
		fprintf(stderr, "\nProblem: allocation of ddhex failed\n");
		exit(EXIT_FAILURE);
	}


	/***********************************************************************
	 * L=1000 m channels cases (linear and quadratic friction)
	 ***********************************************************************/
	L = 1000.;
	dx_ex = L/NX_EX; //space step
	
	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
	}

	/***********************************************************************
	 * subcritical case
	 ***********************************************************************/
	if(par.get_choice()==1){
		
		for (int i=0 ; i<=NX_EX ; i++){
			hex[i] = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(xex[i]/1000.-1./2.,2.))/2.);
			dhex[i] = -2.*(pow(4./GRAV,1./3.))*(xex[i]/1000.-1./2.)*exp(-16.*pow(xex[i]/1000.-1./2.,2.))/125.;
			ddhex[i] = -pow(4./GRAV,1./3.)*(1.-32.*(xex[i]/1000.-1./2.)*(xex[i]/1000.-1./2.))*exp(-16.*(xex[i]/1000.-1./2.)*(xex[i]/1000.-1./2.))/62500.;
			qex[i] = 1.5;
		}//end for
		
		kt = 0.01;
		kl = 0.001;
		muv = 0.01;
		muh = 0.001;
		
		h_r_bound = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(L/1000.-1./2.,2.))/2.);
		
		head(par, "MacDonald", "long channel with subcritical flow and diffusion");
		param(L, dx_ex);
		cout << "# Values of the parameters: kt="<< kt<< " , kl="<< kl<< " , mu_v=" << muv<< " , mu_h=" << muh<< endl;
		cout << "# " << endl;
		cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s"<< endl;
		cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
		cout << "##############################################################################"<<endl;
		
		/***********************************************************************
		 * supercritical case
		 ***********************************************************************/
		}else{
			for (int i=0 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(xex[i]/1000.-1./2.,2.))/5.);
				dhex[i] = (pow(4./GRAV,1./3.))*9.*exp(-36.*pow(xex[i]/1000.-1./2.,2.))*((xex[i]/1000.)-(1./2.))/625.;
				ddhex[i] = pow(4./GRAV,1./3.)*9.*(1.-72.*(xex[i]/1000.-1./2.)*(xex[i]/1000.-1./2.))*exp(-36.*(xex[i]/1000.-1./2.)*(xex[i]/1000.-1./2.))/625000.;
				qex[i] = 2.5;
			}//end for
			
			kt = 0.005;
			kl = 0.001;
			muv = 0.01;
			muh = 0.1;
			
			h_l_bound = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(-1./2.,2.))/5.);
			
			head(par, "MacDonald", "long channel with supercritical flow and diffusion");
			param(L, dx_ex);
			cout << "# Values of the parameters: kt="<< kt<< " , kl="<< kl<< " , mu_v=" << muv<< " , mu_h=" << muh<< endl; 
			cout << "# " << endl;
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: "<< h_l_bound <<" m"<< endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s" << endl;
			cout << "##############################################################################"<<endl;
			
		} //end if
}


MacDonald_like_diffus::~MacDonald_like_diffus(){
	delete [] dhex;
	delete [] ddhex;
}


void MacDonald_like_diffus::compute(){
	
	/**
	 * @details 
	 * Computes Mac Donald solutions with diffusion, see \cite Delestre10.
	 * @par Modifies 
	 * Solution#zex.
	 */

	/***********************************************************************
	 * zex is the topography associated to the chosen steady flow
	 ***********************************************************************/
	
	varz = Delta_topo_diffus(qex[NX_EX],hex[NX_EX],dhex[NX_EX],ddhex[NX_EX],kt,kl,muv,muh);
	zex[NX_EX] = 0.5*dx_ex*varz;
	// zex =0 on the boundary ("NX_EX + 1/2")
	
	for (int i=NX_EX ; i>=1 ; i--){
			varz = Delta_topo_diffus(qex[i],hex[i],dhex[i],ddhex[i],kt,kl,muv,muh);
			zex[i-1] = dx_ex*varz+zex[i];
	}
	
	for (int i =0; i<=NX_EX; i++){
		if (abs(hex[i])  > EPSILON) {
			uex[i] = qex[i] / hex[i];
		}
		else {
			uex[i] = 0.0;
		}
	}
	
	savefinalcritical(xex, hex, uex, zex);
}


SCALAR MacDonald_like_diffus::Delta_topo_diffus(SCALAR q, SCALAR h, SCALAR dh, SCALAR ddh, SCALAR kt, SCALAR kl, SCALAR muv, SCALAR muh) const{
	
	/**
	 * @details
	 * @param[in] q discharge
	 * @param[in] h water height 
	 * @param[in] dh variation of the water height
	 * @param[in] ddh second order derivative of h
	 * @param[in] kt turbulent coefficient
	 * @param[in] kl laminar coefficient
	 * @param[in] muv vertical viscosity
	 * @param[in] muh horizontal viscosity
	 * @return Value of \f$\displaystyle \left(1-\frac{q^2}{gh^3}\right) dh + \frac{kl\,q}{gh^2(1+\frac{kl\, h}{3muv})}+ \frac{kt\,q^2}{gh^2(1+\frac{kl\, h}{3muv})^2} + 4muh \frac{q\, ddh - \frac{q\, dh^2}{h}}{gh^2}\f$.
	 */	
	
	return (1.-pow(q,2.)/(GRAV*pow(h,3.)))*dh+kl*q/(GRAV*pow(h,2.)*(1.+kl*h/(3.*muv)))+kt*pow(q,2.)/(GRAV*pow(h,2.)*pow(1.+kl*h/(3.*muv),2.))+4.*muh*(q*ddh-q*dh*dh/h)/(GRAV*h*h);
}

void MacDonald_like_diffus::param(SCALAR L, SCALAR dx_ex) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain 
	 * @param[in] dx_ex space step 
	 */
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Solution at the steady state" << endl;
	cout << "# "<< endl;
	
}

