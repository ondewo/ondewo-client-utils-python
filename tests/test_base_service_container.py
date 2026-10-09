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

"""
Unit tests for :class:`BaseServicesContainer`.

Verify that ``BaseServicesContainer`` is a dataclass and can be instantiated.
"""

import dataclasses
from typing import Any

from ondewo.utils.base_service_container import BaseServicesContainer


def test_is_dataclass_and_instantiable() -> None:
    """
    Verify that ``BaseServicesContainer`` is a dataclass and can be instantiated.

    Returns:
        None:
            This test returns nothing; it asserts on the container instead.
    """
    container: BaseServicesContainer = BaseServicesContainer()
    assert dataclasses.is_dataclass(container)


@dataclasses.dataclass
class _ParentServices(BaseServicesContainer):
    """
    A container declaring one service, extended below.

    Attributes:
        parent_svc (Any): A service declared on the parent.
    """

    parent_svc: Any = None


@dataclasses.dataclass
class _ChildServices(_ParentServices):
    """
    A container inheriting ``parent_svc`` and adding ``child_svc``.

    Attributes:
        child_svc (Any): A service declared on the child.
    """

    child_svc: Any = None


def test_a_subclassed_container_enumerates_inherited_fields_first() -> None:
    """Verify ``dataclasses.fields`` (what ``disconnect`` walks) lists parent fields, then the child's, in order."""
    assert [field.name for field in dataclasses.fields(_ChildServices())] == ["parent_svc", "child_svc"]
