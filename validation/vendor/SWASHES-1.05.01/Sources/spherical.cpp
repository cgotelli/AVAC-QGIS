/**
 * @file spherical.cpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.00
 * @date  2022-07-18

 *
 * @brief Computes Static solutions in spherical geometry
 * @details
 * Analytic solution: different static solutions in spherical geometry, see \cite Williamson92.
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

#include "spherical.hpp"

Spherical::Spherical(Parameters& par) :Solution(par) {

	/**
	 * @details
	 * Defines the physical parameters.
	 * @param[in] par contains all the values from the parameters
	 * @warning Problem: allocation of lambdaex failed
	 * @warning Problem: allocation of thetaex failed
	 * @par Modifies
	 * Solution#dx_ex, Solution#dy_ex, Spherical#rhoex, Spherical#uex2D, Spherical#vex2D, Spherical#lambdaex, 
	 * Spherical#thetaex, Spherical#alpha, Spherical#omega, Spherical#radius,
	 * to have a Spherical configuration and the domain paramters.
	 */


	//To correctly represent the values graphically the longitudinal angle (lambda) must loop from 0 to 2PI.
	//Since the points where lambda=2PI don't add new informations compared to the ones where lambda=0,
	//we decided to add those points without counting them in the number of points demanded by the user.
	//So overall there will be (NX_EX+1)*NY_EX calculations. 
	//But only NX_EX*(NY_EX-2)+2 points in the actual mesh (considering the poles).			

	lambdaex = new SCALAR[NX_EX + 1]; //lambdaex is the longitudinal angle
	if (NULL == lambdaex) {
		fprintf(stderr, "\nProblem: allocation of lambdaex failed\n");
		exit(EXIT_FAILURE);
	}

	thetaex = new SCALAR[NY_EX]; //thetaex is the latitudinal angle
	if (NULL == thetaex) {
		fprintf(stderr, "\nProblem: allocation of thetaex failed\n");
		exit(EXIT_FAILURE);
	}

	rhoex.resize(NX_EX + 1); // i : 0->NX_EX
	uex2D.resize(NX_EX + 1); // i : 0->NX_EX
	vex2D.resize(NX_EX + 1); // i : 0->NX_EX
	hex2D.resize(NX_EX + 1); // i : 0->NX_EX

	for (int i = 0; i < NX_EX + 1; i++) {

		rhoex[i].resize(NY_EX); // j : 0->NY_EX - 1
		vex2D[i].resize(NY_EX); // j : 0->NY_EX - 1
		uex2D[i].resize(NY_EX); // j : 0->NY_EX - 1
		hex2D[i].resize(NY_EX); // j : 0->NY_EX - 1


		for (int j = 0; j < NY_EX; j++) {
			//The topography equals 0 for all the domains of this class
			rhoex[i][j] = 0.;
		}
	}


	if (par.get_choicedomain() == 1) {
		alpha = 0.; //alpha is the angle between the spherical pole and the earth axis
		if (par.get_choice() == 1) { //for now there's only one choice in this domain
			solu = 1;
		}
	}
	else { //choicedomain = 2
		alpha = 0.406; //alpha is the angle between the spherical pole and the earth axis
		if (par.get_choice() == 1) { //for now there's only one choice in this domain
			solu = 2;
		}
	}
	dx_ex = 2*PI / (NX_EX); //In spherical geometry, dx and dy correspond to incremants in the angle lambda and theta
	dy_ex = PI / (NY_EX-1);

	h0 = 3000.;
	radius = 6.37122 * pow(10, 6);
	u0 = 2*PI*radius/(12*24*3600);
	omega = 7.292*pow(10,-5); //Omega correponds to the pulsation of earth rotation 

	lambdaex[0] = 0.;
	thetaex[0] = -PI/2;
	for (int i = 1; i < NX_EX + 1; i++) {
		lambdaex[i] = lambdaex[i-1]+dx_ex; //lambdaex is the longitudinal angle
	}

	for (int j = 1; j < NY_EX; j++) {
		thetaex[j] = thetaex[j - 1] + dy_ex; //thetaex is the latitudinal angle
	}

	for (int i = 0; i < NX_EX + 1; i++) {
		for (int j = 0; j < NY_EX; j++) {
			uex2D[i][j] = u0*(cos(thetaex[j]) * cos(alpha) + cos(lambdaex[i]) * sin(thetaex[j]) * sin(alpha));
			vex2D[i][j] = -u0*sin(lambdaex[i])*sin(alpha);
		}
	}


	head(par, "SPHERICAL", "global steady state");
	param(radius, alpha, omega, dx_ex, dy_ex);
	cout << "##############################################################################" << endl;
}

Spherical::~Spherical() {
	for (int i = 0; i < NX_EX + 1; i++) {
		uex2D[i].clear();
		vex2D[i].clear();
		rhoex[i].clear();
		hex2D[i].clear();
	}
	uex2D.clear();
	vex2D.clear();
	rhoex.clear();
	hex2D.clear();
	delete[] thetaex;
	delete[] lambdaex;
}


void Spherical::compute() {

	/**
	 * @details
	 * Computes the chosen Spherical solution.
	 * @par Modifies
	 * Spherical#hex2D.
	 */

	if (solu == 1) {

		for (int i = 0; i < NX_EX + 1; i++) {
			for (int j = 0; j < NY_EX; j++) {
				hex2D[i][j] = h0 - (radius * omega * u0 + pow(u0, 2) / 2) * pow(-cos(lambdaex[i]) * cos(thetaex[j]) * sin(alpha) + cos(alpha) * sin(thetaex[j]), 2) / GRAV;			
			}
		}
	}
	else { //solu=2

		for (int i = 0; i < NX_EX + 1; i++) {
			for (int j = 0; j < NY_EX; j++) {
				hex2D[i][j] = h0 - (radius * omega * u0 + pow(u0, 2) / 2) * pow(-cos(lambdaex[i]) * cos(thetaex[j]) * sin(alpha) + cos(alpha) * sin(thetaex[j]), 2) / GRAV;
			}
		}
	}
	savefinalSpherical(lambdaex, thetaex, hex2D, uex2D, vex2D, rhoex);
}


void Spherical::param(SCALAR radius, SCALAR alpha, SCALAR omega, SCALAR dx_ex, SCALAR dy_ex) const {

	/**
	 * @details
	 * @param[in] radius radius of the sphere
	 * @param[in] omega pulsation of the rotation of the sphere
	 * @param[in] alpha angle between the sphere's rotation axis and the polar axis
	 * @param[in] dx_ex angle step in lambda
	 * @param[in] dy_ex angle step in theta
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Radius of the sphere: " << radius << " meters" << endl;
	cout << "# Pulsation of the rotation of the sphere: " << omega << " s^-1" << endl;
	cout << "# Angle between the sphere's rotation axis and the polar axis: " << alpha << " radiants" << endl;
	cout << "# Longitudinale angle step: " << dx_ex << " radiants" << endl;
	cout << "# Latitudinale angle step: " << dy_ex << " radiants" << endl;
	cout << "# Number of cells in lambda: " << NX_EX + 1 << endl;
	cout << "# Number of cells in theta: " << NY_EX << endl;
	cout << "# Topography: z(x) = 0" << endl;

}
