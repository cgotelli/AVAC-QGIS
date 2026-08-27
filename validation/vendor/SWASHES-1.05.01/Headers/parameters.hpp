/**
 * @file parameters.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2015)
 * @version 1.03.00
 * @date 2015-10-28
 *
 * @brief Gets parameters
 * @details 
 * Reads the parameters, checks their values, returns the use if needed.
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

#include "misc.hpp"

#ifndef PARAMETERS_HPP
#define PARAMETERS_HPP

/** @class Parameters
 * @brief Gets parameters
 * @details 
 * Class that reads the parameters, checks their values and 
 * contains all the common declarations to get the values of the parameters.
 */


class Parameters{
	protected :
	
	/** Number of cells in x. */
	int nx_ex; 
	/** Number of cells in y. */
	int ny_ex;
	/** Value corresponding to the dimension of the solution. */
	SCALAR choicedim;
	/** Value corresponding to the type of the solution. */
	int choicetype;
	/** Value corresponding to the chosen solution. */
	int choice;
	/** Value corresponding to the domain of the solution. */
	int choicedomain;
	
	public :
	
	/** @brief Constructor */
	Parameters(int, char**);

	/** @brief Destructor */
	virtual ~Parameters();
	
	/** @brief Prints help */	
	void help() const;

	/** @brief Gives the number of cells in x */
	int get_nxex() const ;
	
	/** @brief Gives the number of cells in y */
	int get_nyex() const ;
	
	/** @brief Gives the dimension */
	SCALAR get_choicedim() const ;
	
	/** @brief Gives the type */
	int get_choicetype() const ;

	/** @brief Gives the chosen solution */
	int get_choice() const ;
	
	/** @brief Gives the domain */
	int get_choicedomain() const ;

};
#endif
