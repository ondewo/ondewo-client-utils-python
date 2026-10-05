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


def _build_file_descriptor() -> FileDescriptor:
    """
    Build a real ``FileDescriptor`` for the ``ondewo.retrytest.Calls`` test service.

    Returns:
        FileDescriptor:
            The descriptor, added to a private pool so it never clashes with the default pool.
    """
    file_proto: descriptor_pb2.FileDescriptorProto = descriptor_pb2.FileDescriptorProto(
        name="ondewo/retrytest/calls.proto",
        package="ondewo.retrytest",
        syntax="proto3",
    )
    file_proto.message_type.add(name="Msg")
    service: descriptor_pb2.ServiceDescriptorProto = file_proto.service.add(name="Calls")
    for method_name, level in RETRY_TEST_METHODS.items():
        service.method.add(
            name=method_name,
            input_type=".ondewo.retrytest.Msg",
            output_type=".ondewo.retrytest.Msg",
            options=descriptor_pb2.MethodOptions(idempotency_level=level),
        )
    pool: descriptor_pool.DescriptorPool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return pool.FindFileByName(file_proto.name)


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
    pb2: ModuleType = ModuleType("retry_fixture.calls_pb2")
    pb2.DESCRIPTOR = _build_file_descriptor()  # type: ignore[attr-defined]
    pb2_grpc: ModuleType = ModuleType("retry_fixture.calls_pb2_grpc")
    calls_stub: type = type("CallsStub", (), {"__module__": pb2_grpc.__name__})
    pb2_grpc.CallsStub = calls_stub  # type: ignore[attr-defined]
    services: ModuleType = ModuleType("retry_fixture.services.calls")
    services.calls_pb2 = pb2  # type: ignore[attr-defined]
    services.CallsStub = calls_stub  # type: ignore[attr-defined]

    registered: Tuple[ModuleType, ...] = (pb2, pb2_grpc, services)
    for module in registered:
        sys.modules[module.__name__] = module
    yield services
    for module in registered:
        del sys.modules[module.__name__]
