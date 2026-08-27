/**
 * @file macdonald_like.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2012-2022)
 * @version 1.03.01
 * @date 2022-03-30
 *
 * @brief Computes Mac Donald solutions
 * @details 
 * Analytic solution: Mac Donald solutions in 1d, 
 * see \cite MacDonald96 \cite MacDonald97, \cite Delestre13 and \cite Vo08.
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

#ifndef MACDONALD_LIKE_HPP
#define MACDONALD_LIKE_HPP

/** @class MacDonald_like
 * @brief Computes Mac Donald solutions
 * @details 
 * Class that computes Mac Donald solutions in 1d, 
 * see \cite MacDonald96, \cite MacDonald97, \cite Delestre13 and \cite Vo08.
 */


class MacDonald_like: public Solution{

	public:
		
	/** @brief Constructor */
	explicit MacDonald_like(Parameters &);

	/** @brief Destructor */
	virtual ~MacDonald_like();

	/** @brief Computes the solution */	
	void compute() override;

	/** @brief Evaluation of the slope variation for Manning friction law */
	SCALAR Delta_topo_Manning(SCALAR , SCALAR , SCALAR , SCALAR , SCALAR ) const;

	/** @brief Evaluation of the slope variation for Darcy-Weisbach friction law */
	SCALAR Delta_topo_Darcy_Weisbach(SCALAR , SCALAR , SCALAR , SCALAR , SCALAR ) const;
	
	/** @brief Writes the parameters of the solution */	
	void param(SCALAR , SCALAR ) const;


	private:
		
	SCALAR varz, cf, R; //slope variation, friction coefficient, rain intensity
	int choice_fric; //variable for the choice of the friction law: 0=Manning, 1=Darcy-Weisbach
	SCALAR * dhex; //the water height variation (delta h)
	SCALAR h_l_bound, h_r_bound; // water height on the left or right bound of the domain (differs from the discrete values of h)

	/** @brief Copy constructor */
	MacDonald_like(const MacDonald_like &);

	/** @brief operator= */
	MacDonald_like & operator=(const MacDonald_like &);


};
#endif
