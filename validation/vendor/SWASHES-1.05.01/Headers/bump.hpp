/**
 * @file bump.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Anne-Celine Boulanger <anne-celine.boulanger@inria.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes bumps solutions
 * @details 
 * Analytic solution: with a bump, see \cite Delestre13 and \cite Goutal97.
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

#ifndef SOLUTION_HPP
#include "solution.hpp"
#endif

#ifndef BUMP_HPP
#define BUMP_HPP

/** @class Bump
* @brief Computes bump solutions
* @details 
* Class that computes the solutions with a bump for the topography, see \cite Delestre13 and \cite Goutal97.
*/


class Bump: public Solution{

	public:
	
	/** @brief Constructor */
	explicit Bump(Parameters &);

	/** @brief Destructor */
	virtual ~Bump();

	/** @brief Computes the solution */	
	void compute() override;
		
	/** @brief Coefficient p for Cardano method */
	SCALAR p(SCALAR , SCALAR , SCALAR ) const;

	/** @brief Coefficient q for Cardano method */	
	SCALAR q(SCALAR , SCALAR , SCALAR , SCALAR ) const;

	/** @brief Determinant for Cardano method */
	SCALAR determinant(SCALAR , SCALAR ) const;

	/** @brief Computation of the 3rd order polynomia roots */
	SCALAR height(SCALAR , SCALAR , SCALAR , SCALAR , SCALAR ) const;

	/** @brief Defines a, b, c, d in order to solve \f$ ah^3+bh^2+ch+d \f$ */
	void abcd(SCALAR , SCALAR , SCALAR , SCALAR , SCALAR &, SCALAR &, SCALAR &, SCALAR &);

	/** @brief Steady state RH relation */
	SCALAR RHJump(SCALAR , SCALAR , SCALAR ) const;
	
	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR) const;

	private:
	
	SCALAR q_in, h_out, hmiddle; // discharge value, h at the outflow, the height at the top of the bump
	SCALAR a, b, c, d; // the coefficients of the 3rd order polynomia
	int solu; // the relative number of the bump solution
	SCALAR epsi, epsilon; //definition of epsilons
	SCALAR H_MAX; //the maximum water height
	SCALAR zmax ; // max of the topography
};
#endif
