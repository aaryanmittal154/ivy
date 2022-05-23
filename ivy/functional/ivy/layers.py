"""Collection of Ivy neural network layers in functional form."""

# global
import numpy as np
from typing import Union

# local
import ivy
from ivy.framework_handler import current_framework as _cur_framework


# Extra #
# ------#


# Linear #


def linear(x, weight, bias=None):
    """Applies a linear transformation to the incoming data: y = x * t(weight) + bias.
    The operation also supports batching of the weight matrices. This is useful if a
    batch of different network parameters are to be represented.

    Parameters
    ----------
    x
        The input x compute linear transformation on.
        *[outer_batch_shape,inner_batch_shape,in_features]*
    weight
        The weight matrix. *[outer_batch_shape,out_features,in_features]*
    bias
        The bias vector, default is None. *[outer_batch_shape,out_features]*

    Returns
    -------
    ret
        Result array of the linear transformation.
        *[outer_batch_shape,inner_batch_shape,out_features]*

    """
    outer_batch_shape = list(weight.shape[:-2])
    num_outer_batch_dims = len(outer_batch_shape)
    inner_batch_shape = list(x.shape[num_outer_batch_dims:-1])
    num_inner_batch_dims = len(inner_batch_shape)
    num_out_feats, num_in_feats = list(weight.shape[-2:])

    # OBS x IBS x OF
    y = ivy.matmul(
        x,
        ivy.swapaxes(
            ivy.reshape(
                weight,
                outer_batch_shape
                + [1] * max(num_inner_batch_dims - 1, 0)
                + [num_out_feats, num_in_feats],
            ),
            -1,
            -2,
        ),
    )

    if ivy.exists(bias):

        # OBS x [1]*len(IBS) x OF
        bias_broadcast = ivy.reshape(
            bias, outer_batch_shape + [1] * num_inner_batch_dims + [num_out_feats]
        )

        # OBS x IBS x OF
        y = y + bias_broadcast

    # OBS x IBS x OF
    return y


# Dropout #


def dropout(x, prob, scale=True):
    """Randomly zeroes some of the elements of the input tensor with probability p using
    samples from a Bernoull distribution.

    Parameters
    ----------
    x
        The input array x to perform dropout on.
    prob
        The probability of zeroing out each array element.
    scale
        Whether to scale the output by 1/(1-prob), default is True.

    Returns
    -------
    ret
        Result array of the linear transformation. *[N,∗,out_features]*

    """
    # noinspection PyUnresolvedReferences
    x = ivy.where(
        ivy.random_uniform(shape=x.shape, device=ivy.dev(x)) < prob,
        ivy.zeros_like(x),
        x,
    )
    if scale:
        x *= 1 / (1 - prob)
    return x


# Attention #


def scaled_dot_product_attention(q, k, v, scale, mask=None):
    """Applies scaled dot product attention to inputs x using optional mask.

    Parameters
    ----------
    q
        The queries *[batch_shape,num_queries,feat_dim]*.
    k
        The keys *[batch_shape,num_keys,feat_dim]*.
    v
        The values *[batch_shape,num_keys,feat_dim]*.
    scale
        The value by which to scale the query-key pairs before softmax.
    mask
        The mask to apply to the query-key values. Default is None.
        *[batch_shape,num_queries,num_keys]*

    Returns
    -------
    ret
        The output following application of scaled dot-product attention.
        *[batch_shape,num_queries,feat_dim]*

    """
    # BS x Q x K
    sim = ivy.einsum("... q f, ... k f -> ... q k", q, k) * scale

    if ivy.exists(mask):

        # BS x Q x K
        sim = ivy.where(
            ivy.logical_not(mask),
            -ivy.ones_like(sim) * np.finfo(np.dtype(ivy.dtype(sim))).max,
            sim,
        )

    # BS x Q x K
    attn = ivy.softmax(sim, -1)

    # BS x Q x F
    return ivy.einsum("... q k, ... k f -> ... q f", attn, v)


def multi_head_attention(
    x,
    scale,
    num_heads,
    context=None,
    mask=None,
    to_q_fn=None,
    to_kv_fn=None,
    to_out_fn=None,
    to_q_v=None,
    to_kv_v=None,
    to_out_v=None,
):
    """Applies multi-head attention to inputs x.

    Parameters
    ----------
    x
        The array to determine the queries from *[batch_shape,num_queries,x_feat_dim]*.
    scale
        The value by which to scale the query-key similarity measure before softmax.
    num_heads
        The number of attention heads to use.
    context
        The array to determine the keys and values from. Default is None.
        *[batch_shape,num_keys,cont_feat_dim]*.
    mask
        The mask to apply to the query-key values. Default is None.
        *[batch_shape,num_queries,num_keys]*
    to_q_fn
        The function to compute queries from input x, returning queries
        *[batch_shape,num_queries,numheads×feat_dim]*. (Default value = None)
    to_kv_fn
        The function to compute keys and values from the context. (Default value = None)
    to_out_fn
        The function to compute the output from the scaled dot-product attention.
        (Default value = None)
    to_q_v
        The variables for function to_q_fn. Default is None.
    to_kv_v
        The variables for function to_kv_fn. Default is None.
    to_out_v
        The variables for function to_out_fn. Default is None.

    Returns
    -------
    ret
        The output following application of multi-head attention.
        *[batch_shape,num_queries,out_feat_dim]*

    """
    # BS x Q x (HxF)
    q = to_q_fn(x, v=to_q_v) if ivy.exists(to_q_fn) else x

    # BS x K x CF
    context = ivy.default(context, x)

    # BS x K x (2xHxF)    or    BS x K x (HxF),  BS x K x (HxF)
    kv = (
        to_kv_fn(context, v=to_kv_v)
        if ivy.exists(to_kv_fn)
        else ivy.split(context, 2, -1)
    )

    # BS x K x (HxF),  BS x K x (HxF)
    if isinstance(kv, tuple):
        k, v = kv
    else:
        k, v = ivy.split(kv, 2, -1)

    # BS x H x Q x F,  BS x H x K x F,  BS x H x K x F
    q, k, v = map(
        lambda t: ivy.einops_rearrange(t, "... n (h f) -> ... h n f", h=num_heads),
        (q, k, v),
    )

    # BS x H x Q x K
    if ivy.exists(mask):
        mask = ivy.einops_repeat(mask, "... q k -> ... h q k", h=num_heads)

    # BS x H x Q x F
    sdpa = scaled_dot_product_attention(q, k, v, scale, mask)

    # BS x Q x (HxF)
    sdpa = ivy.einops_rearrange(sdpa, "... h q f -> ... q (h f)")

    # BS x Q x OF
    return to_out_fn(sdpa, v=to_out_v) if ivy.exists(to_out_fn) else sdpa


# Convolutions #


def conv1d(
    x: Union[ivy.Array, ivy.NativeArray],
    filters: Union[ivy.Array, ivy.NativeArray],
    strides: int,
    padding: str,
    data_format: str = "NWC",
    dilations: int = 1,
) -> ivy.Array:
    """Computes a 1-D convolution given 3-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,w,d_in]*.
    filters
        Convolution filters *[fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    data_format
        NWC" or "NCW". Defaults to "NWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the convolution operation.

    Examples
    --------
    >>> x = ivy.asarray([[[0.], [3.], [0.]]]) #NWC
    >>> filters = ivy.array([[[0.]], [[1.]], [[0.]]]) #WIO
    >>> result = ivy.conv1d(x, filters, (1,), 'SAME', 'NWC', (1,))
    >>> print(result)
    ivy.array([[[0.], [3.], [0.]]])

    """
    return _cur_framework(x).conv1d(
        x, filters, strides, padding, data_format, dilations
    )


def conv1d_transpose(
    x, filters, strides, padding, output_shape=None, data_format="NWC", dilations=1
):
    """Computes a 1-D transpose convolution given 3-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,w,d_in]*.
    filters
        Convolution filters *[fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    output_shape
        Shape of the output (Default value = None)
    data_format
        NWC" or "NCW". Defaults to "NWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the transpose convolution operation.

    """
    return _cur_framework(x).conv1d_transpose(
        x, filters, strides, padding, output_shape, data_format, dilations
    )


def conv2d(x, filters, strides, padding, data_format="NHWC", dilations=1):
    """Computes a 2-D convolution given 4-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,h,w,d_in]*.
    filters
        Convolution filters *[fh,fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    data_format
        NHWC" or "NCHW". Defaults to "NHWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the convolution operation.

    """
    return _cur_framework(x).conv2d(
        x, filters, strides, padding, data_format, dilations
    )


def conv2d_transpose(
    x, filters, strides, padding, output_shape=None, data_format="NHWC", dilations=1
):
    """Computes a 2-D transpose convolution given 4-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,h,w,d_in]*.
    filters
        Convolution filters *[fh,fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    output_shape
        Shape of the output (Default value = None)
    data_format
        NHWC" or "NCHW". Defaults to "NHWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the transpose convolution operation.

    """
    return _cur_framework(x).conv2d_transpose(
        x, filters, strides, padding, output_shape, data_format, dilations
    )


def depthwise_conv2d(x, filters, strides, padding, data_format="NHWC", dilations=1):
    """Computes a 2-D depthwise convolution given 4-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,h,w,d]*.
    filters
        Convolution filters *[fh,fw,d]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    data_format
        NHWC" or "NCHW". Defaults to "NHWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the convolution operation.

    """
    return _cur_framework(x).depthwise_conv2d(
        x, filters, strides, padding, data_format, dilations
    )


# noinspection PyDefaultArgument
def conv3d(
    x: Union[ivy.Array, ivy.NativeArray],
    filters: Union[ivy.Array, ivy.NativeArray],
    strides: int,
    padding: str,
    data_format: str = "NDHWC",
    dilations: int = 1,
) -> ivy.Array:
    """Computes a 3-D convolution given 5-D input x and filters arrays.

    Parameters
    ----------
    x
        Input volume *[batch_size,d,h,w,d_in]*.
    filters
        Convolution filters *[fd,fh,fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    data_format
        NDHWC" or "NCDHW". Defaults to "NDHWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the convolution operation.

    Examples
    --------
    >>> x1 = [[[1.],[2.]],[[1.],[2.]],[[1.],[2.]]]
    >>> x2 = [[[3.],[4.]],[[3.],[4.]],[[3.],[4.]]]
    >>> x = ivy.array([[x1,x2]]) #NDHWC
    >>> filters = ivy.array([[[[[1]],[[0.]]]]]) #DHWIO
    >>> result = ivy.conv3d( x, filters, 1, 'VALID',"NDHWC", 1)
    >>> print(result)
    ivy.array([[
        [
            [[1.]],[[1.]],[[1.]]
        ],
        [
            [[3.]],[[3.]],[[3.]]
        ]
            ]])

    """
    return _cur_framework(x).conv3d(
        x, filters, strides, padding, data_format, dilations
    )


def conv3d_transpose(
    x, filters, strides, padding, output_shape=None, data_format="NDHWC", dilations=1
):
    """Computes a 3-D transpose convolution given 5-D input x and filters arrays.

    Parameters
    ----------
    x
        Input image *[batch_size,d,h,w,d_in]*.
    filters
        Convolution filters *[fd,fh,fw,d_in,d_out]*.
    strides
        The stride of the sliding window for each dimension of input.
    padding
        SAME" or "VALID" indicating the algorithm, or list indicating the per-dimension
        paddings.
    output_shape
        Shape of the output (Default value = None)
    data_format
        NDHWC" or "NCDHW". Defaults to "NDHWC".
    dilations
        The dilation factor for each dimension of input. (Default value = 1)

    Returns
    -------
    ret
        The result of the transpose convolution operation.

    """
    return _cur_framework(x).conv3d_transpose(
        x, filters, strides, padding, output_shape, data_format, dilations
    )


# LSTM #


def lstm_update(
    x, init_h, init_c, kernel, recurrent_kernel, bias=None, recurrent_bias=None
):
    """Perform long-short term memory update by unrolling time dimension of input array.

    Parameters
    ----------
    x
        input tensor of LSTM layer *[batch_shape, t, in]*.
    init_h
        initial state tensor for the cell output *[batch_shape, out]*.
    init_c
        initial state tensor for the cell hidden state *[batch_shape, out]*.
    kernel
        weights for cell kernel *[in, 4 x out]*.
    recurrent_kernel
        weights for cell recurrent kernel *[out, 4 x out]*.
    bias
        bias for cell kernel *[4 x out]*. (Default value = None)
    recurrent_bias
        bias for cell recurrent kernel *[4 x out]*. (Default value = None)

    Returns
    -------
    ret
        hidden state for all timesteps *[batch_shape,t,out]* and cell state for last
        timestep *[batch_shape,out]*

    """
    # get shapes
    x_shape = list(x.shape)
    batch_shape = x_shape[:-2]
    timesteps = x_shape[-2]
    input_channels = x_shape[-1]
    x_flat = ivy.reshape(x, (-1, input_channels))

    # input kernel
    Wi = kernel
    Wi_x = ivy.reshape(
        ivy.matmul(x_flat, Wi) + (bias if bias is not None else 0),
        batch_shape + [timesteps, -1],
    )
    Wii_x, Wif_x, Wig_x, Wio_x = ivy.split(Wi_x, 4, -1)

    # recurrent kernel
    Wh = recurrent_kernel

    # lstm states
    ht = init_h
    ct = init_c

    # lstm outputs
    hts_list = list()

    # unrolled time dimension with lstm steps
    for Wii_xt, Wif_xt, Wig_xt, Wio_xt in zip(
        ivy.unstack(Wii_x, axis=-2),
        ivy.unstack(Wif_x, axis=-2),
        ivy.unstack(Wig_x, axis=-2),
        ivy.unstack(Wio_x, axis=-2),
    ):
        htm1 = ht
        ctm1 = ct

        Wh_htm1 = ivy.matmul(htm1, Wh) + (
            recurrent_bias if recurrent_bias is not None else 0
        )
        Whi_htm1, Whf_htm1, Whg_htm1, Who_htm1 = ivy.split(
            Wh_htm1, num_or_size_splits=4, axis=-1
        )

        it = ivy.sigmoid(Wii_xt + Whi_htm1)
        ft = ivy.sigmoid(Wif_xt + Whf_htm1)
        gt = ivy.tanh(Wig_xt + Whg_htm1)
        ot = ivy.sigmoid(Wio_xt + Who_htm1)
        ct = ft * ctm1 + it * gt
        ht = ot * ivy.tanh(ct)

        hts_list.append(ivy.expand_dims(ht, -2))

    return ivy.concat(hts_list, -2), ct
