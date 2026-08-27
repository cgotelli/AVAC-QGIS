/**
 * @file solute.cpp
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2024)
 * @version 1.04.02
 * @date 2024-10-31
 *
 * @brief Computes solute solutions
 * @details
 * Analytic solution: solute solution, see \cite BZ24.
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

#include "solute.hpp"

Solute::Solute(Parameters& par) :Solution(par) {

	/**
	 * @details
	 * Defines the physical parameters, the final time and prints the header with the solute configuration.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies
	 * Solution#dx_ex, Solution#L, Solution#T, Solution#xex, 
	 * to have the solute configuration.
	 */
	L = 1000.; // m 
	dx_ex = L / NX_EX;
	T = 500.; // s
	
	lambda = 0.0; // modified below if degradation
	u = 1.0; // m/s
	kd = 20; // m^3/kg
	C = 0.1; // kg/m^3
	Km1 = 0.002; // s^-1
	
	phiex = new SCALAR[NX_EX+1];//array for 
	if(NULL==phiex){
		fprintf(stderr, "\nProblem: allocation of phiex failed\n");
		exit(EXIT_FAILURE);
	}
	psiex = new SCALAR[NX_EX+1];//array for 
	if(NULL==psiex){
		fprintf(stderr, "\nProblem: allocation of psiex failed\n");
		exit(EXIT_FAILURE);
	}
	tabphi0 = new SCALAR[NX_EX+1];//array for 
	if(NULL==tabphi0){
		fprintf(stderr, "\nProblem: allocation of tabphi0 failed\n");
		exit(EXIT_FAILURE);
	}
	tabpsi0 = new SCALAR[NX_EX+1];//array for 
	if(NULL==tabpsi0){
		fprintf(stderr, "\nProblem: allocation of tabpsi0 failed\n");
		exit(EXIT_FAILURE);
	}

	for (int i = 0; i <= NX_EX; i++) {
		xex[i] = (i - 0.5) * dx_ex;
	}


		
	if (par.get_choice()==1 || par.get_choice()==3){ // initial concentrations
		mu= 70; // m
		sigma=20; // m
		for (int i = 0; i <= NX_EX; i++) {
			tabphi0[i] = phi0(xex[i], mu, sigma);
			tabpsi0[i] = psi0(xex[i]) ;
		}
		choice = "Initial concentration";
	}
	else {
		phix0 = 0.001; // kg/m^3
		psix0 = 0.0; // kg/m^3
		choice = "Boundary concentration";
	}
		
	if (par.get_choice() >2) { // degradation
		lambda = 0.003; //s^-1
		choice = choice + " with degradation";
	}
		
		
	head(par, "Solute solution", choice);
	param(L, phix0, psix0, lambda, mu, sigma, u, kd, C, Km1, dx_ex, T);
		
	
}


Solute::~Solute() {
	
	delete [] phiex;
	delete [] psiex;
	delete [] tabphi0;
	delete [] tabpsi0;

}


void Solute::compute() {

	/**
	 * @details
	 * Computes the chosen solute solution.
	 * @par Modifies
	 * Solute#phiex, Solute#psiex.
	 */


	for (int i = 0; i <= NX_EX; i++) { //looks at all the different cases
		if (T*u>xex[i]){ // H(T-x/u) = 1
			phiex[i] = phix0/(C*kd+1)*exp(-lambda*xex[i]/u)+ 1/(C*kd+1)*phi0(xex[i]-u*T, mu, sigma)*exp(-lambda*T)+ C*kd*phix0/(C*kd+1)*exp(-(Km1*C*kd+Km1+lambda)*xex[i]/u)+ C*kd/(C*kd+1)*phi0(xex[i]-u*T, mu, sigma)*exp(-(Km1*C*kd+Km1+lambda)*T);
			psiex[i] = C*kd*phix0/(C*kd+1)*exp(-lambda*xex[i]/u)-C*kd*phix0/(C*kd+1)*exp(-(Km1*C*kd+Km1+lambda)*xex[i]/u) +C*kd/(C*kd+1)*phi0(xex[i]-T*u, mu, sigma)*exp(-lambda*T)- C*kd/(C*kd+1)*phi0(xex[i]-T*u, mu, sigma)*exp(-(Km1*C*kd+Km1+lambda)*T);
		}
		else{ // H(T-x/u) = 0
			phiex[i] = 1/(C*kd+1)*phi0(xex[i]-u*T, mu, sigma)*exp(-lambda*T)+ C*kd/(C*kd+1)*phi0(xex[i]-u*T, mu, sigma)*exp(-(Km1*C*kd+Km1+lambda)*T);
			psiex[i] = C*kd/(C*kd+1)*phi0(xex[i]-T*u, mu, sigma)*exp(-lambda*T)- C*kd/(C*kd+1)*phi0(xex[i]-T*u, mu, sigma)*exp(-(Km1*C*kd+Km1+lambda)*T);
		}
	}//end for
	
	
	savefinalConcentrations(xex, phiex, psiex, tabphi0, tabpsi0);

}

SCALAR Solute::phi0(SCALAR x, SCALAR mu, SCALAR sigma)
{
	/**
	 * @details
	 * Computes the initial Gaussian disctribution of Solute#phi at the point x (in kg/m^3)
	 * @param[in] x coordinate of the point
	 * @param[in] mu postion of the maximum of the initial dissolved solute concentration
	 * @param[in] sigma standard deviation of the initial dissolved solute concentration
	 */
	return exp(-pow((x-mu),2)/(2*pow(sigma,2)))*0.001;
}

SCALAR Solute::psi0(SCALAR x)
{
	/**
	 * @details
	 * Computes the inital zero distribution of Solute#psi at the point x  (in kg/m^3)
	 * @param[in] x coordinate of the point (unused)
	 */
	(void) x;
	return 0.0;
}


void Solute::param(SCALAR L, SCALAR phix0, SCALAR psix0, SCALAR lambda, SCALAR mu, SCALAR sigma, SCALAR u, SCALAR kd, SCALAR C, SCALAR Km1, SCALAR dx_ex, SCALAR T) const {

	/**
	 * @details
	 * @param[in] L length of the domain
	 * @param[in] phix0 left boundary condition (input) on the dissolved solute concentration (in kg/m^3)
	 * @param[in] psix0 left boundary condition (input) on the adsorbed solute concentration (in kg/m^3)
	 * @param[in] lambda degradation constant
	 * @param[in] mu postion of the maximum of the initial dissolved solute concentration
	 * @param[in] sigma standard deviation of the initial dissolved solute concentration
	 * @param[in] u water velocity
	 * @param[in] kd equilibrium distribution coefficient
	 * @param[in] C sediment mass concentration in suspension
	 * @param[in] Km1 desorption rate
	 * @param[in] dx_ex space step
	 * @param[in] T final time
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters" << endl;
	cout << "# Space step: " << dx_ex << " meters" << endl;
	cout << "# Number of cells: " << NX_EX << endl;
	cout << "# Degradation constant: lambda=" << lambda << " second^(-1)"<<endl;
	cout << "# Water velocity =" << u << " meters/second" << endl;
	cout << "# Sediment mass concentration in suspension: C=" << C << " kilograms/meter^3"<< endl;
	cout << "# Equilibrium distribution coefficient: kd=" << kd << " meters^3/kilogram"<<endl;
	cout << "# Desorption rate: K-1=" << Km1 <<" second^(-1)"<< endl;
	if (choice.at(0) == 'B'){ // if boundary conditions
		cout << "# Left phi value: phix0=" << phix0 << " kilograms/meter^3"<< endl;
		cout << "# Left psi value: psix0=" << psix0 << " kilograms/meter^3"<< endl;
	}
	else{ // if initial condition
		cout << "# Initial dissolved solute concentration: "<<endl;
		cout << "#    phii(x) = 0.001 exp(-(x-" << mu << ")^2/(2*"<<sigma <<"^2)) kilograms/meter^3"<<endl;
	}
	cout << "# Time value: " << T << " seconds" << endl;
	cout << "##############################################################################" << endl;
}

