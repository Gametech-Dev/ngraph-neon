# ----------------------------------------------------------------------------
# Copyright 2017 Nervana Systems Inc.
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
import numpy as np
from ngraph.op_graph.op_graph import TensorValueOp
from ngraph.factory.comm_node_factory import get_comm_pattern
from ngraph.op_graph.comm_nodes import calculate_scatter_axes, \
    CPUQueueBroadcastSendOp, CPUQueueBroadcastRecvOp
from multiprocessing import Process, Event, Manager
from ngraph.frontends.neon import UniformInit
from contextlib import closing
import ngraph as ng
import ngraph.transformers as ngt
import pytest
import time


ax_A = ng.make_axis(length=10, name='A')
ax_B = ng.make_axis(length=15, name='B')
ax_C = ng.make_axis(length=20, name='C')
axes = ng.make_axes([ax_A, ax_B, ax_C])


def test_calculate_new_axes_single_device():
    new_axes = calculate_scatter_axes(axes=axes, scatter_axis=ax_B, num_devices=1)
    assert new_axes.full_lengths == axes.full_lengths


@pytest.mark.parametrize("axis, num", [(ax_A, 2), (ax_B, 3), (ax_C, 4), (ax_A, 5), (ax_B, 5),
                                       (ax_C, 5)])
def test_calculate_new_axes_no_remainder(axis, num):
    new_axes = calculate_scatter_axes(axes=axes, scatter_axis=axis, num_devices=num)
    expected_axes = ng.make_axes(
        [a if a != axis else ng.make_axis(length=axis.length / num, name=a.name) for a in axes])
    assert new_axes.full_lengths == expected_axes.full_lengths


@pytest.mark.parametrize("axis, num", [(ax_B, 2), (ax_A, 3), (ax_B, 4), (ax_B, 6), (ax_C, 7)])
def tests_calculate_new_axes_has_remainder(axis, num):
    with pytest.raises(AssertionError):
        calculate_scatter_axes(axes=axes, scatter_axis=axis, num_devices=num)


def test_calculate_new_axes_zero_devices():
    with pytest.raises(ZeroDivisionError):
        calculate_scatter_axes(axes=axes, scatter_axis=ax_B, num_devices=0)


def test_calculate_new_axes_null_axes():
    with pytest.raises(TypeError):
        calculate_scatter_axes(axes=None, scatter_axis=ax_B, num_devices=2)


def test_calculate_new_axes_null_parallel_axis():
    new_axes = calculate_scatter_axes(axes=axes, scatter_axis=None, num_devices=1)
    # Checks null parallel axis. The axes calculated should have the same length as original
    assert new_axes.full_lengths == axes.full_lengths


@pytest.mark.parametrize("from_node, to_node, expected_type", [
    (None, None, None),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        None
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id='1', transformer='cpu1')),
        'direct'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='gpu', device_id='0', transformer='gpu0')),
        'direct'
    ),
    (
        TensorValueOp(ng.constant(1),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_B,
              transformer=['cpu1', 'cpu2'])),
        None
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_B,
                            transformer=['cpu1', 'cpu2'])),
        'scatter'
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        'broadcast'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        ng.Op(metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        'gather'
    ),
    (
        TensorValueOp(ng.placeholder([ax_A, ax_B]),
                      metadata=dict(device='cpu', device_id='0', transformer='cpu0')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=None,
                            transformer=['cpu1', 'cpu2'])),
        'broadcast'
    ),
    (
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'], reduce_func='mean')),
        ng.Op(metadata=dict(device='cpu', device_id=('1', '2'), parallel=ax_C,
                            transformer=['cpu1', 'cpu2'])),
        'allreduce'
    ),
])
def test_get_node_type(from_node, to_node, expected_type):
    assert expected_type == get_comm_pattern(from_node, to_node)


@pytest.mark.parametrize('config', [
    {
        'sender_index': 0,
        'device_ids': ['0', '1', '2'],
        'x_input': [1., 2., 3., 4., 5., 6.],
        'shape_input': [1, 6],
        'expected_results': [[1., 2., 3., 4., 5., 6.], [1., 2., 3., 4., 5., 6.]],
    },
    {
        'sender_index': 0,
        'device_ids': ['0', '1', '2', '3', '4', '5'],
        'x_input': [5., 9.],
        'shape_input': [1, 2],
        'expected_results': [[5., 9.], [5., 9.], [5., 9.], [5., 9.], [5., 9.]],
    },
])
def test_broadcast_ops(config):
    class myProcess(Process):
        def __init__(self, y, comp_name):
            super(myProcess, self).__init__()
            self.y = y
            self.comp_name = comp_name
            self.manager = Manager()
            self.results_qs = self.manager.Queue()
            self.exit = Event()

        def run(self):
            with closing(ngt.make_transformer_factory('cpu')()) as t:
                comp = t.computation(self.y)
                self.results_qs.put(comp())

            while not self.exit.is_set():
                time.sleep(0.1)

        def get_result(self):
            while True:
                try:
                    result = self.results_qs.get(timeout=0.2)
                    return result
                except Exception:
                    raise

    c = config
    y = [None] * len(c['device_ids'])
    active_processes = list()
    results = list()
    sender_id = c['device_ids'][c['sender_index']]
    receiver_ids = c['device_ids'][:c['sender_index']] + c['device_ids'][c['sender_index'] + 1:]

    ax_a = ng.make_axis(length=c['shape_input'][0], name='A')
    ax_b = ng.make_axis(length=c['shape_input'][1], name='B')
    axes = ng.make_axes([ax_a, ax_b])

    with ng.metadata(device='cpu', device_id=sender_id,
                     transformer='None', host_transformer='None'):
        from_node = ng.constant(axes=axes, const=c['x_input'])

    with ng.metadata(device='cpu', device_id=tuple(receiver_ids),
                     transformer='None', host_transformer='None'):
        to_node = ng.constant(axes=axes, const=0)

    y[c['sender_index']] = CPUQueueBroadcastSendOp(from_node=from_node, to_node=to_node)
    for i in range(len(c['device_ids'])):
        if i != c['sender_index']:
            sc_op = CPUQueueBroadcastRecvOp(to_node=to_node, send_node=y[c['sender_index']])
            sc_op.idx = i if i < c['sender_index'] else i - 1
            y[i] = sc_op

    for i in range(len(c['device_ids'])):
        active_processes.append(myProcess(y[i], 'cpu' + str(i)))
        active_processes[i].start()

    for i in range(len(c['device_ids'])):
        if i != c['sender_index']:
            results.append(active_processes[i].get_result().tolist())
        active_processes[i].exit.set()
        active_processes[i].join()

    np.testing.assert_array_equal(results, c['expected_results'])


@pytest.mark.parametrize('config', [
    {
        'input': 36,
        'func': 'mean',
        'device_id': (1, 2),
        'expected_result': [[[-35.0, -35.0], [-35.0, -35.0], [-35.0, -35.0], [-35.0, -35.0]]],
    },
    {
        'input': 36,
        'func': 'sum',
        'device_id': (1, 2),
        'expected_result': [[[-71.0, -71.0], [-71.0, -71.0], [-71.0, -71.0], [-71.0, -71.0]]],
    },
    {
        'input': 36,
        'func': 'mean',
        'device_id': (1, 4, 3, 2),
        'expected_result': [[[-35.0, -35.0], [-35.0, -35.0], [-35.0, -35.0], [-35.0, -35.0]]],
    },
    {
        'input': 25,
        'func': 'sum',
        'device_id': (5, 7, 3, 4),
        'expected_result': [[[-99.0, -99.0], [-99.0, -99.0], [-99.0, -99.0], [-99.0, -99.0]]],
    },
])
def test_allreduce_hint(config):
    c = config

    with ng.metadata(device_id=c['device_id']):
        axis_A = ng.make_axis(length=4, name='axis_A')
        axis_B = ng.make_axis(length=2, name='axis_B')
        var_A = ng.variable(axes=[axis_A], initial_value=UniformInit(1, 1)).named('var_A')
        var_B = ng.variable(initial_value=UniformInit(c['input'], c['input']),
                            axes=[axis_B]).named('var_B')
        var_B.metadata['reduce_func'] = c['func']
        var_minus = (var_A - var_B).named('var_minus')
        var_minus.metadata['parallel'] = axis_A
    with closing(ngt.make_transformer_factory('hetr')()) as hetr:
        out_comp = hetr.computation([var_minus]).named('out_comp')
        result = out_comp()

        np.testing.assert_array_equal(result, c['expected_result'])


@pytest.mark.parametrize('config', [
    {
        'input': 1,
        'device_id': (1, 2),
        'result_two': [[4.0, 4.0, 4.0, 4.0],
                       [4.0, 4.0, 4.0, 4.0]],
        'result_one': [[2.0, 2.0, 2.0, 2.0],
                       [2.0, 2.0, 2.0, 2.0]],
    },
])
def test_multiple_gather_ops(config):
    c = config

    H = ng.make_axis(length=2, name='height')
    W = ng.make_axis(length=4, name='width')
    x = ng.placeholder(axes=[H, W])
    with ng.metadata(device_id=c['device_id'], parallel=W):
        x_plus_one = x + 1
        x_plus_two = x_plus_one + 2
    with closing(ngt.make_transformer_factory('hetr')()) as hetr:
        plus = hetr.computation([x_plus_two, x_plus_one], x)
        result_two, result_one = plus(c['input'])

        np.testing.assert_array_equal(result_two, c['result_two'])
        np.testing.assert_array_equal(result_one, c['result_one'])
