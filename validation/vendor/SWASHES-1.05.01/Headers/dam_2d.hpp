/**
 * @file dam_2d.hpp
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

#ifndef SOLUTION_HPP
#include "solution.hpp"
#endif

#ifndef DAM_2D_HPP
#define DAM_2D_HPP

  /** @class Dam_2D
   * @brief Computes Static dam solutions in 2D
   * @details
   * Class that computes the solutions with a dam in 2d, see \cite Delestre13.
   */

class Dam_2D : public Solution {

public:

	/** @brief Constructor */
	explicit Dam_2D(Parameters&);

	/** @brief Destructor */
	virtual ~Dam_2D();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR) const;

	/** @brief Computes the norm of a vector*/
	SCALAR norm(SCALAR, SCALAR);

	/** @brief Computes the topography of the center ring for the second domain*/
	SCALAR ring(SCALAR, SCALAR, SCALAR, SCALAR);

	/** @brief Computes the topography of the cross for the second domain*/
	SCALAR cross(SCALAR, SCALAR, SCALAR, SCALAR);

private:

	TAB hex2D, zex2D, uex2D, vex2D;
	SCALAR dam_d, dam_h, dam_w;

	int solu; // the number of the solution
};
#endif

