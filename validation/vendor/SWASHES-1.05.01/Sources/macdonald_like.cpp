/**
 * @file macdonald_like.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes Mac Donald solutions
 * @details 
 * Analytic solution: Mac Donald solutions in 1d, 
 * see \cite MacDonald96, \cite MacDonald97, \cite Delestre13 and \cite Vo08.
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

#include "macdonald_like.hpp"

MacDonald_like::MacDonald_like(Parameters & par):Solution(par){

	/** 
	 * @details 
	 * Defines the physical parameters and prints the header with the configuration.\n 
	 * The solution is saved at the steady state. 
	 * @param[in] par contains all the values from the parameters
	 * @warning Problem: allocation of dhex failed.
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#hex, Solution#qex to have Mac Donald configuration. 
	 * @note If the vector dhex cannot be allocated, the code will exit with failure termination code.
	 */	

	varz=0;

	dhex = new SCALAR[NX_EX+1];//array for the water height variations
	if(NULL==dhex){
		fprintf(stderr, "\nProblem: allocation of dhex failed\n");
		exit(EXIT_FAILURE);
	}
	
	//Manning for even numbers, Darcy-Weisbach for odd numbers. 
	
	/***********************************************************************
	 * L=1000 m channels cases (either Manning or Darcy-Weisbach)
	 ***********************************************************************/
	if(par.get_choicedomain()==1){ //Long channel L=1000 m
		L = 1000.;
		R = 0.; //no rain
		dx_ex = L/NX_EX; //space step
		choice_fric = par.get_choice()-(par.get_choice()/2)*2; //we get 0 for the Manning law and 1 for the Darcy-Weisbach law
		
		for (int i=1 ; i<=NX_EX ; i++){
			xex[i] = (i-0.5)*dx_ex;
		}

		/***********************************************************************
		 * subcritical flow 
		 ***********************************************************************/
		if((par.get_choice()==1)||(par.get_choice()==2)){
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(xex[i]/1000.-1./2.,2.))/2.);
				dhex[i] = -2.*(pow(4./GRAV,1./3.))*(xex[i]/1000.-1./2.)*exp(-16.*pow(xex[i]/1000.-1./2.,2.))/125.;
				qex[i] = 2.;
			}//end for
			
			h_r_bound = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(L/1000.-1./2.,2.))/2.);
			
			head(par, "MacDonald", "long channel with subcritical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s"<< endl;
			cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
			cout << "# " << endl;

			if(choice_fric==0){ //Manning
				cf = 0.033;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.093;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}

		/***********************************************************************
		 * supercritical flow
		 ***********************************************************************/
		}else if((par.get_choice()==3)||(par.get_choice()==4)){
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(xex[i]/1000.-1./2.,2.))/5.);
				dhex[i] = (pow(4./GRAV,1./3.))*9.*exp(-36.*pow(xex[i]/1000.-1./2.,2.))*((xex[i]/1000.)-(1./2.))/625.;
				qex[i] = 2.5;
			}//end for
			
			h_l_bound = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(-1./2.,2.))/5.);
			
			head(par, "MacDonald", "long channel with supercritical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: "<< h_l_bound <<" m"<< endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s" << endl;
			cout << "# " << endl;

			if(choice_fric==0){ //Manning
				cf = 0.04;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.065;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}

		/***********************************************************************
		 * sub- to super-critical flow 
		 ***********************************************************************/
		}else if((par.get_choice()==5)||(par.get_choice()==6)){
			for (int i=1 ; i<=NX_EX ; i++){
				if (xex[i]<=500.){
					hex[i] = (pow(4./GRAV,1./3.))*(1.-(tanh(3.*(xex[i]/1000.-1./2.)))/3.);
					dhex[i] = (-pow(4./GRAV,1./3.))/(1000.*pow(cosh(3.*(xex[i]/1000.-1./2.)),2.));
					qex[i] = 2.;
				}else{
					hex[i] = (pow(4./GRAV,1./3.))*(1.-tanh(6.*(xex[i]/1000.-1./2.))/6.);
					dhex[i] = (-pow(4./GRAV,1./3.))/(1000.*pow(cosh(6.*(xex[i]/1000.-1./2.)),2.));
					qex[i] = 2.;
				}//end if
			}//end for
			
			head(par, "MacDonald", "long channel with sub- to super-critical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s"<< endl;
			cout << "# " << endl;
			
			if(choice_fric==0){ //Manning
				cf = 0.0218;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.042;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}

		/***********************************************************************
		 * super- to sub-critical flow
		 ***********************************************************************/
		}else{
			for (int i=1 ; i<=NX_EX ; i++){
				if (xex[i]<=500.){
					hex[i] = (pow(4./GRAV,1./3.))*(9./10.-exp(-xex[i]/250.)/6.);
					dhex[i] = (pow(4./GRAV,1./3.))*exp(-xex[i]/250.)/1500.;
					qex[i] = 2.;
				}else{
					hex[i] = (pow(4./GRAV,1./3.))*(1.-0.348427*exp(-20.*(xex[i]/1000.-1./2.)) +
						0.552264*exp(-40.*(xex[i]/1000.-1./2.))-0.55558*exp(-60.*(xex[i]/1000.-1./2.)) +
						4.*exp(xex[i]/1000.-1.)/5.);
					dhex[i] = (pow(4./GRAV,1./3.))*((-0.348427*exp(-20.*(xex[i]/1000.-1./2.)) +
						2.*0.552264*exp(-40.*(xex[i]/1000.-1./2.)) -
						3.*0.55558*exp(-60.*(xex[i]/1000.-1./2.)))/(-50.)+exp(xex[i]/1000.-1.)/1250.);
					qex[i] = 2.;
				}//end if
			}//end for
			
			h_l_bound = (pow(4./GRAV,1./3.))*(9./10.-1/6.);
			h_r_bound = (pow(4./GRAV,1./3.))*(1.-0.348427*exp(-20.*(L/1000.-1./2.)) +0.552264*exp(-40.*(L/1000.-1./2.))-0.55558*exp(-60.*(L/1000.-1./2.)) + 4.*exp(L/1000.-1.)/5.);
			
			head(par, "MacDonald", "long channel with super- to sub-critical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: "<<h_l_bound<<" m"<< endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s"<< endl;		
			cout << "# Imposed water height on the right boundary: "<< h_r_bound<<" m" << endl;
			cout << "# " << endl;

			if(choice_fric==0){ //Manning
				cf = 0.0218;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.0425;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}
		}


	/***********************************************************************
	 * L=100 m channels cases (only Manning, easy to get with Darcy-Weisbach)
	 ***********************************************************************/
	}else if (par.get_choicedomain()==2){ //Short channel L=100 m
		L = 100.;
		R = 0.; //no rain
		dx_ex = L/NX_EX; //space step
		choice_fric = par.get_choice()-(par.get_choice()/2)*2; //we get 0 for the Manning law and 1 for the Darcy-Weisbach law

		for (int i=1 ; i<=NX_EX ; i++){
			xex[i] = (i-0.5)*dx_ex;
		}

		/***********************************************************************
		 * smooth transition and shock (Manning) case 
		 ***********************************************************************/
		if(par.get_choice()==2){
			for (int i=1 ; i<=NX_EX ; i++){
				if (xex[i]<=200./3.){
					hex[i] = (pow(4./GRAV,1./3.))*(4./3.-xex[i]/100.)-9.*xex[i]*(xex[i]/100.-2./3.)/1000.;
					dhex[i] = pow(4./GRAV,1./3.)*(-1./100.)-9.*(xex[i]/100.-1./3.)/500.;
					qex[i] = 2.;
				}else{
					hex[i] = pow(4./GRAV,1./3.)*(0.674202*pow(xex[i]/100.-2./3.,4.) +
												 0.674202*pow(xex[i]/100.-2./3.,3.)-21.7112*pow(xex[i]/100.-2./3.,2.) +
												 14.492*(xex[i]/100.-2./3.)+1.4305);
					dhex[i] = pow(4./GRAV,1./3.)*(0.02696808*pow(xex[i]/100.-2./3.,3.) + 
												  0.02022606*pow(xex[i]/100.-2./3.,2.)-0.434224*(xex[i]/100.-2./3.)+0.14492);
					qex[i] = 2.;
				}//end if
			}
			
			h_r_bound =pow(4./GRAV,1./3.)*(0.674202*pow(1.-2./3.,4.) +0.674202*pow(1.-2./3.,3.)-21.7112*pow(1.-2./3.,2.) +14.492*(1.-2./3.)+1.4305);
			
			head(par, "MacDonald", "short channel with smooth transition and shock");
			param(L, dx_ex);
			cout << "# Initial conditions: h = max("<<h_r_bound <<" - z , 0) m and q = 0 m^2/s" << endl; // note that z(L) = 0
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s" << endl;			
			cout << "# Imposed water height on the right boundary: " <<h_r_bound << " m"<< endl;
			cout << "# " << endl;
			
			cf = 0.0328;
			cout << "# Manning's friction coefficient: " << cf << endl;
			cout << "##############################################################################"<<endl;
			

		/***********************************************************************
		 * supercritical (Manning) case
		 ***********************************************************************/
		}else if(par.get_choice()==4){
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.-exp(-4.*pow(xex[i]/100.-1./2.,2.))/4.);
				dhex[i] = (pow(4./GRAV,1./3.))*exp(-4.*pow(xex[i]/100.-1./2.,2.))*((xex[i]/100.)-(1./2.))/50.;
				qex[i] = 2.;
			}//end for
			
			h_l_bound = (pow(4./GRAV,1./3.))*(1.-exp(-4.*pow(-1./2.,2.))/4.);
			
			head(par, "MacDonald", "short channel with supercritical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: " << h_l_bound << " m"<< endl;
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s" << endl;
			cout << "# " << endl;
			
			cf = 0.03; //Manning
			cout << "# Manning's friction coefficient: " << cf << endl;
			cout << "##############################################################################"<<endl;
			

		/***********************************************************************
		 * sub- to super-critical (Manning) case
		 ***********************************************************************/
		}else{
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.-(xex[i]-50.)/200.+pow(xex[i]-50.,2.)/30000.);
				dhex[i] = (pow(4./GRAV,1./3.))*(-1./200.+(xex[i]-50.)/15000.);
				qex[i] = 2.;
			}//end for
			
			h_r_bound = (pow(4./GRAV,1./3.))*(1.-(50.)/200.+pow(50.,2.)/30000.);
			
			head(par, "MacDonald", "short channel with sub- to super-critical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = max("<<h_r_bound<<" - z, 0) m and q = 0 m^2/s" << endl; // note that z(L) = 0
			cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s" << endl;
			cout << "# " << endl;
			
			cf = 0.0328;
			cout << "# Manning's friction coefficient: " << cf << endl;
			cout << "##############################################################################"<<endl;
		}//end if

	/***********************************************************************
	 * L=5000 m channel case (only Manning, easy to get with Darcy-Weisbach)
	 * periodic solution (closed to furrows)
	 ***********************************************************************/
	}else if (par.get_choicedomain()==3){ 
		L = 5000.;
		R = 0.; //no rain
		dx_ex = L/NX_EX; //space step
		choice_fric = par.get_choice()-(par.get_choice()/2)*2; //we get 0 for the Manning law and 1 for the Darcy-Weisbach law

		for (int i=1 ; i<=NX_EX ; i++){
			xex[i] = (i-0.5)*dx_ex;
		}

		/***********************************************************************
		 * subcritical (Manning-periodic) case 
		 ***********************************************************************/
		for (int i=1 ; i<=NX_EX ; i++){
			hex[i] = 9./8.+sin(xex[i]*2.*asin(1.)/500.)/4.;
			dhex[i] = 4.*atan(1.)*cos(4.*atan(1.)*xex[i]/500.)/2000.;
			qex[i] = 2.;
		}//end for
		
		h_r_bound = 9./8.+sin(5000*2.*asin(1.)/500.)/4.;
		
		head(par, "MacDonald", "very long, undulating, periodic channel with subcritical flow");
		param(L, dx_ex);
		cout << "# Initial conditions: h = max("<<h_r_bound<<" - z, 0) m and q = 0 m^2/s" << endl; // note that z(L) = 0
		cout << "# Imposed discharge on the left boundary: "<< qex[1] <<" m^2/s"<< endl;
		cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
		cout << "# " << endl;
		
		cf = 0.03;
		cout << "# Manning's friction coefficient: " << cf << endl;
		cout << "##############################################################################"<<endl;

	/***********************************************************************
	 * L=1000 m channels cases (either Manning or Darcy-Weisbach)
	 * with rain 
	 * reference: Vo Thi Ngoc 2008
	 ***********************************************************************/
	}else{
		L = 1000.;
		R = 0.001; 
		dx_ex = L/NX_EX; //space step
		choice_fric = par.get_choice()-(par.get_choice()/2)*2; //we get 0 for the Manning law and 1 for the Darcy-Weisbach law
		
		for (int i=1 ; i<=NX_EX ; i++){
			xex[i] = (i-0.5)*dx_ex;
		}

		/***********************************************************************
		 * subcritical cases with rain 
		 ***********************************************************************/
		if((par.get_choice()==1)||(par.get_choice()==2)){
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(xex[i]/1000.-1./2.,2.))/2.);
				dhex[i] = -2*(pow(4./GRAV,1./3.))*(xex[i]/1000.-1./2.)*exp(-16.*pow(xex[i]/1000.-1./2.,2.))/125.;
				qex[i] = 1.+R*xex[i];
			}//end for
			
			h_l_bound = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(-1./2.,2.))/2.);
			h_r_bound = (pow(4./GRAV,1./3.))*(1.+exp(-16.*pow(1.-1./2.,2.))/2.);
			
			head(par, "MacDonald", "long channel with rain, with subcritical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed discharge on the left boundary for the first iteration: 1 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: "<< h_l_bound << " m" << endl;
			cout << "# Imposed water height on the right boundary: "<< h_r_bound << " m" << endl;
			cout << "# " << endl;
		
			if(choice_fric==0){ //Manning
				cf = 0.033;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.093;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}

		/***********************************************************************
		 * supercritical cases with rain
		 ***********************************************************************/
		}else{
			for (int i=1 ; i<=NX_EX ; i++){
				hex[i] = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(xex[i]/1000.-1./2.,2.))/5.);
				dhex[i] = (pow(4./GRAV,1./3.))*9.*exp(-36.*pow(xex[i]/1000.-1./2.,2.))*((xex[i]/1000.)-(1./2.))/625.;
				qex[i] = 2.5+R*xex[i];
			}//end for
			
			h_l_bound = (pow(4./GRAV,1./3.))*(1.-exp(-36.*pow(-1./2.,2.))/5.);
			
			head(par, "MacDonald", "long channel with rain, with supercritical flow");
			param(L, dx_ex);
			cout << "# Initial conditions: h = 0 m and q = 0 m^2/s" << endl;
			cout << "# Imposed discharge on the left boundary: 2.5 m^2/s" << endl;
			cout << "# Imposed water height on the left boundary: "<< h_l_bound << " m" << endl;
			cout << "# " << endl;
			
			if(choice_fric==0){ //Manning
				cf = 0.04;
				cout << "# Manning's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}else{ //Darcy-Weisbach
				cf = 0.065;
				cout << "# Darcy-Weisbach's friction coefficient: " << cf << endl;
				cout << "##############################################################################"<<endl;
			}
		}//end if
	} //end if
}


MacDonald_like::~MacDonald_like(){
	delete [] dhex;
}


void MacDonald_like::compute(){
	
	/**
	 * @details 
	 * Computes Mac Donald solutions, see \cite MacDonald96, \cite MacDonald97, \cite Delestre13 and \cite Vo08.
	 * @par Modifies 
	 * Solution#zex.
	 */

	/***********************************************************************
	 * zex is the topography associated to the chosen steady flow
	 ***********************************************************************/
	if(choice_fric==0){ //Manning
		varz = Delta_topo_Manning(qex[NX_EX],hex[NX_EX],dhex[NX_EX],R,cf);
		zex[NX_EX] = 0.5*dx_ex*varz;
		// zex =0 on the boundary ("NX_EX + 1/2")
		for (int i=NX_EX ; i>=1 ; i--){
			varz = Delta_topo_Manning(qex[i],hex[i],dhex[i],R,cf);
			zex[i-1] = dx_ex*varz+zex[i];
		}//end for
	}else{ //Darcy-Weisbach
		varz = Delta_topo_Darcy_Weisbach(qex[NX_EX],hex[NX_EX],dhex[NX_EX],R,cf);
		zex[NX_EX] = 0.5*dx_ex*varz;
		for (int i=NX_EX ; i>=1 ; i--){
			varz = Delta_topo_Darcy_Weisbach(qex[i],hex[i],dhex[i],R,cf);
			zex[i-1] = dx_ex*varz+zex[i];
		}//end for
	}
	
	for (int i =0; i<=NX_EX; i++){
		if (abs(hex[i]) > EPSILON) {
			uex[i] = qex[i] / hex[i];
		}
		else {
			uex[i] = 0.0;
		}
	}
	
	savefinalcritical(xex, hex, uex, zex);
}


SCALAR MacDonald_like::Delta_topo_Manning(SCALAR q, SCALAR h, SCALAR dh, SCALAR Rain, SCALAR c) const{
	
	/**
	 * @details
	 * @param[in] q discharge
	 * @param[in] h water height 
	 * @param[in] dh variation of the water height 
	 * @param[in] Rain rain quantity
	 * @param[in] c friction coefficient
	 * @return Value of \f$\displaystyle \left(1-\frac{q^2}{gh^3}\right) dh + 2Rain\frac{q}{gh^2}+\frac{c^2q^2}{h^{10/3}} \f$.
	 */	
	
	return (1.-pow(q,2.)/(GRAV*pow(h,3.)))*dh+2.*q*Rain/(GRAV*(pow(h,2.)))+(pow(c*q,2.))/(pow(h,10./3.));
}

SCALAR MacDonald_like::Delta_topo_Darcy_Weisbach(SCALAR q, SCALAR h, SCALAR dh, SCALAR Rain, SCALAR c) const{
	
	/**
	 * @details
	 * @param[in] q discharge
	 * @param[in] h water height 
	 * @param[in] dh variation of the water height
	 * @param[in] Rain rain quantity
	 * @param[in] c friction coefficient
	 * @return Value of \f$\displaystyle \left(1-\frac{q^2}{gh^3}\right) dh + 2Rain\frac{q}{gh^2}+c\frac{q^2}{8gh^3} \f$.
	 */	
	
	return (1.-pow(q,2.)/(GRAV*pow(h,3.)))*dh+2.*q*Rain/(GRAV*pow(h,2.))+c*pow(q,2.)/(8.*GRAV*pow(h,3.));
}


void MacDonald_like::param(SCALAR L, SCALAR dx_ex) const{
	
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

