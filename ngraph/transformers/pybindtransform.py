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
import collections
import numpy as np
from ngraph.transformers.base import Computation
from ngraph.transformers.base import Transformer
from ngraph.op_graph.op_graph import Op, TensorValueOp, SequentialOp
from orderedset import OrderedSet
from ngraph.transformers.passes.pybindwrapperpass \
    import PybindWrapperGenerator, PybindScopePass
import pyngraph.util as util
from pyngraph import Type, Function
from pyngraph.runtime import Manager


class PybindComputation(Computation):

    def __init__(self, transformer, computation_op, **kwargs):
        super(PybindComputation, self).__init__(transformer, computation_op, **kwargs)
        self.transformer = transformer
        self.computation_op = computation_op
        self.parameter_list = []
        self.result_primary_tensor_view_list = []
        self.ngraph_op_result_list = []
        self.return_result_list = dict()

        self.ngraph_cpp_ops = dict()
        self.variables_cpp_op = dict()
        self.variables = []
        self.op_rank = dict()
        self.rank = 0
        self.scopevisited = set()
        self.scopemark = dict()
        self.seqcount = 0
        self.parcount = 0

        self.create_function()
        self.initialize_cpp_backend(self.computation_op.returns, *self.computation_op.parameters)

    def __call__(self, *args, **kwargs):
        """
        This builds a primary_tensor_view from the *args and
        results to pass the ([parameter_list], [return_list])
        to ngraph++ call_frame to compute the results.

        :param args:
        :param kwargs:
        :return: [list of computed results]
        """
        param_primary_tensor_view_list = []
        args = self.unpack_args_or_feed_dict(args, kwargs)
        self.get_ngraph_cpp_param_list(param_primary_tensor_view_list, *args)

        for index, result in enumerate(self.result_primary_tensor_view_list):
            result_op = self.ngraph_op_result_list[index]
            element_size = self.get_element_size(result_op)
            shape = list(result_op.axes.lengths)
            # TODO - need to define dtype of numpy array's for results based on result.dtype
            result_arr = np.empty(shape, dtype=np.float32)
            result.write(util.numpy_to_c(result_arr), 0, int(element_size))
            self.return_result_list[result_op] = result_arr

        self.cf.call(param_primary_tensor_view_list, self.result_primary_tensor_view_list)

        # now read the values from the computed result
        for index, result in enumerate(self.result_primary_tensor_view_list):
            result_op = self.ngraph_op_result_list[index]
            element_size = self.get_element_size(result_op)
            result.read(util.numpy_to_c(self.return_result_list[result_op]), 0, int(element_size))

        # determine whether the value to be retruned is a list, dict or an op.
        if isinstance(self.computation_op.returns, Op):
            return self.return_result_list[self.computation_op.returns]
        elif isinstance(self.computation_op.returns, (collections.Sequence, OrderedSet)):
            return tuple(self.return_result_list[op] for op in self.computation_op.returns)
        elif isinstance(self.computation_op.returns, collections.Set):
            return self.return_result_list
        else:
            return None

    def lookup_cpp_op(self, op):
        if isinstance(op, TensorValueOp):
            if not op.tensor.is_constant:
                if op.tensor in self.variables_cpp_op:
                    if self.scopemark[op] == self.variables_cpp_op[op.tensor][0]:
                        if self.op_rank[op] > self.op_rank[op.tensor]:
                            return self.variables_cpp_op[op.tensor][1]
        """
            if op.tensor in self.ngraph_cpp_ops:
                return self.ngraph_cpp_ops[op.tensor]
        else:
            if op in self.ngraph_cpp_ops:
                return self.ngraph_cpp_ops[op]
        """
        if op.tensor in self.ngraph_cpp_ops:
            return self.ngraph_cpp_ops[op.tensor]
        return None

    def register_cpp_op(self, op):
        pass

    def register_forward_variable(self, op):
        pass

    def set_op_rank(self, op):
        self.op_rank[op] = self.rank
        # print(op.name + " rank is " + str(self.rank))
        self.rank += 1

    def create_function(self):
        computation = self.computation_op
        self.transformer.graph_passes = []
        self.transformer.graph_passes += [PybindWrapperGenerator(self.transformer, self)]
        self.custom_passes = []
        self.custom_passes += [PybindScopePass(self)]
        computation_op_list = OrderedSet()
        if isinstance(computation.returns, collections.Container):
            computation_op_list.update(list(computation.returns))
        elif isinstance(computation.returns, Op):
            computation_op_list.update(list([computation.returns]))
        for custom_pass in self.custom_passes:
            custom_pass(computation_op_list)
        self.transformer.run_registered_graph_passes(computation_op_list)

    def initialize_cpp_backend(self, results, *parameters):
        """
        Passes result's primary_tensor_view to the ngraph++ Function to generate ngraph ++ op graph
        allocates backend and initilizes ngraph++ call frame.

        :param results:
        :param parameters:
        :return:
        """
        # define the result type

        # TODO define element type based on result.dtype instead of defaulting to f32
        self.result_element_type = Type.f32
        result_nodes_list = []
        result_node_to_shape = dict()

        if isinstance(results, Op):
            results = [results]

        for node in results:
            if isinstance(node, SequentialOp):
                node = node.ops[-1]
            self.ngraph_op_result_list.append(node)
            result_node_to_shape[node] = list(node.axes.lengths)
            result_nodes_list.append(self.ngraph_cpp_ops[node])

        # Add additional results (updated variable)
        for variable in self.variables_cpp_op:
            node = self.variables_cpp_op[variable][2]
            self.ngraph_op_result_list.append(node)
            result_node_to_shape[node] = list(node.axes.lengths)
            result_nodes_list.append(self.variables_cpp_op[variable][1])

        # use the ngraph_cpp_op dict to built the parameter list for c++ backend
        for place_holders in parameters:
            self.parameter_list.append(
                self.ngraph_cpp_ops[place_holders.tensor])

        # Add additional parameters (variables)
        for variable in self.variables_cpp_op:
            self.parameter_list.append(
                self.ngraph_cpp_ops[variable.tensor])

        # TODO - what's the role of the string argument? for now just passing 'test'
        self.function = Function(
            result_nodes_list,
            self.parameter_list,
            'test')

        self.manager = Manager.get(self.transformer.ngraph_backend)
        self.external = self.manager.compile(self.function)
        self.backend = self.manager.allocate_backend()
        self.cf = self.backend.make_call_frame(self.external)
        # create the primary_tensor_view for result's using the ngraph++ initilized backend
        for node in results:
            if isinstance(node, SequentialOp):
                node = node.ops[-1]
            self.result_primary_tensor_view_list.append(
                self.backend.make_primary_tensor_view(
                    self.result_element_type, result_node_to_shape[node]))

    def get_ngraph_cpp_param_list(self, param_primary_tensor_view_list, *args):
        """
        Builds a list of ngraph++ primary_tensor_view from ngraph *parameters list

        :param args:
        :return:
        """
        # get the primary tensor_view for all the *parameters passed from the user
        for op in self.computation_op.parameters:
            # TODO define element type based on op.dtype instead of deafulting to flaot32
            param_element_type = Type.f32
            param_primary_tensor_view_list.append(
                self.backend.make_primary_tensor_view(
                    param_element_type, list(
                        op.axes.lengths)))

        # use c++ backend write method to pass the tensor values
        for index, op in enumerate(self.computation_op.parameters):
            element_size = self.get_element_size(op)
            # TODO - need to define dtype of numpy array's for *params based on op.dtype
            param_primary_tensor_view_list[index].write(util.numpy_to_c(
                np.array(args[index], dtype=np.float32)), 0, int(element_size))

    def get_element_size(self, op):
        """
        computes the size of the op in bytes

        :param op:
        :return: int, op size in bytes
        """
        item_size = op.tensor.dtype.itemsize
        element_size = (np.prod(op.axes.lengths)) * item_size
        return element_size


class FunctionTransformer(Transformer):
    def __init__(self, **kwargs):
        super(FunctionTransformer, self).__init__(**kwargs)
        self.computations = OrderedSet()

    def run_registered_graph_passes(self, ops, **kwargs):
        for graph_pass in self.graph_passes:
            graph_pass.wrapped_do_pass(ops=ops, **kwargs)
        return ops

    # TODO: update the following methods
    def initialize_allocations(self):
        """
        Inititializes allocation caches.

        """
        self.op_tensors = dict()
        self.op_tensor_views = dict()
        self.device_buffers = OrderedSet()

    def host_to_device(self, computation, parameters, args):
        """
        Copy args to parameters in computation.

        Args:
            computation: The computation.
            parameters: Parameters of the computation.
            args: Values for the parameters.

        """
        for param, arg in zip(parameters, args):
            self.get_op_tensor_view(param)[...] = arg

    def device_to_host(self, computation, op, tensor=None):
        """
        Copy a computation result from the device back to the host.

        Args:
            computation: The computation.
            op: The op associated with the value.
            tensor: Optional tensor for returned value.

        Returns:
            The value of op.

        """
        if self.has_op_tensor(op):
            return self.get_op_tensor_view(op).get(tensor)

    def get_tensor_view_value(self, op, host_tensor=None):
        """
        Returns the contents of the tensor view for op.

        Args:
            op: The computation graph op.
            host_tensor: Optional tensor to copy value into.

        Returns:
            A NumPy tensor with the elements associated with op.

        """
        return self.get_op_tensor_view(op).get(host_tensor)

    @property
    def use_exop(self):
        """

        Returns: True if this transformer uses the execution graph.

        """
        return False

class PybindTransformer(FunctionTransformer):
    """
    Transformer for executing graphs to call the pybind wrapper of the ngraph c++.

    """
    """
    transformer_name = "pybind_translator"
    """

    def __init__(self, **kwargs):
        """
        if "backend" in kwargs:
            self.ngraph_backend = kwargs.pop("backend")
        else:
            raise AssertionError("No backend info found, please provide the backend info \
            while creating the transformer_factory()")
        """
        super(PybindTransformer, self).__init__(**kwargs)

    def make_computation(self, computation):
        """
        creates PybindComputation object

        :param computation:
        :return: instance of PybindComputation()
        """
        pybind_comp = PybindComputation(self, computation)
        return pybind_comp

    def initialize(self):
        pass

    def device_buffer_storage(self, bytes, dtype, name):
        pass

    def start_transform_allocate(self):
        pass

    def transform_allocate_ops(self, all_ops):
        pass

    def finish_transform_allocate(self):
        pass

    def transform_ordered_ops(self, ordered_ops, name):
        pass

    def finish_transform(self):
        pass

    def allocate_storage(self):
        pass

    def add_initialization_ops(self, ops):
        pass

    def state_initializations(self, states):
        pass


class PybindCPUTransformer(PybindTransformer):
    """
    Transformer for ngraph c++ with cpu backend.

    """
    transformer_name = "ngcpu"

    def __init__(self, **kwargs):
        self.ngraph_backend = "CPU"
        super(PybindCPUTransformer, self).__init__(**kwargs)


class PybindINTERPRETERTransformer(PybindTransformer):
    """
    Transformer for ngraph c++ with interpreter backend.

    """
    transformer_name = "nginterp"

    def __init__(self, **kwargs):
        self.ngraph_backend = "INTERPRETER"
        super(PybindINTERPRETERTransformer, self).__init__(**kwargs)


class PybindGPUTransformer(PybindTransformer):
    """
    Transformer for ngraph c++ with interpreter backend.

    """
    transformer_name = "nggpu"

    def __init__(self, **kwargs):
        self.ngraph_backend = "GPU"
        super(PybindGPUTransformer, self).__init__(**kwargs)
