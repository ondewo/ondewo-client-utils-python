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
Shared fixtures for the retry-policy tests.

Builds a hermetic stand-in for a generated ONDEWO client: a real protobuf ``FileDescriptor`` for a
``ondewo.retrytest.Calls`` service, a fake ``calls_pb2`` / ``calls_pb2_grpc`` module pair, and a
fake ``services.calls`` module that imports both the way a downstream client service module does
(``from ondewo.vtsi import calls_pb2`` and ``from ondewo.vtsi.calls_pb2_grpc import CallsStub``).
"""

import sys
from types import ModuleType
from typing import (
    Dict,
    Iterator,
    Optional,
    Tuple,
)

import pytest
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
)
from google.protobuf.descriptor import FileDescriptor

RETRY_TEST_SERVICE: str = "ondewo.retrytest.Calls"

# Method name -> idempotency_level declared in its proto options.
RETRY_TEST_METHODS: Dict[str, "descriptor_pb2.MethodOptions.IdempotencyLevel.ValueType"] = {
    "StartCallers": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "CreateCaller": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "DeleteCaller": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "Getaway": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "ListCallers": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "GetCaller": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "BatchGetCallers": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "Ping": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "UpsertCaller": descriptor_pb2.MethodOptions.IDEMPOTENT,
    "ComputeStatistics": descriptor_pb2.MethodOptions.NO_SIDE_EFFECTS,
}


AGENTS_TEST_SERVICE: str = "ondewo.retrytest.Agents"

# A second service in a second generated module, for the shared-channel tests.
AGENTS_TEST_METHODS: Dict[str, "descriptor_pb2.MethodOptions.IdempotencyLevel.ValueType"] = {
    "CreateAgent": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "GetAgent": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "ListAgents": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
    "TrainAgent": descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN,
}


def _build_file_descriptor(
    file_name: str = "ondewo/retrytest/calls.proto",
    service_name: str = "Calls",
    methods: Optional[Dict[str, "descriptor_pb2.MethodOptions.IdempotencyLevel.ValueType"]] = None,
) -> FileDescriptor:
    """
    Build a real ``FileDescriptor`` for one ``ondewo.retrytest`` test service.

    Args:
        file_name (str):
            The proto file name. Defaults to the ``Calls`` service's file.
        service_name (str):
            The service name inside package ``ondewo.retrytest``. Defaults to ``"Calls"``.
        methods (Optional[Dict[str, MethodOptions.IdempotencyLevel.ValueType]]):
            Method name -> declared idempotency level. Defaults to :data:`RETRY_TEST_METHODS`.

    Returns:
        FileDescriptor:
            The descriptor, added to a private pool so it never clashes with the default pool.
    """
    file_proto: descriptor_pb2.FileDescriptorProto = descriptor_pb2.FileDescriptorProto(
        name=file_name,
        package="ondewo.retrytest",
        syntax="proto3",
    )
    file_proto.message_type.add(name="Msg")
    service: descriptor_pb2.ServiceDescriptorProto = file_proto.service.add(name=service_name)
    for method_name, level in (RETRY_TEST_METHODS if methods is None else methods).items():
        service.method.add(
            name=method_name,
            input_type=".ondewo.retrytest.Msg",
            output_type=".ondewo.retrytest.Msg",
            options=descriptor_pb2.MethodOptions(idempotency_level=level),
        )
    pool: descriptor_pool.DescriptorPool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return pool.FindFileByName(file_proto.name)


def _register_fake_client(name: str, stub_name: str, file_descriptor: FileDescriptor) -> Tuple[ModuleType, ...]:
    """
    Register a fake generated client (pb2, pb2_grpc and a service module) in ``sys.modules``.

    Args:
        name (str):
            The proto module stem, e.g. ``"calls"`` for ``calls_pb2``.
        stub_name (str):
            The stub class name, e.g. ``"CallsStub"``.
        file_descriptor (FileDescriptor):
            The descriptor the fake ``*_pb2`` module carries.

    Returns:
        Tuple[ModuleType, ...]:
            ``(pb2, pb2_grpc, services)``; the service module is last.
    """
    pb2: ModuleType = ModuleType(f"retry_fixture.{name}_pb2")
    pb2.DESCRIPTOR = file_descriptor  # type: ignore[attr-defined]
    pb2_grpc: ModuleType = ModuleType(f"retry_fixture.{name}_pb2_grpc")
    stub: type = type(stub_name, (), {"__module__": pb2_grpc.__name__})
    setattr(pb2_grpc, stub_name, stub)
    services: ModuleType = ModuleType(f"retry_fixture.services.{name}")
    setattr(services, f"{name}_pb2", pb2)
    setattr(services, stub_name, stub)
    registered: Tuple[ModuleType, ...] = (pb2, pb2_grpc, services)
    for module in registered:
        sys.modules[module.__name__] = module
    return registered


@pytest.fixture
def retry_test_service_module() -> Iterator[ModuleType]:
    """
    Register a fake generated client (pb2, pb2_grpc and a service module) in ``sys.modules``.

    The service module references the ``*_pb2`` module directly and the stub class of the
    ``*_pb2_grpc`` module, mirroring how ONDEWO client service modules import them.

    Yields:
        ModuleType:
            The fake service module; define a service-interface class with this ``__module__``.
    """
    registered: Tuple[ModuleType, ...] = _register_fake_client("calls", "CallsStub", _build_file_descriptor())
    yield registered[-1]
    for module in registered:
        del sys.modules[module.__name__]


@pytest.fixture
def agents_test_service_module() -> Iterator[ModuleType]:
    """
    Register a second fake generated client, for the ``ondewo.retrytest.Agents`` service.

    Yields:
        ModuleType:
            The fake ``services.agents`` module.
    """
    registered: Tuple[ModuleType, ...] = _register_fake_client(
        "agents",
        "AgentsStub",
        _build_file_descriptor("ondewo/retrytest/agents.proto", "Agents", AGENTS_TEST_METHODS),
    )
    yield registered[-1]
    for module in registered:
        del sys.modules[module.__name__]
