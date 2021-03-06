# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************
# set empty to prevent any implicit rules from firing.
.SUFFIXES:

SHELL := /bin/bash

# Extract Python version
PY := $(shell python --version 2>&1  | cut -c8)
ifeq ($(PY), 2)
	PYLINT3K_ARGS := --disable=no-absolute-import,setslice-method,getslice-method,nonzero-method,zip-builtin-not-iterating
else
	PYLINT3K_ARGS :=
endif

# style checking related
STYLE_CHECK_OPTS :=
STYLE_CHECK_DIRS := src/neon tests examples

# pytest options
TEST_OPTS := --timeout=600 --cov=src/neon --timeout_method=thread
TEST_DIRS := tests/


# this variable controls where we publish Sphinx docs to
DOC_DIR := doc
DOC_PUB_RELEASE_PATH := $(DOC_PUB_PATH)/$(RELEASE)

.PHONY: env default install install_all uninstall uninstall_all clean test style lint lint3k check doc

default: install

install:
	pip install wheel
	pip install -e .

install_all: test_prepare examples_prepare doc_prepare install

test_prepare:
	pip install -r test_requirements.txt

examples_prepare:
	pip install -r examples_requirements.txt > /dev/null 2>&1

doc_prepare:
	pip install -r doc_requirements.txt > /dev/null 2>&1

uninstall:
	pip uninstall -y neon
	pip uninstall -r requirements.txt

uninstall_all: uninstall
	pip uninstall -y -r test_requirements.txt \
	-r examples_requirements.txt -r doc_requirements.txt

clean:
	find . -name "*.py[co]" -type f -delete
	find . -name "__pycache__" -type d -delete
	rm -f .coverage .coverage.*
	rm -rf neon.egg-info
	@echo

test: test_cpu


test_cpu: export PYTHONHASHSEED=0
test_cpu: test_prepare clean
	echo Running unit tests for core and cpu transformer tests...
	py.test -m "not hetr_only and not flex_only and not hetr_gpu_only" --boxed \
	--junit-xml=testout_test_cpu_$(PY).xml \
	$(TEST_OPTS) $(TEST_DIRS)
	coverage xml -i -o coverage_test_cpu_$(PY).xml


examples: examples_prepare
	for file in `find examples -type f -executable`; do echo Running $$file... ; ./$$file ; done

style: test_prepare
	flake8 --output-file style.txt --tee $(STYLE_CHECK_OPTS) $(STYLE_CHECK_DIRS)
	pylint --reports=n --output-format=colorized --py3k $(PYLINT3K_ARGS) --ignore=.venv *

lint: test_prepare
	pylint --output-format=colorized *

lint3k:
	pylint --py3k $(PYLINT3K_ARGS) --ignore=.venv *

check: test_prepare
	echo "Running style checks.  Number of style faults is... "
	-flake8 --count $(STYLE_CHECK_OPTS) $(STYLE_CHECK_DIRS) \
	 > /dev/null
	echo
	echo "Number of missing docstrings is..."
	-pylint --disable=all --enable=missing-docstring -r n \
	 src/neon | grep "^C" | wc -l
	echo
	echo "Running unit tests..."
	-py.test $(TEST_DIRS) | tail -1 | cut -f 2,3 -d ' '
	echo

fixstyle: autopep8

autopep8:
	autopep8 -a -a --global-config setup.cfg --in-place `find . -name \*.py`
	echo run "git diff" to see what may need to be checked in and "make style" to see what work remains

doc: doc_prepare
	$(MAKE) -C $(DOC_DIR) clean
	$(MAKE) -C $(DOC_DIR) html
	echo "Documentation built in $(DOC_DIR)/build/html"
	echo

publish_doc: doc
ifneq (,$(DOC_PUB_HOST))
	-cd $(DOC_DIR)/build/html && \
		rsync -avz -essh --perms --chmod=ugo+rX . \
		$(DOC_PUB_USER)$(DOC_PUB_HOST):$(DOC_PUB_RELEASE_PATH)
	-ssh $(DOC_PUB_USER)$(DOC_PUB_HOST) \
		'rm -f $(DOC_PUB_PATH)/latest && \
		 ln -sf $(DOC_PUB_RELEASE_PATH) $(DOC_PUB_PATH)/latest'
else
	echo "Can't publish.  Ensure DOC_PUB_HOST, DOC_PUB_USER, DOC_PUB_PATH set"
endif

release: check
	echo "Bump version number in setup.py"
	vi setup.py
	echo "Bump version number in doc/source/conf.py"
	vi doc/source/conf.py
	echo "Update ChangeLog"
	vi ChangeLog
	echo "TODO (manual steps): release on github and update docs with 'make publish_doc'"
	echo
