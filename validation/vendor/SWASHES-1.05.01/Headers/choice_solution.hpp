/**
 * @file choice_solution.hpp
 * @author Olivier Delestre <olivierdelestre41@yahoo.fr> (2010)
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2025)
 * @author Noemie Gaveau <noemie.gaveau@gmail.com> (2015)
 * @author Maxime Rougier <rougiermaxime01@gmail.com> (2022)
 * @version 1.05.00
 * @date 2025-04-02
 *
 * @brief Choice of the solution
 * @details
 * From the value of the corresponding parameter,
 * calls the chosen solution.
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
#include "dam_break.hpp"
#endif

#ifndef SELFSIMILAR_DAM_BREAK_HPP
#include "selfsimilar_dam_break.hpp"
#endif

#ifndef DRESSLER_DAM_HPP
#include "dressler_dam.hpp"
#endif

#ifndef SLUICE_GATE_HPP
#include "sluice_gate.hpp"
#endif

#ifndef RAIN_HPP
#include "rain.hpp"
#endif

#ifndef STEP_HPP
#include "step.hpp"
#endif

#ifndef INCLINED_PLANE_HPP
#include "inclined_plane.hpp"
#endif

#ifndef BUMP_HPP
#include "bump.hpp"
#endif

#ifndef SOLUTE_HPP
#include "solute.hpp"
#endif

#ifndef DAM2D_HPP
#include "dam_2d.hpp"
#endif

#ifndef SPHERICAL_HPP
#include "spherical.hpp"
#endif

#ifndef MACDONALD_LIKE_HPP
#include "macdonald_like.hpp"
#endif

#ifndef MACDONALD_LIKE_DIFFUS_HPP
#include "macdonald_like_diffus.hpp"
#endif

#ifndef THACKER_HPP
#include "thacker.hpp"
#endif

#ifndef BEDLOAD_HPP
#include "bedload.hpp"
#endif

#ifndef THACKER2D_HPP
#include "thacker2d.hpp"
#endif

#ifndef MACDONALDB1_HPP
#include "macdonaldb1.hpp"
#endif

#ifndef MACDONALDB2_HPP
#include "macdonaldb2.hpp"
#endif


#ifndef SAMPSON_HPP
#include "sampson.hpp"
#endif

#ifndef SWASH_HPP
#include "swash.hpp"
#endif

#ifndef CHOICE_SOLUTION_HPP
#define CHOICE_SOLUTION_HPP

/** @class Choice_solution
 * @brief Choice of the solution
 * @details
 * Class that calls the chosen solution.
 */


class Choice_solution{
	private :

	Solution * sol;
	int dim2;

	/** @brief Copy constructor */
	Choice_solution(const Choice_solution &);

	/** @brief operator= */
	Choice_solution & operator=(const Choice_solution &);


	public :

	/** @brief Constructor */
	explicit Choice_solution(Parameters &);

	/** @brief Computes the solution */
	void compute();

	/** @brief Destructor */
	virtual ~Choice_solution();
};
#endif
