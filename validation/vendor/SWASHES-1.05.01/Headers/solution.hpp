/**
 * @file solution.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2024)
 * @author Maxime Rougier <maximerougier01@gmail.com> (2022)
 * @version 1.04.02
 * @date 2024-10-28
 *
 * @brief Common file
 * @details 
 * Common part for all the solutions.
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

#include "parameters.hpp"

#ifndef SOLUTION_HPP
#define SOLUTION_HPP

/** @class Solution
 * @brief Analytic solution
 * @details 
 * Class that contains all the common declarations for the solutions.
 */


class Solution{
	protected :
	
	/** Number of cells in x. */
	const int NX_EX;
	/** Number of cells in y. */
	const int NY_EX; 
	
	/** Final time.*/
	SCALAR T;
	/** Dimensions of the domain in x. */
	SCALAR L;
	/** Dimensions of the domain in y. */
	SCALAR l;
	/** Space step in x. */
	SCALAR dx_ex;
	/** Space step in y. */
	SCALAR dy_ex; 

	/** Array for the first coordinate. */
	SCALAR * xex; 
	/** Array for the second coordinate. */
	SCALAR * yex; 
	/** Array for the water height. */
	SCALAR * hex; 
	/** Array for the flow velocity. */
	SCALAR * uex; 
	/** Array for the flow discharge. */
	SCALAR * qex; 
	/** Array for the topography. */
	SCALAR * zex;

	public:
		
	/** @brief Constructor */
	Solution(Parameters &);

	/** @brief Allocations of the tables */
	void allocation();

	/** @brief Deallocation of the tables */
	void deallocation();

	/** @brief Function to be specified in case */
	virtual void compute() =0;
		
	/** @brief Saves the analytic solution at the final time with the critical height */
	void savefinalcritical(const SCALAR *, const SCALAR*, SCALAR*, const SCALAR *) const;
	
	/** @brief Saves the analytic solution at the final time with the critical height and the initial topography */
	void savefinalcriticalinit(const SCALAR *, const SCALAR*, SCALAR*, const SCALAR *, const SCALAR *) const;
	
	/** @brief Saves the analytic solution at the final time without u */
	void savefinalmu(const SCALAR *, const SCALAR*, const SCALAR*) const;
	
	/** @brief Saves the analytic solution at the final time in 2D */
	void savefinal2D(const SCALAR *, const SCALAR *, TAB, TAB, TAB, TAB) const;

	/** @brief Saves the analytic solution at the final time in a spherical geometry */
	void savefinalSpherical(const SCALAR *,const SCALAR *, TAB, TAB, TAB, TAB) const;
	
	/** @brief Saves the analytic solution at the final time when written in concentrations */
	void savefinalConcentrations(const SCALAR *, SCALAR *, SCALAR *, SCALAR *, SCALAR *) const;
		
	/** @brief Writes the version of the software and the choice of the solution */
	void head(const Parameters &, const string &, const string &) const;
	
	/** @brief Destructor */
	virtual ~Solution();
};
#endif
