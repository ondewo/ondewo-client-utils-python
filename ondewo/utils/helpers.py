# Copyright 2020-2024 ONDEWO GmbH
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

"""Helper utilities for building protobuf Structs and for recursive attribute access."""

import functools
from typing import (
    Any,
    Dict,
)

from google.protobuf.struct_pb2 import Struct


def get_struct_from_dict(d: Dict) -> Struct:  # type: ignore
    """
    Create a protobuf Struct from a dictionary.

    Args:
        d (Dict):
            The dictionary whose key/value pairs populate the resulting ``Struct``.
            May be ``None``, in which case an empty ``Struct`` is returned.

    Returns:
        Struct:
            A protobuf ``Struct`` populated with the entries of ``d`` (empty when
            ``d`` is ``None``).

    Raises:
        AssertionError:
            If ``d`` is neither a ``dict`` nor ``None``.
    """
    assert isinstance(d, dict) or d is None, "parameter must be a dict or None"

    result: Struct = Struct()  # type: ignore

    if d is not None:
        for key, value in d.items():
            result[key] = value  # type: ignore

    return result


def get_attr_recursive(obj: Any, attr: str, *args: Any) -> Any:
    """
    Recursively read a (possibly nested) attribute from an object.

    from
    https://stackoverflow.com/questions/31174295/getattr-and-setattr-on-nested-subobjects-chained-properties

    Args:
        obj (Any):
            The object to read the attribute from.
        attr (str):
            The dot-separated attribute path, e.g. ``"a.b.c"``.
        *args (Any):
            An optional single default value returned when an attribute along the
            path does not exist.

    Returns:
        Any:
            The value of the nested attribute, or the provided default when given.
    """
    return functools.reduce(lambda obj_, attr_: getattr(obj_, attr_, *args), [obj] + attr.split("."))


def set_attr_recursive(obj: Any, attr: str, value: Any) -> None:
    """
    Recursively set a (possibly nested) attribute on an object.

    from
    https://stackoverflow.com/questions/31174295/getattr-and-setattr-on-nested-subobjects-chained-properties

    Args:
        obj (Any):
            The object on which to set the attribute.
        attr (str):
            The dot-separated attribute path, e.g. ``"a.b.c"``.
        value (Any):
            The value to assign to the (nested) attribute.

    Returns:
        None
    """
    pre, _, post = attr.rpartition(".")
    return setattr(get_attr_recursive(obj, pre) if pre else obj, post, value)
