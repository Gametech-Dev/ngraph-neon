# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
"""
To visualize HeTr computational graph with Tensorboard

1. run `python dist_hetr.py -v`

2. run `tensorboard --logdir /tmp/hetr_tb/ --port 6006`

use ssh port forwarding to run on remote server
https://stackoverflow.com/questions/37987839/how-can-i-run-tensorboard-on-a-remote-server
"""
from __future__ import print_function
from contextlib import closing
import ngraph as ng
import ngraph.transformers as ngt
from ngraph.op_graph.tensorboard.tensorboardpass import TensorBoardPass
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--iter_count", "-i", type=int, default=5, help="num iterations to run")
parser.add_argument("--visualize", "-v", action="store_true", help="enable graph visualization")
args = parser.parse_args()

# Build the graph
H = ng.make_axis(length=4, name='height')
N = ng.make_axis(length=8, name='batch')
weight = ng.make_axis(length=2, name='weight')

x = ng.placeholder(axes=[H, N])
w = ng.placeholder(axes=[weight, H])
with ng.metadata(device_id=('0', '1'), parallel=N):
    dot = ng.dot(w, x)

# Select a transformer
with closing(ngt.make_transformer_factory('hetr')()) as hetr:
    # Visualize the graph
    if args.visualize:
        hetr.register_graph_pass(TensorBoardPass('/tmp/hetr_tb'))

    # Define a computation
    computation = hetr.computation(dot, x, w)

    # Run the computation
    for i in range(args.iter_count):
        print(computation(i, i))
