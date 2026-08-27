/**
 * @file spherical.hpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.00
 * @date 2022-07-13
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

#ifndef SOLUTION_HPP
#include "solution.hpp"
#endif

#ifndef SPHERICAL_HPP
#define SPHERICAL_HPP

  /** @class Spherical
   * @brief Computes Static solutions in spherical geometry
   * @details
   * Class that computes different static solutions in spherical geometry, see \cite Williamson92.
   */

class Spherical : public Solution {

public:

	/** @brief Constructor */
	explicit Spherical(Parameters&);

	/** @brief Destructor */
	virtual ~Spherical();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR, SCALAR) const;




private:

	TAB hex2D, vex2D, uex2D, rhoex;
	//here rhoex corresponds to the topography compared with the base sea level radius

	SCALAR* lambdaex;
	//lambdaex is the longitudinal angle
	SCALAR* thetaex;
	//thetaex is the latitudinal angle

	SCALAR h0, u0, radius, omega, alpha; 
	//Omega correponds to the pulsation of earth rotation 
	//alpha is the angle between the spherical pole and the earth axis

	int solu; // the number of the solution


	/** @brief Copy constructor */
	Spherical(const Spherical &);

	/** @brief operator= */
	Spherical & operator=(const Spherical &);
};
#endif