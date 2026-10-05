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
"""Unit tests for :mod:`ondewo.utils.grpc_retry_policy`."""

import json
import sys
from types import ModuleType
from typing import (
    Any,
    Dict,
    List,
)

import pytest

from ondewo.utils import grpc_retry_policy as policy
from tests.conftest import RETRY_TEST_SERVICE


def _idempotent_methods(service_config_json: str) -> List[str]:
    """
    Return the methods a service config gives the idempotent retry policy.

    Args:
        service_config_json (str):
            A service config built by :mod:`ondewo.utils.grpc_retry_policy`.

    Returns:
        List[str]:
            The method names listed with :data:`policy.IDEMPOTENT_RETRY_POLICY`.
    """
    method_config: List[Dict[str, Any]] = json.loads(service_config_json)["methodConfig"]
    return [
        name["method"]
        for entry in method_config
        if entry.get("retryPolicy") == policy.IDEMPOTENT_RETRY_POLICY
        for name in entry["name"]
    ]


def _class_in(module: ModuleType) -> type:
    """
    Define an empty class that claims to live in the given module.

    Args:
        module (ModuleType):
            The module whose globals the discovery should scan.

    Returns:
        type:
            A fresh class, so the per-class cache never answers from a previous test.
    """
    return type("Calls", (), {"__module__": module.__name__})


@pytest.mark.parametrize(
    "name, expected",
    [
        ("GetAgent", True),
        ("ListCallers", True),
        ("BatchGetEntities", True),
        ("CheckLogin", True),
        ("ValidateRegex", True),
        ("Ping", True),
        ("Getaway", False),
        ("Listen", False),
        ("BatchCreateEntities", False),
        ("SipGetSipStatus", False),
        ("DetectIntent", False),
        ("StartCallers", False),
    ],
)
def test_read_verbs_match_as_whole_words(name: str, expected: bool) -> None:
    """Verify the read-verb pattern matches a leading verb only as a whole word."""
    assert (policy.READ_ONLY_METHOD_NAME_PATTERN.match(name) is not None) is expected


def test_the_default_config_retries_nothing_beyond_grpc_itself() -> None:
    """Verify a config without services has only the policy-less ``{}`` default entry."""
    assert json.loads(policy.build_service_config_json([])) == {"methodConfig": [{"name": [{}]}]}


def test_discovery_finds_the_service_through_the_pb2_module(retry_test_service_module: ModuleType) -> None:
    """Verify the idempotent methods are derived from the ``*_pb2`` module the class's module imports."""
    service_config_json: str = policy.service_config_json_for(_class_in(retry_test_service_module))
    assert sorted(_idempotent_methods(service_config_json)) == sorted(
        ["ListCallers", "GetCaller", "BatchGetCallers", "Ping", "UpsertCaller", "ComputeStatistics"]
    )
    assert {"service": RETRY_TEST_SERVICE, "method": "StartCallers"} not in json.loads(service_config_json)[
        "methodConfig"
    ][0]["name"]


def test_discovery_finds_the_service_through_the_stub_alone(retry_test_service_module: ModuleType) -> None:
    """Verify a module importing only ``XStub`` from ``*_pb2_grpc`` still yields its service."""
    del retry_test_service_module.calls_pb2
    assert "ListCallers" in _idempotent_methods(policy.service_config_json_for(_class_in(retry_test_service_module)))


def test_a_class_without_generated_modules_gets_the_default() -> None:
    """Verify discovery tolerates unregistered modules and non-generated globals."""
    stray: ModuleType = ModuleType("retry_fixture.stray")
    stray.not_generated = sys  # type: ignore[attr-defined]
    stray.a_value = 42  # type: ignore[attr-defined]
    stray.missing_pb2 = ModuleType("retry_fixture.missing_pb2")  # type: ignore[attr-defined]
    sys.modules[stray.__name__] = stray
    try:
        in_stray: type = _class_in(stray)
        unregistered: type = type("Orphan", (), {"__module__": "retry_fixture.never_imported"})
        assert policy.service_config_json_for(in_stray) == policy.build_service_config_json([])
        assert policy.service_config_json_for(unregistered) == policy.build_service_config_json([])
    finally:
        del sys.modules[stray.__name__]


def test_the_config_is_built_once_per_class(retry_test_service_module: ModuleType) -> None:
    """Verify the per-class discovery is cached rather than repeated per instance."""
    service_class: type = _class_in(retry_test_service_module)
    assert policy.service_config_json_for(service_class) is policy.service_config_json_for(service_class)
