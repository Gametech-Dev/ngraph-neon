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
from __future__ import division
import multiprocessing
import collections
from orderedset import OrderedSet
from ngraph.op_graph.op_graph import TensorOp, compute_reduction_axes, \
    MutateInsteadOfCopyWithNewArgsMixin
from ngraph.op_graph.axes import Axes, make_axes, make_axis


def calculate_gather_axes(axes, gather_axis, num_devices):
    new_axes = [make_axis(a.length * num_devices, a.name)
                if gather_axis == a else a for a in axes]
    new_axes = make_axes(new_axes)
    return new_axes


def set_parallel_axes(axes, parallel_axis):
    new_axes = []
    for axis in Axes.as_nested_list(axes):
        if axis == parallel_axis:
            axis = parallel_axis
        elif isinstance(axis, collections.Iterable):
            # flattened axis
            axis = [parallel_axis if a == parallel_axis else a for a in axis]
        new_axes.append(axis)

    return make_axes(new_axes)


def get_slices(axes, parallel_axis, num_devices):
    new_slices = list()
    for i in range(num_devices):
        slices = list()
        for a in axes:
            s = slice(None)
            if parallel_axis == a:
                remainder = a.length % num_devices
                new_length = a.length // num_devices
                start = i * new_length
                stop = (i + 1) * new_length
                step = 1
                if remainder > 0:
                    if i == (num_devices - 1):
                        stop += remainder
                s = slice(start, stop, step)
            slices.append(s)
        new_slices.append(slices)
    return new_slices


class ResultOp(TensorOp):
    """
    special op for Hetr distributed case, not supported by other transformers
    note: possible deprecation in future (issue #1115)
    """

    def __init__(self, device_id, args, **kwargs):

        super(ResultOp, self).__init__(args=args)
        self.metadata['device_id'] = device_id
        self.axes = args[0].axes
        self.dtype = args[0].dtype


class CommunicationOp(TensorOp):
    """
    Represents a communication op.

    Arguments:
        None
    """

    def __init__(self, node, args=None, axes=None, dtype=None):
        super(CommunicationOp, self).__init__(args=args, axes=axes, dtype=dtype)
        self.metadata['device'] = node.metadata['device']
        self.metadata['device_id'] = node.metadata['device_id']
        self.metadata['transformer'] = node.metadata['transformer']
        self.metadata['host_transformer'] = node.metadata['host_transformer']

    @property
    def is_communication_op(self):
        return True

    @property
    def has_side_effects(self):
        return True


class SendOp(CommunicationOp):
    """
    Represents a send op. Sets args, axes, dtype, and metadata.

    Arguments:
        from_node: The source node.
    """

    def __init__(self, from_node):
        super(SendOp, self).__init__(
            node=from_node,
            args=tuple([from_node]),
            axes=from_node.axes,
            dtype=from_node.dtype)


class RecvOp(CommunicationOp):
    """
    Represents a recv op. Sets args, axes, dtype, and metadata.

    Arguments:
        to_node: The destination node.
        send_node: The send node associated with this recv node.
    """

    def __init__(self, to_node, send_node, fragment_axis=None, fragments=None):
        super(RecvOp, self).__init__(
            node=to_node,
            args=(),
            axes=self.calculate_recv_axes(send_node.axes, fragment_axis, fragments),
            dtype=send_node.dtype)
        self._send_node = send_node
        self.source_id = send_node.metadata['device_id']

    @classmethod
    def calculate_recv_axes(cls, send_axes, fragment_axis, fragments):
        return send_axes

    def send_node(self):
        return self._send_node


class ScatterSendOp(SendOp):
    """
    Represents a scatter send op. Sets destination device ids and slices.

    Arguments:
        from_node: The source node.
        to_node: The destination node.
    """

    def __init__(self, from_node, to_node):
        super(ScatterSendOp, self).__init__(from_node)
        self.to_id = to_node.metadata['device_id']
        self._slices = get_slices(self.axes,
                                  to_node.metadata['parallel'],
                                  len(self.to_id))

    @property
    def slices(self):
        return self._slices


class ScatterRecvOp(RecvOp):
    """
    Represents a scatter recv op.

    Arguments:
        to_node: The destination node.
        send_node: The scatter send node associated with this node.
    """

    def __init__(self, to_node, send_node):
        super(ScatterRecvOp, self).__init__(to_node, send_node,
                                            fragment_axis=to_node.metadata['parallel'],
                                            fragments=len(to_node.metadata['device_id']))


class GatherSendOp(SendOp):
    """
    Represents a gather send op.

    Arguments:
        from_node: The source node.
    """

    def __init__(self, from_node):
        super(GatherSendOp, self).__init__(from_node)


class GatherRecvOp(RecvOp):
    """
    Represents a gather recv op. Sets metadata, source device ids and
    slices.

    Arguments:
        from_node: The source node.
        to_node: The destination node.
        send_node: The gather send node associated with this node.
    """

    def __init__(self, from_node, to_node, send_node):
        super(GatherRecvOp, self).__init__(to_node, send_node,
                                           fragment_axis=from_node.metadata['parallel'],
                                           fragments=len(from_node.metadata['device_id']))
        self.metadata['marker'] = 'gather'
        self.metadata['parallel'] = from_node.metadata['parallel']
        self.from_id = from_node.metadata['device_id']
        # use _slices to avoid serialization
        self._slices = get_slices(self.axes,
                                  self.metadata['parallel'],
                                  len(self.from_id))

    @property
    def slices(self):
        return self._slices

    @property
    def send_nodes(self):
        """
        :return: iterable of send nodes
        """
        from ngraph.transformers.hetr.hetr_utils import get_iterable
        return OrderedSet(i for i in get_iterable(self._send_node))

    @send_nodes.setter
    def send_nodes(self, new_send_nodes):
        self._send_node = new_send_nodes

    def send_node(self):
        # make it work for general traversal in functions (e.g. find_recv())
        return self.send_nodes


class GPUQueueSendOp(MutateInsteadOfCopyWithNewArgsMixin, SendOp):

    def __init__(self, from_node):
        super(GPUQueueSendOp, self).__init__(from_node=from_node)
        self._queue = multiprocessing.Queue()

    @property
    def queue(self):
        return self._queue


class GPUQueueRecvOp(RecvOp):

    def __init__(self, to_node, send_node):
        super(GPUQueueRecvOp, self).__init__(to_node, send_node)
        self._queue = send_node.queue

    @property
    def queue(self):
        return self._queue


class GPUCudaScatterSendOp(MutateInsteadOfCopyWithNewArgsMixin, ScatterSendOp):

    def __init__(self, from_node, to_node):
        super(GPUCudaScatterSendOp, self).__init__(from_node=from_node, to_node=to_node)
        self._shared_queues = [multiprocessing.Queue() for i in to_node.metadata['device_id']]
        self.metadata['parallel'] = to_node.metadata['parallel']

    @property
    def shared_queues(self):
        return self._shared_queues


class GPUCudaScatterRecvOp(ScatterRecvOp):

    def __init__(self, to_node, send_node):
        super(GPUCudaScatterRecvOp, self).__init__(to_node, send_node)
        self.idx = 0
        self._shared_queues = send_node._shared_queues

    @property
    def shared_queues(self):
        return self._shared_queues


class GPUCudaGatherSendOp(MutateInsteadOfCopyWithNewArgsMixin, GatherSendOp):

    def __init__(self, from_node):
        super(GPUCudaGatherSendOp, self).__init__(from_node=from_node)
        self.idx = 0
        self._shared_queues = [multiprocessing.Queue() for i in from_node.metadata['device_id']]
        self.metadata['parallel'] = from_node.metadata['parallel']

    @property
    def shared_queues(self):
        return self._shared_queues


class GPUCudaGatherRecvOp(GatherRecvOp):

    def __init__(self, from_node, to_node, send_node):
        super(GPUCudaGatherRecvOp, self).__init__(from_node, to_node, send_node)
        self._shared_queues = send_node._shared_queues

    @property
    def shared_queues(self):
        return self._shared_queues


class CPUQueueSendOp(MutateInsteadOfCopyWithNewArgsMixin, SendOp):

    def __init__(self, from_node):
        super(CPUQueueSendOp, self).__init__(from_node=from_node)
        self._queue = multiprocessing.Queue()

    @property
    def queue(self):
        return self._queue


class CPUQueueRecvOp(RecvOp):

    def __init__(self, to_node, send_node):
        super(CPUQueueRecvOp, self).__init__(to_node, send_node)
        self._queue = send_node.queue

    @property
    def queue(self):
        return self._queue


class CPUQueueScatterSendOp(MutateInsteadOfCopyWithNewArgsMixin, ScatterSendOp):

    def __init__(self, from_node, to_node):
        super(CPUQueueScatterSendOp, self).__init__(from_node=from_node, to_node=to_node)
        self._shared_queues = [multiprocessing.Queue() for i in to_node.metadata['device_id']]

    @property
    def shared_queues(self):
        return self._shared_queues


class CPUQueueScatterRecvOp(ScatterRecvOp):

    def __init__(self, to_node, send_node):
        super(CPUQueueScatterRecvOp, self).__init__(to_node, send_node)
        self.idx = 0
        self._shared_queues = send_node.shared_queues

    @property
    def shared_queues(self):
        return self._shared_queues


class CPUQueueGatherSendOp(MutateInsteadOfCopyWithNewArgsMixin, GatherSendOp):

    def __init__(self, from_node):
        super(CPUQueueGatherSendOp, self).__init__(from_node=from_node)
        self.idx = 0
        self._shared_queues = [multiprocessing.Queue() for i in from_node.metadata['device_id']]

    @property
    def shared_queues(self):
        return self._shared_queues


class CPUQueueGatherRecvOp(GatherRecvOp):

    def __init__(self, from_node, to_node, send_node):
        super(CPUQueueGatherRecvOp, self).__init__(from_node, to_node, send_node)
        self._shared_queues = send_node.shared_queues

    @property
    def shared_queues(self):
        return self._shared_queues


class AllReduceOp(CommunicationOp):
    """
    Represents an AllReduce op. Sets reduction axes and out axes.
    TODO: revisit the need for reduction_axes and out_axes in HeTr.

    Arguments:
        x: The input node.
        reduction_axes: The reduction axes.
        out_axes: The output axes.
        dtype: The data type.
    """
    def __init__(self, x, reduction_axes=None, out_axes=None, dtype=None, func=None, **kwargs):
        reduction_axes, out_axes = compute_reduction_axes(x, reduction_axes, out_axes)
        self.reduction_axes = reduction_axes
        super(AllReduceOp, self).__init__(node=x, args=(x,), axes=out_axes, dtype=dtype, **kwargs)
        self.reduce_func = func
        if (self.reduce_func == 'mean' or self.reduce_func == 'sum') is False:
            raise RuntimeError(
                'Reduce function {} is not supported!'.format(self.reduce_func))


class CPUQueueAllReduceOp(MutateInsteadOfCopyWithNewArgsMixin, AllReduceOp):
    """
    Represents CPU-based queue implementation for AllReduce op. Sets reduction function and creates
    shared queues.

    Arguments:
        x: The input node.
        func: The reduction function, e.g. 'sum', 'mean'.
    """
    def __init__(self, input_node, func=None):
        super(CPUQueueAllReduceOp, self).__init__(x=input_node,
                                                  out_axes=input_node.axes,
                                                  dtype=input_node.dtype,
                                                  func=func)
        self.idx = 0
        self._shared_queues = [multiprocessing.Queue() for i in input_node.metadata['device_id']]

    @property
    def shared_queues(self):
        return self._shared_queues


class GPUCudaAllReduceOp(MutateInsteadOfCopyWithNewArgsMixin, AllReduceOp):
    """
    Represents GPU implementation for AllReduce op. Sets reduction function and creates
    shared queues.

    Arguments:
        x: The input node.
        func: The reduction function, e.g. 'sum', 'mean'.
    """
    def __init__(self, input_node, func=None):
        super(GPUCudaAllReduceOp, self).__init__(x=input_node,
                                                 out_axes=input_node.axes,
                                                 dtype=input_node.dtype,
                                                 func=func)
        self.idx = 0
        self.device_ids = input_node.metadata['device_id']
        self._shared_queues = \
            {i: multiprocessing.Queue() for i in input_node.metadata['device_id']}

    @property
    def shared_queues(self):
        return self._shared_queues


class BroadcastSendOp(SendOp):
    """
    Represents a broadcat send op. Sets destination device ids.

    Arguments:
        from_node: The source node.
        to_node: The destination node.
    """

    def __init__(self, from_node, to_node):
        super(BroadcastSendOp, self).__init__(from_node)
        self.to_id = to_node.metadata['device_id']


class BroadcastRecvOp(RecvOp):
    """
    Represents a broadcast recv op.

    Arguments:
        to_node: The destination node.
        send_node: The broadcast send node associated with this node.
    """

    def __init__(self, to_node, send_node):
        super(BroadcastRecvOp, self).__init__(to_node, send_node)


class CPUQueueBroadcastSendOp(BroadcastSendOp):
    """
    Represents CPU-based queue implementation for BroadcastSend op.
    Creates shared queues.
    """
    def __init__(self, from_node, to_node):
        super(CPUQueueBroadcastSendOp, self).__init__(from_node, to_node)
        self._shared_queues = [multiprocessing.Queue() for i in to_node.metadata['device_id']]

    @property
    def shared_queues(self):
        return self._shared_queues


class CPUQueueBroadcastRecvOp(BroadcastRecvOp):
    """
    Represents CPU-based queue implementation for BroadcastRecv op.
    Creates shared queues.
    """
    def __init__(self, to_node, send_node):
        super(CPUQueueBroadcastRecvOp, self).__init__(to_node, send_node)
        self.idx = 0
        self._shared_queues = send_node.shared_queues

    @property
    def shared_queues(self):
        return self._shared_queues
