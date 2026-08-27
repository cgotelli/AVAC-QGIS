########################## Makefile ##############################################
#
# author Carine Lucas <carine.lucas@univ-orleans.fr> (2010-2022)
# author: Marco Mancini <marco.mancini@univ-orleans.fr> (2019)
# version: 1.03.01
# date: 2022-03-28
#
# copyright License Cecill-V2 <http://www.cecill.info/licences/Licence_CeCILL_V2-en.html>
#
# (c) CNRS - Universite d'Orleans - INRA (France)
#
# This file is part of SWASHES software.
# <https://sourcesup.renater.fr/projects/swashes/>
#
# SWASHES = Shallow-Water Analytic Solutions for Hydraulic and
# Environmental Studies.
# This software is a computer program whose purpose is to compute analytic
# solutions for Shallow-Water equations.
#
# LICENSE
#
# This software is governed by the CeCILL license under French law and
# abiding by the rules of distribution of free software.  You can  use,
# modify and/ or redistribute the software under the terms of the CeCILL
# license as circulated by CEA, CNRS and INRIA at the following URL
# <http://www.cecill.info>.
#
# As a counterpart to the access to the source code and  rights to copy,
# modify and redistribute granted by the license, users are provided only
# with a limited warranty  and the software's author,  the holder of the
# economic rights,  and the successive licensors  have only  limited
# liability.
#
# In this respect, the user's attention is drawn to the risks associated
# with loading,  using,  modifying and/or developing or reproducing the
# software by the user in light of its specific status of free software,
# that may mean  that it is complicated to manipulate,  and  that  also
# therefore means  that it is reserved for developers  and  experienced
# professionals having in-depth computer knowledge. Users are therefore
# encouraged to load and test the software's suitability as regards their
# requirements in conditions enabling the security of their systems and/or
# data to be ensured and,  more generally, to use and operate it in the
# same conditions as regards security.
#
# The fact that you are presently reading this means that you have had
# knowledge of the CeCILL license and that you accept its terms.
#
##################################################################################
SHELL:=/bin/bash
CONFIG := ./make_config

include $(CONFIG)

TARGET_EXEC ?= swashes

BUILD_DIR ?= ./build

SRC_DIRS ?= ./Sources

INC_DIRS ?= ./Headers

Compil_msg=" Compiling $(TARGET_EXEC)"

SRCS := $(shell find $(SRC_DIRS) -name "*.cpp" -type f \( ! -iname ".*" \))

OBJS := $(SRCS:%=$(BUILD_DIR)/%.o)
DEPS := $(OBJS:.o=.d)

INC_DIRS := $(shell find $(INC_DIRS) -type d)
INC_FLAGS := $(addprefix -I,$(INC_DIRS))

CPPFLAGS += $(INC_FLAGS) -MMD -MP

MKDIR_P ?= mkdir -p

.PHONY: $(TARGET_EXEC) clean start_prt

$(TARGET_EXEC) : start_prt $(BUILD_DIR)/$(TARGET_EXEC)
	@echo " $(TARGET_EXEC)  => $(BIN)"
	@cp $(BUILD_DIR)/$(TARGET_EXEC) $(BIN)/

$(BUILD_DIR)/$(TARGET_EXEC): $(OBJS)
	@echo " Linking $@"
	@$(CPP) $(OBJS) -o $@ $(LDFLAGS)

start_prt :
	@echo $(Compil_msg)

-include $(DEPS)

$(BUILD_DIR)/%.cpp.o: %.cpp $(CONFIG)
	@echo "     Compiling $<"
	@$(MKDIR_P) $(dir $@)
	@$(CPP) $(CPPFLAGS) -c $< -o $@

clean:
	$(RM) -r $(BUILD_DIR)
	$(RM)  $(BIN)/$(TARGET_EXEC)
	
