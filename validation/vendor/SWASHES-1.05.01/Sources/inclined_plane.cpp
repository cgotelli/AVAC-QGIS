/**
 * @file inclined_plane.cpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Anne-Celine Boulanger <anne-celine.boulanger@inria.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2014-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes the solution over an inclined plane
 * @details 
 * Analytic solution: \cite Delestre12.
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

#include "inclined_plane.hpp"


Inclined_plane::Inclined_plane(Parameters & par):Solution(par){
		
	/** 
	 * @details 
	 * Defines the physical parameters and prints the header with the configuration.\n
	 * The solution is saved at the steady state. 
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies 
	 * Solution#dx_ex, Solution#L, Solution#xex, Solution#zex to have the inclined plane configuration.
	 */
	
	L = 10.;
	dx_ex = L/NX_EX;
	alpha = -0.15;
	beta = 2;
	q0 = 0.01;
	h0 = 0.02;

	a=0;
	b=0;
	c=0;
	d=0;
	
	H_MAX = 3.;

	for (int i=0 ; i<=NX_EX ; i++){
		xex[i] = (i-0.5)*dx_ex;
		zex[i] = alpha*xex[i]+beta; //inclined plane
		qex[i] = q0;
	}
		
	//if(par.get_choice()==1){
	//supercritical flow
		
	head(par, "Solution over an inclined plane", "supercritical flow");
	param(L, dx_ex, alpha, beta, h0, q0);
	
	//}
}

Inclined_plane::~Inclined_plane(){
}

void Inclined_plane::compute(){
					 
	/**
	 * @details 
	 * Computes the solution on an inclined plane, see \cite Delestre12.
	 * @par Modifies 
	 * Solution#hex.
	 */
	

	//if(par.get_choice()==1){
	//supercritical flow
		
	for (int i=0 ; i<=NX_EX ; i++){
		/* hex is solution of hex^3 + hex^2(ax-q0^2/(2gh0^2)-h0)+q0^2/(2g)=0 */
		
		abcd(q0,h0,alpha, xex[i],a,b,c,d);
		hex[i] = height(p(a,b,c),q(a,b,c,d),a,b,h0);
		uex[i] = qex[i]/hex[i];

	}
	
	//}
	
	savefinalcritical(xex, hex, uex, zex);
}


SCALAR Inclined_plane::p(SCALAR a, SCALAR b, SCALAR c) const{
	
	/**
	 * @details
	 * @param[in] a coefficient of the 3rd order polynomia
	 * @param[in] b coefficient of the 3rd order polynomia
	 * @param[in] c coefficient of the 3rd order polynomia
	 * @return Value of \f$ \displaystyle -\frac{b^2}{3a^2} + \frac{c}{a} \f$.
	 */
	
	return (-b*b/(3.0*a*a) + c/a);
}

SCALAR Inclined_plane::q(SCALAR a, SCALAR b, SCALAR c, SCALAR d) const{
	
	
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


SCALAR Inclined_plane::determinant(SCALAR p, SCALAR q) const{
	
	/**
	 * @details
	 * Determinant in the Cardano method/related to number of roots.
	 * @param[in] p computed by Inclined_plane::p
	 * @param[in] q computed by Inclined_plane::q
	 * @return Value of \f$ q^2 + \frac{4}{27} p^3 \f$.
	 */
	
	return (pow(q, 2.0)+4.0/27.0*pow(p,3.0)) ;
}


SCALAR Inclined_plane::height(SCALAR p, SCALAR q, SCALAR a, SCALAR b, SCALAR hnear) const{
	
	/**
	 * @details
	 * @param[in] p computed by Inclined_plane::p
	 * @param[in] q computed by Inclined_plane::q
	 * @param[in] a coefficient of the 3rd order polynomia
	 * @param[in] b coefficient of the 3rd order polynomia
	 * @param[in] hnear height of the previous or following cell (depending on the height computation direction)
	 * @warning Error: no positive height.
	 * @warning Error: Probably irregular solution.
	 * @return h, the water height.
	 */
	
	SCALAR de = determinant(p,q);
	SCALAR h=0;
	SCALAR l1,l2,l3;
	
	if(de > 0){// One real solution
		SCALAR h1,h2;
		h1 = (-q + sqrt(de))/2.0;
		h2 = (-q - sqrt(de))/2.0;
		h = h1/abs(h1)*pow(abs(h1),1.0/3.0)+ h2/abs(h2)*pow(abs(h2),1.0/3.0)-b/(3.0*a);
	}else{
		if(abs(de) < EPSILON){// Two real solutions
			l1 = 3.0*q/p;
			l2 = -3.0*q/(2.0*p);
			if(l1>0){
				h = l1-b/(3.0*a);
			}else{
				h = l2-b/(3.0*a);
			}
		}else{// Three real solution, using complex
			complex<double> u3(-q/2.0,sqrt(abs(de))/2);
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


void Inclined_plane::abcd(SCALAR q_in, SCALAR h_in, SCALAR alpha, SCALAR x, SCALAR &a, SCALAR &b, SCALAR &c, SCALAR &d){
	
	/**
	 * @details
	 * Enters the coefficients of the 3rd order polynomia we want to solve:
	 * \f$ ah^3+b h^2+c h+d \f$.
	 * @param[in] q_in inflow discharge
	 * @param[in] h_in water height at the inflow
	 * @param[in] alpha the slope
	 * @param[in] x the position
	 * @param[out] a coefficient of the 3rd order polynomia
	 * @param[out] b coefficient of the 3rd order polynomia
	 * @param[out] c coefficient of the 3rd order polynomia
	 * @param[out] d coefficient of the 3rd order polynomia
	 */
	
	a = 1.0;
	c = 0.0;
	b = -(q_in*q_in/(2.0*GRAV*h_in*h_in) + h_in - alpha*x);
	d = q_in*q_in/(2*GRAV);
}





void Inclined_plane::param(SCALAR L, SCALAR dx_ex, SCALAR alpha, SCALAR beta, SCALAR h0, SCALAR q0) const{
	
	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] dx_ex space step 
	 * @param[in] alpha the slope of the plane
	 * @param[in] beta the value of the topography for x=0
	 * @param[in] h0 the left (imposed) water height
	 * @param[in] q0 the left (imposed) water discharge
	 */
	
	cout << "# PARAMETERS OF THE SOLUTION"<< endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters"<<endl;
	cout << "# Space step: "<< dx_ex << " meters"<< endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Topography: z(x) = " << alpha << " x + " << beta << endl;
	cout << "# Solution at the steady state" << endl;
	cout << "# "<< endl;
	cout << "# Imposed discharge (left-inflow) q_in = " << q0 << " m^2/s" << endl;
	cout << "# Imposed water height (left-inflow) h_in = " << h0 << " m" << endl;
	cout << "##############################################################################" << endl;
}










