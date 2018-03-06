import pytest
import numpy as np
import neon as ng
from neon.frontends.neon import Linear, ConvBase, Recurrent, BatchNorm, Layer, LookupTable, LSTM


dummy_init = lambda axes: np.ones(axes.lengths)


# TODO: Move the following *_size fixtures to conftest.py and refactor other tests to use them
@pytest.fixture(params=[32])
def batch_size(request):
    return request.param


@pytest.fixture(params=[5])
def sequence_length(request):
    return request.param


@pytest.fixture(params=[4, 32])
def input_size(request):
    return request.param


@pytest.fixture(params=[10])
def output_size(request):
    return request.param


def test_inference_reuse_linear(input_placeholder):

    layer = Linear(dummy_init, 10)
    layer(input_placeholder)
    train_params = (layer.W,)
    with Layer.inference_mode_on():
        layer(input_placeholder)
        inference_params = (layer.W,)

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param


def test_inference_reuse_batch_norm(input_placeholder):

    layer = BatchNorm()
    layer(input_placeholder)
    train_params = (layer.gamma, layer.beta)
    with Layer.inference_mode_on():
        layer(input_placeholder)
        inference_params = (layer.gamma, layer.beta)

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param


def test_inference_reuse_conv(conv_input_placeholder):

    fshape = {k: 1 for k in "DHWK"}
    dilation = {"dil_{}".format(k): 1 for k in "DHW"}
    padding = {"pad_{}".format(k): 0 for k in "DHW"}
    strides = {"str_{}".format(k): 1 for k in "DHW"}
    layer = ConvBase(fshape,
                     dummy_init,
                     dilation=dilation,
                     strides=strides,
                     padding=padding)

    layer(conv_input_placeholder)
    train_params = (layer.W,)
    with Layer.inference_mode_on():
        layer(conv_input_placeholder)
        inference_params = (layer.W,)

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param


def test_inference_reuse_recurrent(recurrent_input):

    layer = Recurrent(10, dummy_init, activation=lambda x: x)
    layer(recurrent_input)
    train_params = (layer.W_input, layer.W_recur)
    with Layer.inference_mode_on():
        layer(recurrent_input)
        inference_params = (layer.W_input, layer.W_recur)

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param


def test_inference_reuse_lstm(recurrent_input):

    layer = LSTM(10, dummy_init, activation=lambda x: x)
    layer(recurrent_input)
    train_params = (layer.W_input["f"], layer.W_recur["f"])
    with Layer.inference_mode_on():
        layer(recurrent_input)
        inference_params = (layer.W_input["f"], layer.W_recur["f"])

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param


def test_inference_reuse_lut(recurrent_axis, batch_axis):

    seq_input = ng.placeholder(axes=[recurrent_axis, batch_axis])
    layer = LookupTable(20, 10, dummy_init)
    layer(seq_input)
    train_params = (layer.W, )
    with Layer.inference_mode_on():
        layer(seq_input)
        inference_params = (layer.W, )

    for train_param, inference_param in zip(train_params, inference_params):
        assert train_param is inference_param
