#### SWASHES
#### version 1.05.01, 2026-04-09

SWASHES is a library of Shallow Water Analytic Solutions for Hydraulic and Environmental Studies.
A significant number of analytic solutions to the Shallow Water equations is described in a unified formalism.

This software is distributed under CeCILL-V2 (GPL compatible) free software license
(see <http://www.cecill.info/licences/Licence_CeCILL_V2-en.html>).

The following explains quickly how to compile SWASHES.
A more complete documentation can be found in the doc/Documentation.pdf file.

To be informed of SWASHES developments, please, subcribe to the dedicated (low traffic) mailing list: <http://listes.univ-orleans.fr/sympa/subscribe/swashes.infos>.
To contact the main developers of SWASHES, please, send an email to swashes.contact@listes.univ-orleans.fr .

##############################
Users
##############################

The primary repository of SWASHES is: <https://sourcesup.renater.fr/projects/swashes/>.
From there, you can download zip packages (see tab "Files"), submit bugs, etc.

If you are using the Conda package manager, the SWASHES package is available at
<https://anaconda.org/lrntct/swashes> (contribution of Laurent Courty).

SWASHES is also available as a Python library named pyswashes (contribution of Laurent Courty).
With it you can obtain the selected analytic solution in the form of a csv, Pandas dataframe, NumPy array or ASCII Grid format.
See <https://pyswashes.readthedocs.io/en/latest/>

For windows' users: look at the application note about how to compile and run SWASHES
<https://sourcesup.renater.fr/docman/view.php/876/3951/AppNote-windows.pdf>

Very short description to compile and run of SWASHES:
When you are in the SWASHES directory, write the following lines:

make clean
make

and then run SWASHES:

./bin/swashes PARAMETERS

If you are on a multicore machine, to speedup the compilation, you could replace `make` by `make -j N`, where N is the number of cores you have.

##############################
Developers
##############################

Always comment the files, at the beginning of the file, using Doxygen syntax (www.doxygen.org/).

---------- Doxygen -----------

In order to generate the Doxygen html file, the Doxygen_config_file_html file is saved in the doc directory.
To run Doxygen (version 1.8.0), from the SWASHES directory, use the command:

doxygen doc/Doxygen_config_file_html

Warning: Graphviz (http://www.graphviz.org/) must be in your PATH to generate HTML diagrams.
If not, change the HAVE_DOT parameter of the Doxygen_config_file_html.

=> In the doc/html/ directory, index.html is created.

To generate the Doxygen latex (pdf) file, you must use the Doxygen_config_file_latex file and compile the tex file:

doxygen doc/Doxygen_config_file_latex
cd doc/latex
make

=> In the doc/latex directory, refman.pdf is created.

-------- Check list  --------

Before creating a new tag / version, check:
- if the doc is coherent (also date and version),
- generate again the doxygen file (do not forget the version number),
- check the version in misc.hpp file,
  -> for these 3 points, use the script "UpdateDateVersion.sh"
- look at the g++ warnings and solve them (when applicable),
- check for memory leaks and other flaws: run SWASHES with valgrind in such a way that the program goes through your changes,
- complete the changelog.txt file (included the "ready for tag "version X.XX.ZZ") and update the todo list,
- place the tag "version X.XX.ZZ".
