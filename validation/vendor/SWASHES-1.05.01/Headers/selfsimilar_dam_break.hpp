/**
 * @file selfsimilar_dam_break.hpp
 * @author Serge Bodjona (2013)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2014-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes self-similar dam break solutions
 * @details 
 * Analytic solution: self-similar solution for dam break with friction, \n
 * see Self-similar_solutions.pdf in the doc folder or in the bibliography of sourcesup.
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

#ifndef SELFSIMILAR_DAM_BREAK_HPP
#define SELFSIMILAR_DAM_BREAK_HPP

/** @class Selfsimilar_dam_break
 * @brief Computes self-similar dam break solutions
 * @details 
 * Class that computes the self-similar solutions for dam break with friction,
 * see Self-similar_solutions.pdf in the doc folder or in the bibliography of sourcesup.
 */

class Selfsimilar_dam_break: public Solution{

	public:
		
	/** @brief Constructor */
	explicit Selfsimilar_dam_break(Parameters &);

	/** @brief Destructor */
	virtual ~Selfsimilar_dam_break();

	/** @brief Computes the solution */	
	void compute() override;
	
	/** @brief Writes the parameters of the solution */	
	void param(SCALAR, SCALAR , SCALAR, SCALAR, SCALAR, SCALAR , SCALAR ) const;

	private:
	
	int choice;
	SCALAR xdam; // half-lenght of the dam
	SCALAR shift; // shift to get a domain between 0 and L.
	SCALAR xL, xR; //the dam location: the fluid is initially between xL and xR
	SCALAR hinit; //the initial height of the fluid
	SCALAR k1; // friction coefficient = -3*nu
	SCALAR k; // coefficient used in the approximate (kinematic or diffusive wave) equation
	SCALAR C1; // constant for the computation of the solution
	SCALAR Tm15; // Tm15 = T^{-1/5}
	SCALAR alpha, beta; // topography: zb = alpha x + beta
};
#endif
