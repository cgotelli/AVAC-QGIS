/**
 * @file step.hpp
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.00
 * @date 2022-07-28
 *
 * @brief Computes dam break with a step solutions
 * @details
 * Analytic solution: dam break with a step without friction, see \cite Han14.
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

#ifndef STEP_HPP
#define STEP_HPP

  /** @class Step
   * @brief Computes dam break with a step solutions
   * @details
   * Class that computes the solutions for a dam break with a step without friction, see \cite Han14.
   */

class Step : public Solution {

public:

	/** @brief Constructor */
	explicit Step(Parameters&);

	/** @brief Destructor */
	virtual ~Step();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR) const;

	/** @brief Computes the value of the rarefaction function from the left state*/
	SCALAR r1(SCALAR, SCALAR, SCALAR);

	/** @brief Computes the speed of the shock wave in the second characteristic field*/
	SCALAR spshock(SCALAR, SCALAR, SCALAR);


private:
	SCALAR xdam, step_size; //the dam location and size of the step
	SCALAR h_left, h_right; // hl (resp. hr) the water heights on the left (resp. right) of the dam
	SCALAR u_left, u_right;
	SCALAR h_1, h_2; //water heights before, at and after the step respectively
	SCALAR u_1, u_2; //speed before, at and after the step respectively

	int solu;
};
#endif
