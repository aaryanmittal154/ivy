# global
import jax.numpy as jnp
from typing import Union, Tuple, Optional, List

# local
from ivy.functional.backends.jax import JaxArray


def all(
    x: JaxArray,
    axis: Optional[Union[int, Tuple[int], List[int]]] = None,
    keepdims: bool = False,
) -> JaxArray:
    ret = jnp.all(x, axis, keepdims=keepdims)
    return ret


def any(
    x: JaxArray,
    axis: Optional[Union[int, Tuple[int], List[int]]] = None,
    keepdims: bool = False,
) -> JaxArray:
    ret = jnp.any(x, axis, keepdims=keepdims)
    return ret
