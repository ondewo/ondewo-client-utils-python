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

from types import SimpleNamespace

import pytest
from google.protobuf.struct_pb2 import Struct

from ondewo.utils.helpers import (
    get_attr_recursive,
    get_struct_from_dict,
    set_attr_recursive,
)


class TestGetStructFromDict:
    def test_returns_struct_with_values(self) -> None:
        struct = get_struct_from_dict({"a": "b", "n": 1, "flag": True})
        assert isinstance(struct, Struct)
        assert struct["a"] == "b"
        assert struct["n"] == 1
        assert struct["flag"] is True

    def test_none_returns_empty_struct(self) -> None:
        struct = get_struct_from_dict(None)  # type: ignore[arg-type]
        assert isinstance(struct, Struct)
        assert len(struct.fields) == 0

    def test_empty_dict_returns_empty_struct(self) -> None:
        struct = get_struct_from_dict({})
        assert len(struct.fields) == 0

    def test_non_dict_raises_assertion_error(self) -> None:
        with pytest.raises(AssertionError):
            get_struct_from_dict("not-a-dict")  # type: ignore[arg-type]


class TestGetAttrRecursive:
    def test_nested_attribute(self) -> None:
        obj = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=42)))
        assert get_attr_recursive(obj, "a.b.c") == 42

    def test_single_level_attribute(self) -> None:
        obj = SimpleNamespace(x=7)
        assert get_attr_recursive(obj, "x") == 7

    def test_missing_attribute_with_default(self) -> None:
        obj = SimpleNamespace(a=SimpleNamespace())
        assert get_attr_recursive(obj, "a.missing", "fallback") == "fallback"

    def test_missing_attribute_without_default_raises(self) -> None:
        obj = SimpleNamespace()
        with pytest.raises(AttributeError):
            get_attr_recursive(obj, "does_not_exist")


class TestSetAttrRecursive:
    def test_nested_attribute(self) -> None:
        obj = SimpleNamespace(a=SimpleNamespace(b=SimpleNamespace(c=0)))
        set_attr_recursive(obj, "a.b.c", 99)
        assert obj.a.b.c == 99

    def test_single_level_attribute(self) -> None:
        obj = SimpleNamespace(x=0)
        set_attr_recursive(obj, "x", "new")
        assert obj.x == "new"
