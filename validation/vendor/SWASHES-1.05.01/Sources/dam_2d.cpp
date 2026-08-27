/**
 * @file dam_2d.cpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.00
 * @date 2022-07-13
 *
 * @brief Computes Static dam solutions in 2D
 * @details
 * Analytic solution: with a dam in 2d, see \cite Delestre13.
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

#include "dam_2d.hpp"

Dam_2D::Dam_2D(Parameters& par) :Solution(par) {

	/**
	 * @details
	 * Defines the physical parameters.
	 * @param[in] par contains all the values from the parameters
	 * @par Modifies
	 * Solution#dx_ex, Solution#L, Solution#l, Solution#xex, Solution#yex, Dam_2D#zex2D, Dam_2D#uex2D, Dam_2D#vex2D
	 * to have Dam_2D configuration.
	 */

	zex2D.resize(NX_EX + 1); // i : 0->NX_EX
	uex2D.resize(NX_EX + 1); // i : 0->NX_EX
	vex2D.resize(NX_EX + 1); // i : 0->NX_EX
	hex2D.resize(NX_EX + 1); // i : 0->NX_EX

	for (int i = 0; i <= NX_EX; i++) {

		zex2D[i].resize(NY_EX + 1); // j : 0->NY_EX
		uex2D[i].resize(NY_EX + 1); // j : 0->NY_EX
		vex2D[i].resize(NY_EX + 1); // j : 0->NY_EX
		hex2D[i].resize(NY_EX + 1); // j : 0->NY_EX


		for (int j = 0; j <= NY_EX; j++) {
			//The speed equals 0 for all the domains of this class
			uex2D[i][j] = 0;
			vex2D[i][j] = 0;
		}
	}
	if (par.get_choicedomain() == 1) {

		L = 25.;
		l = 10.;
		dx_ex = L / NX_EX;
		dy_ex = l / NY_EX;

		dam_d = 10.;
		dam_h = 0.5;
		dam_w = 1.;

		//parameter that garanties the width of the dam as a whole is 4*dam_w:
		float alpha = (exp(-pow(dam_w / 2., 2.)) - exp(-pow(dam_w * 2., 2.))) / dam_h; 

		//parameter of the topography that garanties the width of the flat surface of the dam is dam_w meter:
		float beta = exp(-pow(dam_w / 2, 2.)) / alpha - dam_h; 

		for (int j = 0; j <= NY_EX; j++) {
			yex[j] = (j - 0.5) * dy_ex; //We look at values taken in the center of each cell of size dx*dy
		}

		for (int i = 0; i <= NX_EX; i++) {
			xex[i] = (i - 0.5) * dx_ex;
			for (int j = 0; j <= NY_EX; j++) {
				zex2D[i][j] = MIN(dam_h, MAX(0., exp(-pow(xex[i] - dam_d - pow(yex[j] - 5., 2.) / 25., 2.)) / alpha - beta));
			}
		}

		if (par.get_choice() == 1) { //for now there's only one choice in this domain
			solu = 1;
			head(par, "DAM_2D", "Curved DAM");
			param(L, l, dam_d, dam_h, dam_w, dx_ex, dy_ex);
			cout << "##############################################################################" << endl;

		}
	}
	else { //choicedomain()==2

		L = 10.;
		l = 10.;
		dx_ex = L / NX_EX;
		dy_ex = l / NY_EX;

		dam_d = 2.5;
		dam_h = 1.;
		dam_w = 1.;

		float alpha_ring = (exp(-pow(dam_w / 2., 2.)) - exp(-pow(dam_w * 2., 2.))) / dam_h; //parameter that garanties the width of the dam is 4*dam_w
		float beta_ring = exp(-pow(dam_w / 2, 2.)) / alpha_ring - dam_h; //parameter of the topography that garanties the width of the flat surface of the dam is dam_w meter

		float alpha_cross = (exp(-pow(dam_w / 2., 2.)) - exp(-pow(dam_w * 2., 2.))) / (dam_h/2); //same parameter than the ring but the cross is 2 times lower
		float beta_cross = exp(-pow(dam_w / 2, 2.)) / alpha_cross - (dam_h/2);

		for (int j = 0; j <= NY_EX; j++) {
			yex[j] = (j - 0.5) * dy_ex; //We look at values taken in the center of each cell of size dx*dy
		}

		for (int i = 0; i <= NX_EX; i++) {
			xex[i] = (i - 0.5) * dx_ex;
			for (int j = 0; j <= NY_EX; j++) {
				SCALAR croix = cross(xex[i], yex[j], alpha_cross, beta_cross);
				zex2D[i][j] = MAX(ring(xex[i], yex[j], alpha_ring, beta_ring), croix );
			}
		}
		if (par.get_choice() == 1) { //for now there's only one choice in this domain
			solu = 2;
			head(par, "DAM_2D", "Symmetrical cross Dam");
			param(L, l, dam_d, dam_h, dam_w, dx_ex, dy_ex);
			cout << "##############################################################################" << endl;
		}
	}
}

Dam_2D::~Dam_2D() {
	for (int i = 0; i <= NX_EX; i++) {
		zex2D[i].clear();
		uex2D[i].clear();
		vex2D[i].clear();
		hex2D[i].clear();
	}
	zex2D.clear();
	uex2D.clear();
	vex2D.clear();
	hex2D.clear();
}


void Dam_2D::compute() {

	/**
	 * @details
	 * Computes the chosen Dam_2D solution.
	 * @par Modifies
	 * Dam_2D#hex2D.
	 */

	if (solu == 1) {
		
		for (int j = 0; j <= NY_EX; j++) {
			for (int i = 0; i <= NX_EX; i++) {
				if (xex[i] - dam_d - pow(yex[j] - l/2, 2.) / 25.<0.) {//
					hex2D[i][j] = dam_h- zex2D[i][j];
				}
				else {
					hex2D[i][j] = 0;
				}
			}
		}
	}
	else{ //solu == 2
		for (int j = 0; j <= NY_EX; j++) {
			for (int i = 0; i <= NX_EX; i++) {
				if (norm(xex[i] - L / 2, yex[j] - l / 2) < dam_d) {
					hex2D[i][j] = dam_h - zex2D[i][j];
				}
				else{
					hex2D[i][j] = 0;
				}
			}
		}
	}

	savefinal2D(xex, yex, hex2D, uex2D, vex2D, zex2D);

}


void Dam_2D::param(SCALAR L, SCALAR l, SCALAR dam_d, SCALAR dam_h, SCALAR dam_w, SCALAR dx_ex, SCALAR dy_ex) const {

	/**
	 * @details
	 * @param[in] L length of the domain in x
	 * @param[in] l length of the domain in y
	 * @param[in] dam_h height of the dam
	 * @param[in] dam_d distance of the center of the dam to the upstream border
	 * @param[in] dam_w width of the flat section at the top of the dam
	 * @param[in] dx_ex space step in x
	 * @param[in] dy_ex space step in y
	 */

	cout << "# PARAMETERS OF THE SOLUTION" << endl;
	cout << "# " << endl;
	cout << "# Length of the domain: " << L << " meters" << endl;
	cout << "# Width of the domain: " << l << " meters" << endl;
	cout << "# Space step in x: " << dx_ex << " meters" << endl;
	cout << "# Space step in y: " << dy_ex << " meters" << endl;
	cout << "# Number of cells in x: " << NX_EX << endl;
	cout << "# Number of cells in y: " << NY_EX << endl;
	cout << "# Height of the dam: " << dam_h << " meters" << endl;
	cout << "# Distance between the upstream limit and the center of the dam: " << dam_d << " meters" << endl;
	cout << "# width of the dam: " << dam_w << " meters" << endl;
	cout << "# Topography of the form: z(x,y) = min(dam_h, max(0, exp( ( g(x,y) ^2 )/alpha - beta));" << endl;

}

SCALAR Dam_2D::norm(SCALAR x, SCALAR y)
{
	/**
	 * @details
	 * computes the norm of the point (x,y)
	 * @param[in] x first coordinate of the point
	 * @param[in] y second coordinate of the point
	 */
	return sqrt(pow(x, 2) + pow(y, 2));
}

SCALAR Dam_2D::ring(SCALAR x, SCALAR y, SCALAR alpha, SCALAR beta) {
	/**
	 * @details
	 * computes the height of the center ring at the point (x,y) with a topography of the form 
	 * z(x,y) = min(dam_h, max(0, exp( ( g(x,y) ^2 )/alpha - beta))
	 * @param[in] x first coordinate of the point
	 * @param[in] y second coordinate of the point
	 * @param[in] alpha parameter of the dam shape
	 * @param[in] beta parameter of the dam shape
	 */
	return (MIN(dam_h, MAX(0., exp(-pow(norm(x-L/2,y-l/2) - dam_d, 2.)) / alpha - beta)));
}

SCALAR Dam_2D::cross(SCALAR x, SCALAR y, SCALAR alpha, SCALAR beta) {
	/**
	 * @details
	 * computes the height of the cross shaped dam at the point (x,y) with a topography of the form 
	 * z(x,y) = min(dam_h, max(0, exp( ( g(x,y) ^2 )/alpha - beta))
	 * @param[in] x first coordinate of the point
	 * @param[in] y second coordinate of the point
	 * @param[in] alpha parameter of the dam shape
	 * @param[in] beta parameter of the dam shape
	 */
	SCALAR x_center = x - L / 2, y_center = y - l / 2;
	if (norm(x_center,y_center) < dam_d) {
		return 0;
	}
	else {
		SCALAR proj_orth = 0.0;
		//we check whether we should project on x=y or x=-y then compute the norm of the projection
		if (abs(x_center+y_center)>abs(x_center-y_center)) { 
			proj_orth = norm((x_center - y_center) / 2,-(x_center-y_center)/2);
		}
		else {
			proj_orth = norm((x_center + y_center) / 2, (x_center + y_center) / 2);
		}
		
		return (MIN(dam_h/2, MAX(0., exp(-pow(proj_orth, 2.)) / alpha - beta)));
	}
}
