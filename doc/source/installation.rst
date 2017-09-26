.. _installation:

.. ---------------------------------------------------------------------------
.. Copyright 2017 Intel Corporation
.. Licensed under the Apache License, Version 2.0 (the "License");
.. you may not use this file except in compliance with the License.
.. You may obtain a copy of the License at
..
..      http://www.apache.org/licenses/LICENSE-2.0
..
.. Unless required by applicable law or agreed to in writing, software
.. distributed under the License is distributed on an "AS IS" BASIS,
.. WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
.. See the License for the specific language governing permissions and
.. limitations under the License.
.. ---------------------------------------------------------------------------




Installation
************

Requirements
============

Intel® Nervana™ graph runs on **Python 2.7** or **Python 3.4+**, and we support both Linux* and Mac OS X* machines. Before installing, make sure you have recent versions of the following packages (package names on different systems shown):

.. csv-table::
   :header: "Ubuntu", "OSX", "Description"
   :widths: 20, 20, 40
   :escape: ~

   python-pip, pip, Tool to install Python dependencies
   python-virtualenv (*), virtualenv (*), Allows creation of isolated environments ((*): This is required only for Python 2.7 installs. With Python3: test for presence of ``venv`` with ``python3 -m venv -h``)
   libhdf5-dev, h5py, Enables loading of hdf5 formats
   libyaml-dev, pyaml, Parses YAML format inputs
   pkg-config, pkg-config, Retrieves information about installed libraries

Installation
============

We recommend installing inside a virtual environment.

To create and activate a Python 3 virtualenv::

    python3 -m venv .venv
    . .venv/bin/activate

Alternately, you can instead create and activate a Python 2.7 virtualenv like this::

    virtualenv -p python2.7 .venv
    . .venv/bin/activate

To download the Intel Nervana graph (ngraph) source code, run the following command::

    git clone git@github.com:NervanaSystems/ngraph.git
    cd ngraph

To install with Intel® Math Kernel Library for Deep Neural Networks (Intel® MKL-DNN) support, download and install the Intel® MKL-DNN package::

    git clone https://github.com/01org/mkl-dnn.git
    cd mkl-dnn/scripts && ./prepare_mkl.sh && cd ..
    mkdir -p build && cd build
    cmake -DCMAKE_INSTALL_PREFIX=$PWD/../install .. && make install
    cd ../.. && export MKLDNN_ROOT=$PWD/mkl-dnn/install

To build and install, run::

    make install

To add GPU support::

    make gpu_prepare

Getting Started
===============

Several jupyter* notebook walkthroughs demonstrate how to use Intel Nervana graph:

* ``examples/walk_through/`` guides developers through implementing logistic regression with ngraph
* ``examples/mnist/MNIST_Direct.ipynb`` demonstrates building a deep learning model using ngraph directly.

The neon™ framework can also be used to define and train deep learning models:

* ``examples/mnist/mnist_mlp.py``: Multilayer perceptron network on MNIST dataset.
* ``examples/cifar10/cifar10_conv.py``: Convolutional neural network on CIFAR-10.
* ``examples/cifar10/cifar10_mlp.py``: Multilayer perceptron on CIFAR-10 dataset.
* ``examples/ptb/char_rnn.py``: Character-level RNN model on Penn Treebank data.

We also include examples for using TensorFlow* to define graphs that are then passed to ngraph for execution:

* ``frontends/tensorflow/examples/minimal.py``
* ``frontends/tensorflow/examples/logistic_regression.py``
* ``frontends/tensorflow/examples/mnist_mlp.py``


Developer Guidelines
====================

Before checking in code, run the unit tests and check for style errors::

    make test_cpu test_gpu test_integration
    make style

Documentation can be generated via::

    sudo apt-get install pandoc
    make doc

You can view the documentation at ``doc/build/html/index.html``.