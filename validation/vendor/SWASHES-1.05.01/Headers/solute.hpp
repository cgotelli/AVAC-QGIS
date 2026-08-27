/**
 * @file solute.hpp
 * @author Carine Lucas <carine.lucas@univ-orleans.fr> (2024)
 * @version 1.04.02
 * @date 2024-10-31
 *
 * @brief Computes solute solutions
 * @details
 * Analytic solution: solute solution, see \cite BZ24.
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

#ifndef SOLUTE_HPP
#define SOLUTE_HPP

  /** @class Solute
   * @brief Computes solute solutions
   * @details
   * Class that computes the solutions for a solute problem, see \cite BZ24.
   */

class Solute : public Solution {

public:

	/** @brief Constructor */
	explicit Solute(Parameters&);

	/** @brief Destructor */
	virtual ~Solute();

	/** @brief Computes the solution */
	void compute() override;

	/** @brief Writes the parameters of the solution */
	void param(SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR, SCALAR) const;
	
	/** @brief Compute the inital Gaussian distribution of Solute#phi */
	SCALAR phi0(SCALAR, SCALAR, SCALAR);
	
	/** @brief Compute the inital zero distribution of Solute#psi */
	SCALAR psi0(SCALAR);


private:

	SCALAR mu, sigma; // parameters of the initial Gaussian dissolved solute concentration
	SCALAR lambda; // degradation constant (in s^-1)
	SCALAR u; // water velocity (in m/s)
	SCALAR C; // sediment mass concentration in suspension (in kg/m^3)
	SCALAR kd; // equilibrium distribution coefficient (in m^3/kg)
	SCALAR Km1; // desorption rate (in s^-1)

	string choice; // text that characterize the solution
	
	SCALAR * phiex; // dissolved solute concentration (in kg/m^3)
	SCALAR * psiex; // adsorbed solute concentration (in kg/m^3)
	SCALAR * tabphi0; // initial dissolved solute concentration at xex values (in kg/m^3) 
	SCALAR * tabpsi0; // initial adsorbed solute concentration at xex values (in kg/m^3) 
	
	SCALAR phix0=0.0; // left boundary on the dissolved solute concentration (in kg/m^3)
	SCALAR psix0=0.0; // left boundary on the adsorbed solute concentration (in kg/m^3)
};
#endif
