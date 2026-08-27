/**
 * @file bedload.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2012)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2022)
 * @version 1.04.01
 * @date 2024-01-19
 *
 * @brief Computes solutions with bedload
 * @details 
 * Analytic solution: the bed is moving with bedload, see \cite Berthon12.
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

#ifndef BEDLOAD_HPP
#define BEDLOAD_HPP

/** @class Bedload
 * @brief Computes solutions with bedload
 * @details 
 * Class that computes the solutions where the bed is moving with bedload, see \cite Berthon12.
 */


class Bedload: public Solution{

	public:
	
	/** @brief Constructor */
	explicit Bedload(Parameters &);

	/** @brief Destructor */
	virtual ~Bedload();

	/** @brief Computes the solution */
	void compute() override;
	
	/** @brief Writes the parameters of the solution */
	void param(SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR , SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR ) const;
	
	/** @brief Writes a warning about the the solution */
	void paramwarning() const;

	private:
	SCALAR * z0; // initial topography
	SCALAR uexl, hexl, z0l, zexl, uexr, hexr, z0r, zexr; // boundary values
	SCALAR alpha, beta, A, C, q, ucr2, p, ue2;
	SCALAR k, f, d, s, tcr, c1, c2; // for MPM

	/** @brief Copy constructor */
	Bedload(const Bedload &);

	/** @brief operator= */
	Bedload & operator=(const Bedload &);

};
#endif
