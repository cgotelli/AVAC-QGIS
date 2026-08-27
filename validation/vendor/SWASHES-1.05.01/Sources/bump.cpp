/**
 * @file bump.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Anne-Celine Boulanger <anne-celine.boulanger@inria.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2023)
 * @version 1.04.01
 * @date 2023-01-25
 *
 * @brief Computes bumps solutions
 * @details 
 * Analytic solution: with a bump, see \cite Delestre13, \cite Goutal97.
 *
 * @copyright License Cecill-V2 \n
 * <http://www.cecill.info/licences/Licence_CeCILL_V2-en.html>
 *
 * (c) CNRS - Universite d'Orleans - INRA - Universite Pierre et Marie Curie (France)
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

#include "bump.hpp"


Bump::Bump(Parameters & par):Solution(par){
		
	/** 
	 * @details 
	 * Defines the physical parameters and prints the header with the configuration.\n
	 * The solution is saved at the steady state. 
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#zex to have the bump configuration. 
	 */
	
	L = 25.;
	dx_ex = L/NX_EX;
	epsi = 10.0/(NX_EX);
	epsilon = 1.0/NX_EX;
	H_MAX = 3.;
	solu =0;

	a=0;
	b=0;
	c=0;
	d=0;

	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = MAX(0.0,0.2-0.05*pow(xex[i]-10, 2.0));//One bump centered in x=10 m
	}
	zmax = 0.2; // value of the maximum of zex (as a continuous function) 
	
		
	if(par.get_choice()==1){
		//subcritical flow
		
		solu = 1;
		q_in = 4.42; 
		h_out = 2.0;
		hex[NX_EX] = h_out;
		
		head(par, "Bump solution", "subcritical flow");
		param(L, dx_ex);
		cout << "# Initial condition: h+z = 2 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge (left-inflow) q_in = " << q_in << " m^2/s" << endl;
		cout << "# Imposed water height (right-outflow) h_out = " << h_out << " m" << endl;
		cout << "##############################################################################" << endl;
	}
	else if (par.get_choice()==2){ 
		//transcritical without shock (subcritical-supercritical)
		
		solu = 2;
		q_in = 1.53; 
		hmiddle = pow(pow(q_in,2.0)/GRAV,1.0/3.0); //h at the top of the bump which is the critical height
		hex[2*NX_EX/5+1] = hmiddle; // temporary, for the Cardano method
		
		head(par, "Bump solution", "transcritical without shock (subcritical-supercritical)");
		param(L, dx_ex);
		cout << "# Initial condition: h+z = 0.66 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge (left-inflow) q_in = " << q_in << " m^2/s" << endl;
		cout << "# Imposed water height (right-outflow) (while subcritical) h_out = 0.66 m" << endl;
		cout << "##############################################################################"<<endl;
	}
	else if (par.get_choice()==3){ 
		//transcritical with shock (subcritical-supercritical-subcritical)
		
		solu = 3;
		q_in = 0.18;
		h_out=0.33; 
		hmiddle = pow(pow(q_in, 2.0)/GRAV,1.0/3.0); //h at the top of the bump which is the critical height
		hex[NX_EX] = h_out;
		
		head(par, "Bump solution", "transcritical with shock (subcritical-supercritical-subcritical)");
		param(L, dx_ex);
		cout << "# Initial condition: h+z = 0.33 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge (left-inflow) q_in = " << q_in << " m^2/s" << endl;
		cout << "# Imposed water height (right-outflow) h_out = " << h_out << " m" << endl;
		cout << "##############################################################################"<<endl;
	}
	else if (par.get_choice()==4){ 
		//lake at rest with an immersed bump
		
		solu = 4;
		q_in = 0.; //q_in
		h_out=0.5; //h_out
		
		head(par, "Bump solution", "lake at rest with an immersed bump");
		param(L, dx_ex);
		cout << "# Initial condition: h+z = 0.5 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge (left-inflow) q_in = " << q_in << " m^2/s" << endl;
		cout << "# Imposed water height (right-outflow) h_out = " << h_out << " m" << endl;
		cout << "##############################################################################"<<endl;
	}
	else{ // par.get_choice() == 5		
		//lake at rest with an emerged bump
		
		solu = 5;
		q_in = 0.; //q_in
		h_out=0.1; //h_out
		
		head(par, "Bump solution", "lake at rest with an emerged bump");
		param(L, dx_ex);
		cout << "# Initial condition: h+z = 0.1 m and q = 0 m^2/s" << endl;
		cout << "# Imposed discharge (left-inflow) q_in = " << q_in << " m^2/s" << endl;
		cout << "# Imposed water height (right-outflow) h_out = " << h_out << " m" << endl;
		cout << "##############################################################################"<<endl;

	} //end if
	 
	for (int i=0 ; i<=NX_EX ; i++){
		qex[i] = q_in;
	}
}

Bump::~Bump(){
}

void Bump::compute(){
					 
	/**
	 * @details 
	 * Computes the chosen bump solution, see \cite Delestre13 and \cite Goutal97.
	 * @par Modifies 
	 * Solution#hex.
	 */
	

	if(solu==1){ 
		//subcritical flow
		
		for(int i=NX_EX-1; i>=0; i--){
			abcd(q_in, h_out, zex[i],zex[NX_EX],a,b,c,d);
			hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,hex[i+1]);
		}

	}else if (solu==2){ 
		//transcritical without shock (subcritical-supercritical)

		for(int i=2*NX_EX/5; i>=0; i--){//Partie fluviale (before bump)
			abcd(q_in,hmiddle, zex[i],zmax,a,b,c,d);
			hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,hex[i+1]*(1+epsilon));
		}
		
		// As the bump is symmetric and the values do not coincide with the max of the topo, 
		// we make the solution deacrease. 
		
		abcd(q_in, hmiddle, zex[2*NX_EX/5+1],zmax,a,b,c,d);
		hex[2*NX_EX/5+1] = height(p(a,b,c),q(a,b,c,d),a,b,hmiddle);

		for(int i=2*NX_EX/5+2; i<NX_EX+1;i++){//Partie torrentielle (after bump)
			abcd(q_in, hmiddle, zex[i],zmax,a,b,c,d);
			hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,hex[i-1]*(1-epsilon));
		}

	}else if (solu==3){ 
		//transcritical with shock (subcritical-supercritical-subcritical)
		
		/* Research of the limit x */
		SCALAR test=100.0;
		SCALAR hminus=0.;
		int abslim = 2*NX_EX/5;							 // PB depending on NX_EX!!
		
		while(test>epsi && abslim < NX_EX){
			abcd(q_in,h_out,zex[abslim],zex[NX_EX],a,b,c,d);
			SCALAR hplus = height(p(a,b,c),q(a,b,c,d),a,b,h_out);
			abcd(q_in,hmiddle,zex[abslim],zmax,a,b,c,d);
			hminus = height(p(a,b,c),q(a,b,c,d),a,b,hmiddle);
			test = RHJump(hplus, hminus, q_in);
			abslim++;
			}
			
		hex[abslim] = hminus;
		
		/* Computation of the height */
		
		for(int i=abslim-1; i>=0; i--){// fluvial part (before bump)
			abcd(q_in,hmiddle,zex[i],zmax,a,b,c,d);
			hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,hex[i+1]+epsilon);
		}

		for(int i=NX_EX-1; i>abslim; i--){// torrential part (after bump)
			abcd(q_in,h_out,zex[i],zex[NX_EX],a,b,c,d);
			hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,hex[i+1]);
		}
		
	}else{
		// lakes at rest
		for (int i=1 ; i<=NX_EX ; i++){
			hex[i] = max(h_out-zex[i],0.);
			uex[i] = 0.;
		}
	}//end if
	
	if (solu <=3){
		for (int i =0; i<=NX_EX; i++){
			if (abs(hex[i]) > EPSILON) {
				uex[i] = qex[i] / hex[i];
			}
			else {
				uex[i] = 0.0;
			}
		}
	}
	
	savefinalcritical(xex, hex, uex, zex);
}


SCALAR Bump::p(SCALAR a, SCALAR b, SCALAR c) const{
	
	/**
	 * @details
	 * @param[in] a coefficient of the 3rd order polynomia
	 * @param[in] b coefficient of the 3rd order polynomia
	 * @param[in] c coefficient of the 3rd order polynomia
	 * @return Value of \f$ \displaystyle -\frac{b^2}{3a^2} + \frac{c}{a} \f$.
	 */
	
	return (-b*b/(3.0*a*a) + c/a);
}

SCALAR Bump::q(SCALAR a, SCALAR b, SCALAR c, SCALAR d) const{
	
	
	/**
	 * @details
	 * @param[in] a coefficient of the 3rd order polynomia
	 * @param[in] b coefficient of the 3rd order polynomia
	 * @param[in] c coefficient of the 3rd order polynomia
	 * @param[in] d coefficient of the 3rd order polynomia
	 * @return Value of \f$ \displaystyle \frac{b}{27a}\left(\frac{2b^2}{a^2} -9 \frac{c}{a}\right) \f$.
	 */
	
	return (b/(27.0*a)*(2.0*b*b/(a*a)-9.0*c/a) + d/a);
}


SCALAR Bump::determinant(SCALAR p, SCALAR q) const{
	
	/** 
	 * @details
	 * Determinant in the Cardano method/related to number of roots.
	 * @param[in] p computed by Bump::p
	 * @param[in] q computed by Bump::q
	 * @return Value of \f$ q^2 + \frac{4}{27} p^3 \f$.
	 */
	
	return (pow(q, 2.0)+4.0/27.0*pow(p,3.0)) ;
}


SCALAR Bump::height(SCALAR p, SCALAR q, SCALAR a, SCALAR b, SCALAR hnear) const{
	
	/**
	 * @details
	 * @param[in] p computed by Bump::p
	 * @param[in] q computed by Bump::q
	 * @param[in] a coefficient of the 3rd order polynomia
	 * @param[in] b coefficient of the 3rd order polynomia
	 * @param[in] hnear height of the previous or following cell (depending on the height computation direction)
	 * @warning Error: no positive height.
	 * @warning Error: Probably irregular solution.
	 * @return h, the water height. 
	 */	
	
	SCALAR det = determinant(p,q);
	SCALAR h=0;
	SCALAR l1,l2,l3;

	if(det > 0){// One real solution
		SCALAR h1,h2;
		h1 = (-q + sqrt(det))/2.0;
		h2 = (-q - sqrt(det))/2.0;
		h = h1/abs(h1)*pow(abs(h1),1.0/3.0)+ h2/abs(h2)*pow(abs(h2),1.0/3.0)-b/(3.0*a); 
	}else{
		if(abs(det)< EPSILON ){// Two real solutions
			l1 = 3.0*q/p;
			l2 = -3.0*q/(2.0*p);
				if(l1>0){
					h = l1-b/(3.0*a);
				}else{
					h = l2-b/(3.0*a);
				}
		}else{// Three real solution, using complex
			complex<double> u3(-q/2.0,sqrt(abs(det))/2);
			complex<double> u = pow(u3,1.0/3.0);
			complex<double> j(-1.0/2.0,sqrt(3.0)/2.0);
			l1 = 2.0*real(u)-b/(3.0*a);
			l2 = 2.0*real(j*u)-b/(3.0*a);
			l3 = 2.0*real(j*j*u)-b/(3.0*a);
			if(l1<=0 && l2<=0 && l3<=0){
				cerr << "Error: no positive height"<<endl;
			}else if(l1>=H_MAX && l2>=H_MAX && l3>=H_MAX){
				cerr << "Error: Probably irregular solution"<<endl;
			}else{ 
				double m = min(min(abs(l1-hnear),abs(l2-hnear)),abs(l3-hnear));
				if (abs(m - abs(l1-hnear))<EPSILON){
					h = l1;
				}else if (abs(m - abs(l2-hnear))<EPSILON){
					h = l2;
				}else{
					h = l3;
				}
			}
		}
	}

	return h;
}


void Bump::abcd(SCALAR q_in, SCALAR h_out, SCALAR zbx, SCALAR zbfin, SCALAR &a, SCALAR &b, SCALAR &c, SCALAR &d){
	
	/**
	 * @details 
	 * Enters the coefficients of the 3rd order polynomia we want to solve: \f$ ah^3+bh^2+ch+d \f$.
	 * @param[in] q_in inflow discharge
	 * @param[in] h_out water height at the outflow
	 * @param[in] zbx bottom topography of the current cell
	 * @param[in] zbfin bottom topography at the outflow
	 * @param[out] a coefficient of the 3rd order polynomia
	 * @param[out] b coefficient of the 3rd order polynomia
	 * @param[out] c coefficient of the 3rd order polynomia
	 * @param[out] d coefficient of the 3rd order polynomia	
	 */
	
	a=1.0;
	c = 0.0;
	b = -(q_in*q_in/(2.0*GRAV*h_out*h_out) + h_out - (zbx - zbfin));
	d = q_in*q_in/(2*GRAV);
}


SCALAR Bump::RHJump(SCALAR hplus, SCALAR hminus, SCALAR q) const{
	
	/**
	 * @details 
	 * @param[in] hplus water height on the right side
	 * @param[in] hminus water height on the left side
	 * @param[in] q discharge
	 * @return Value of \f$ \left| q^2\left(\frac{1}{hplus} - \frac{1}{hminus}\right)+ \frac{g}{2} \left(hplus^2-hminus^2\right) \right| \f$.
	 */
	
	return abs((q*q*(1.0/(hplus) - 1.0/(hminus)) + GRAV_DEM*((hplus - hminus)*(hplus+hminus)))); // (x-y)(x+y) to avoid errors. 
}


void Bump::param(SCALAR L, SCALAR dx_ex) const{
	
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
	cout << "# Topography: z(x) = max(0.0 , 0.2-0.05*(x-10)^2)" << endl;
	cout << "# Solution at the steady state" << endl;
	cout << "# "<< endl;
}	

