/**
 * @file dam_break.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2022)
 * @version 1.03.01
 * @date 2022-03-29
 *
 * @brief Computes dam break solutions
 * @details 
 * Analytic solution: dam break without friction, see \cite Ritter92 \cite Stoker57.
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

#ifndef DAM_BREAK_HPP
#define DAM_BREAK_HPP

/** @class Dam_break
 * @brief Computes dam break solutions
 * @details 
 * Class that computes the solutions for a dam break without friction, see \cite Ritter92 \cite Stoker57.
 */

class Dam_break: public Solution{

	public:
		
	/** @brief Constructor */
	explicit Dam_break(Parameters &);

	/** @brief Destructor */
	virtual ~Dam_break();

	/** @brief Computes the solution */	
	void compute() override;
	
	/** @brief Function \f$x^6-9v_{right}^2x^4+16v_{left}\, v_{right}^2x^3-v_{right}^2(v_{right}^2+8v_{left}^2)x^2+v_{right}^6 \f$ to get the roots by dichotomy */
	SCALAR function(SCALAR,SCALAR,SCALAR) const;
	
	/** @brief Writes the parameters of the solution */	
	void param(SCALAR, SCALAR , SCALAR , SCALAR ) const;

	private:
		
	SCALAR x_a, x_b, mid; // variables for dichotomy
	SCALAR xdam; //the dam location
	SCALAR h_mid, u_mid, c_mid; //water height, velocity and wave velocity in the intermediate state (only for the dam break on wet soil: Stoker's solution)
	SCALAR v; //the shock velocity (only for the Stoker's solution)
	SCALAR h_left, h_right; // hl (resp. hr) the water heights on the left resp. right) of the dam
	SCALAR c_left, c_right; // cl (resp. cr) left (resp. right) wave velocity
	SCALAR eps; // the allowed error
	int nmax; // the maximum number of iterations
	int iter; // number of iteration with the dichotomy
	SCALAR func; // the unknown

};
#endif
