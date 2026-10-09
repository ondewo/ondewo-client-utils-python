# Copyright 2020-2026 ONDEWO GmbH
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

"""Unit tests for the helper functions in ``ondewo.utils.helpers``.

Covers ``get_struct_from_dict``, ``get_attr_recursive`` and ``set_attr_recursive``.
"""

from types import SimpleNamespace

import pytest
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct

from ondewo.utils.helpers import (
    get_attr_recursive,
    get_struct_from_dict,
    set_attr_recursive,
)


class TestGetStructFromDict:
    """Test suite for :func:`ondewo.utils.helpers.get_struct_from_dict`."""

    def test_returns_struct_with_values(self) -> None:
        """Verify that a populated dict is converted into a matching protobuf Struct."""
        struct: Struct = get_struct_from_dict({"a": "b", "n": 1, "flag": True})
        assert isinstance(struct, Struct)
        assert struct["a"] == "b"
        assert struct["n"] == 1
        assert struct["flag"] is True

    def test_none_returns_empty_struct(self) -> None:
        """Verify that ``None`` produces an empty protobuf Struct."""
        struct: Struct = get_struct_from_dict(None)  # type: ignore[arg-type]
        assert isinstance(struct, Struct)
        assert len(struct.fields) == 0

    def test_empty_dict_returns_empty_struct(self) -> None:
        """Verify that an empty dict produces an empty protobuf Struct."""
        struct: Struct = get_struct_from_dict({})
        assert len(struct.fields) == 0

    def test_non_dict_raises_type_error(self) -> None:
        """Verify a non-dict, non-None argument raises ``TypeError`` naming the type (survives ``-O``)."""
        with pytest.raises(TypeError, match="got str"):
            get_struct_from_dict("not-a-dict")  # type: ignore[arg-type]

    def test_a_non_str_key_raises_type_error(self) -> None:
        """Pin protobuf's refusal of a non-``str`` key (a ``Struct`` is keyed by text)."""
        with pytest.raises(TypeError):
            get_struct_from_dict({1: "a"})  # type: ignore[dict-item]

    def test_a_bytes_value_raises_value_error(self) -> None:
        """Pin protobuf's refusal of a value JSON has no type for, such as ``bytes``."""
        with pytest.raises(ValueError, match="Unexpected type"):
            get_struct_from_dict({"b": b"x"})

    def test_nested_values_are_converted(self) -> None:
        """Verify nested dict and list values become nested ``Struct`` / ``ListValue`` entries."""
        struct: Struct = get_struct_from_dict({"outer": {"inner": 1.5}, "items": ["a", 2, None]})
        assert MessageToDict(struct) == {"outer": {"inner": 1.5}, "items": ["a", 2.0, None]}


class TestGetAttrRecursive:
    """Test suite for :func:`ondewo.utils.helpers.get_attr_recursive`."""

    def test_nested_attribute(self) -> None:
        """Verify that a dotted path resolves a deeply nested attribute value."""
        obj: SimpleNamespace = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=42)))
        assert get_attr_recursive(obj, "a.b.c") == 42

    def test_single_level_attribute(self) -> None:
        """Verify that a single attribute name resolves a top-level attribute value."""
        obj: SimpleNamespace = SimpleNamespace(x=7)
        assert get_attr_recursive(obj, "x") == 7

    def test_missing_attribute_with_default(self) -> None:
        """Verify that a missing attribute returns the supplied default value."""
        obj: SimpleNamespace = SimpleNamespace(a=SimpleNamespace())
        assert get_attr_recursive(obj, "a.missing", "fallback") == "fallback"

    def test_none_mid_path_with_default_returns_the_default(self) -> None:
        """Verify a ``None`` along the path yields the default rather than an ``AttributeError``."""
        default: object = object()
        assert get_attr_recursive(SimpleNamespace(a=None), "a.b.c", default) is default

    def test_the_rest_of_the_path_is_never_looked_up_on_the_default(self) -> None:
        """Verify ``"a.missing.upper"`` with default ``"x"`` gives ``"x"``, not ``"x".upper``."""
        assert get_attr_recursive(SimpleNamespace(a=SimpleNamespace()), "a.missing.upper", "x") == "x"

    def test_an_existing_none_at_the_end_is_returned_not_the_default(self) -> None:
        """Verify an attribute that exists with value ``None`` is returned even when a default is given."""
        assert get_attr_recursive(SimpleNamespace(a=SimpleNamespace(b=None)), "a.b", "x") is None

    def test_missing_attribute_without_default_raises(self) -> None:
        """Verify that a missing attribute without a default raises ``AttributeError``."""
        obj: SimpleNamespace = SimpleNamespace()
        with pytest.raises(AttributeError):
            get_attr_recursive(obj, "does_not_exist")


class TestSetAttrRecursive:
    """Test suite for :func:`ondewo.utils.helpers.set_attr_recursive`."""

    def test_nested_attribute(self) -> None:
        """Verify that a dotted path sets a deeply nested attribute value."""
        obj: SimpleNamespace = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=0)))
        set_attr_recursive(obj, "a.b.c", 99)
        assert obj.a.b.c == 99

    def test_single_level_attribute(self) -> None:
        """Verify that a single attribute name sets a top-level attribute value."""
        obj: SimpleNamespace = SimpleNamespace(x=0)
        set_attr_recursive(obj, "x", "new")
        assert obj.x == "new"

    def test_a_missing_intermediate_attribute_raises(self) -> None:
        """Verify a path through a missing attribute raises ``AttributeError`` naming it, and sets nothing."""
        obj: SimpleNamespace = SimpleNamespace(a=SimpleNamespace())
        with pytest.raises(AttributeError, match="missing"):
            set_attr_recursive(obj, "a.missing.c", 1)
        assert vars(obj.a) == {}
