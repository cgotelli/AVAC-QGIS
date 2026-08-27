/**
 * @file rain.hpp
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2025)
 * @version 1.05.00
 * @date 2025-04-02
 *
 * @brief Computes a solution with mobile rain
 * @details
 * Analytic solution: mobile rain, with different velocities compared to the flow, see \cite DeLu25.
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

#ifndef RAIN_HPP
#define RAIN_HPP

  /** @class Rain
   * @brief Computes a solution with mobile rain
   * @details
   * Class that computes the solutions with mobile rain, with different velocities compared to the flow, see \cite DeLu25.
   */

class Rain : public Solution {

public:

	/** @brief Constructor */
	explicit Rain(Parameters&);

	/** @brief Destructor */
	virtual ~Rain();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR) const;

	/** @brief Computes the value of the integral of the rain*/
	SCALAR rainint(SCALAR, SCALAR, SCALAR);
	
	/** @brief Computes the solution at time t*/
	void computet(SCALAR);


private:
	SCALAR S0; // opposite of the slope of the domain
	SCALAR R0; // maximal rain intensity
	SCALAR vr; // rain velocity
	SCALAR C; // friction coefficient
	SCALAR h0, q0; // water height and discharge
	SCALAR x0, Lr; // characteristics of the rain distribution 
	int raincase ; // choice of the case
	
	SCALAR t0 = 0;
	SCALAR tl = 0;
	SCALAR t0l = 0;
	SCALAR tr = 1;

};
#endif
