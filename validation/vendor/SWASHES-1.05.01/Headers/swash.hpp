/**
 * @file swash.hpp
 * @author Noemie Gaveau <noemie.gaveau@gmail.com> (2015)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2015-2022)
 * @version 1.03.01
 * @date 2022-03-30
 *
 * @brief Computes the solutions of the swash over an inclined plane
 * @details
 * Analytic solution: swash solutions, see \cite Marche05, \cite CaGr58
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

#ifndef SWASH_HPP
#define SWASH_HPP

/** @class Swash
* @brief Computes the solutions of the swash over an inclined plane
* @details
* Class that computes the solutions of the swash over an inclined plane, see \cite Marche05, \cite CaGr58.
*/

class Swash : public Solution{

	public:

	/** @brief Constructor */
	explicit Swash(Parameters &);

	/** @brief Destructor */
	virtual ~Swash();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Computes the non-dimensional speed ua and the non-dimensional free surface eta */
	void ua_eta(SCALAR, SCALAR,SCALAR,SCALAR,SCALAR,SCALAR*, int);

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR) const;
	
	/** @brief Writes the left boundary condition (at each dt = 0.01s) */
	void leftcondition(int, SCALAR, SCALAR) const;

	/** @brief Computes the kth Bessel function for k=0,1 or 2 */
	SCALAR J(int, SCALAR) ;

	private:

	SCALAR e; // initial curvature of the wave
	SCALAR alpha; // topography coefficient
	SCALAR tf; // time value
	SCALAR dt; // time step for the backup of the left boundary condition
	int nt; // number of time iterations
	int sol; // 1 if transient, 2 if periodic
	int flag; // to know if h=0.
	SCALAR A; // amplitude of the periodic solution
	SCALAR a ;
	SCALAR ta ; // non-dimentional time
	SCALAR* xexa ; //non-dimensional x
	SCALAR* zexa ; //non-dimensional z
	SCALAR x0 ; //abscissa changement
	SCALAR* uexa; //non-dimensional speed
	SCALAR* hexa;//non-dimentional water height
	SCALAR eta0; // initial free surface
	SCALAR* etaa;//non-dimensional free surface
	string namefile;

	/** @brief Copy constructor */
	Swash(const Swash &);

	/** @brief operator= */
	Swash & operator=(const Swash &);


};
#endif
