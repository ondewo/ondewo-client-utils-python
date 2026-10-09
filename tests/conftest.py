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
Shared fixtures and definitions for the test suite.

* A hermetic stand-in for a generated ONDEWO client, for the retry-policy tests: a real protobuf
  ``FileDescriptor`` for a ``ondewo.retrytest.Calls`` service, a fake ``calls_pb2`` / ``calls_pb2_grpc``
  module pair, and a fake ``services.calls`` module that imports both the way a downstream client
  service module does (``from ondewo.vtsi import calls_pb2`` and
  ``from ondewo.vtsi.calls_pb2_grpc import CallsStub``).
* An in-process gRPC server (:func:`edge_server`) that real channels call.
* The config builders and the downstream-shaped ``BaseClientConfig`` subclasses several modules share.
* The repository root and its ``pyproject.toml``.
"""

import sys
import tomllib
from concurrent import futures
from dataclasses import (
    dataclass,
    field,
    fields,
)
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Optional,
    Tuple,
)

import grpc
import pytest
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
)
from google.protobuf.descriptor import FileDescriptor

from ondewo.utils.base_client_config import BaseClientConfig

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

#: The timeout of every call a test makes on a real channel, so a broken channel fails instead of hanging.
CALL_TIMEOUT_IN_S: float = 10.0


def load_pyproject() -> Dict[str, Any]:
    """
    Parse the repository's ``pyproject.toml``.

    Returns:
        Dict[str, Any]:
            The parsed document.
    """
    pyproject: Dict[str, Any] = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject


# region configs


def local_config(cert: Any = None, host: str = "localhost", port: str = "50051") -> BaseClientConfig:
    """
    Build a plain :class:`BaseClientConfig`, by default for ``localhost:50051`` without a certificate.

    Args:
        cert (Any):
            The ``grpc_cert``. Defaults to ``None``.
        host (str):
            The host. Defaults to ``"localhost"``.
        port (str):
            The port. Defaults to ``"50051"``.

    Returns:
        BaseClientConfig:
            The config.
    """
    return BaseClientConfig(host=host, port=port, grpc_cert=cert)


@dataclass(frozen=True)
class ConfigWithPassword(BaseClientConfig):
    """
    A downstream-style frozen config subclass carrying a credential that must never reach an error message.

    Attributes:
        password (str):
            A credential field, as downstream SDK configs declare.
    """

    password: str = ""


PEM: str = "-----BEGIN CERTIFICATE-----\nMIIBszCCAVmgAwIBAgIU\nAbC+/=\n-----END CERTIFICATE-----\n"
SECRET: str = "s3cret-Pa55w0rd"
REFRESH_TOKEN: str = "offline-refresh-token-value"


@dataclass(frozen=True)
class KeycloakConfig(BaseClientConfig):
    """
    A stdlib frozen subclass shaped like ondewo-nlu-client's ``ClientConfig`` (no ``@dataclass_json``).

    Attributes:
        user_name (str): The Keycloak user.
        password (str): The ROPC password (a secret).
        keycloak_url (str): The Keycloak base URL.
        realm (str): The Keycloak realm.
        client_id (str): The public SDK client id.
        token_expiration_in_s (Optional[int]): The refresh-loop bound.
        keycloak_verify_ssl (bool): Whether the token endpoint's TLS certificate is verified.
        refresh_token (str): A handed-off offline token (a secret).
    """

    user_name: str = ""
    password: str = ""
    keycloak_url: str = ""
    realm: str = ""
    client_id: str = ""
    token_expiration_in_s: Optional[int] = None
    keycloak_verify_ssl: bool = True
    refresh_token: str = ""

    SECRET_FIELD_NAMES: ClassVar[FrozenSet[str]] = frozenset({"password", "grpc_cert", "refresh_token"})

    def __repr__(self) -> str:
        """
        Render the config without its credential material, as the downstream SDKs do.

        Returns:
            str:
                ``KeycloakConfig(host=..., password='***REDACTED***', ...)``.
        """
        rendered: List[str] = []
        for config_field in fields(self):
            value: Any = getattr(self, config_field.name, None)
            if config_field.name in self.SECRET_FIELD_NAMES and value:
                rendered.append(f"{config_field.name}='***REDACTED***'")
            else:
                rendered.append(f"{config_field.name}={value!r}")
        return f"{type(self).__name__}({', '.join(rendered)})"


@dataclass(frozen=True)
class PipeUnionConfig(BaseClientConfig):
    """
    A subclass shaped like ondewo-vtsi-client's ``ClientConfig``: PEP 604 ``X | None`` fields.

    Attributes:
        realm (str | None): The Keycloak realm.
        password (str | None): A secret.
        token_expiration_in_s (int | None): The refresh-loop bound.
    """

    realm: str | None = None
    password: str | None = None
    token_expiration_in_s: int | None = None


@dataclass(frozen=True)
class Inner:
    """
    A nested dataclass value.

    Attributes:
        name (str): A name.
        weight (int): A number.
    """

    name: str
    weight: int = 1


@dataclass(frozen=True)
class NestedConfig(BaseClientConfig):
    """
    A subclass with nested and collection-typed fields.

    Attributes:
        inner (Optional[Inner]): A nested dataclass.
        tags (List[str]): A list.
        labels (Dict[str, str]): A mapping.
    """

    inner: Optional[Inner] = None
    tags: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)


# endregion

# region an in-process gRPC server


@pytest.fixture
def edge_server() -> Iterator[Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]]]:
    """
    Start an in-process server for ``e.S`` whose handlers count calls and fail as scripted.

    ``GetA`` / ``StartA`` are unary, ``GetStream`` / ``StartStream`` server-streaming (two
    responses). Every other method (e.g. ``/e.S/Nope``) is answered ``UNIMPLEMENTED`` by gRPC itself,
    which proves a channel is usable: a channel whose options grpc-core rejected (an unparsable
    ``grpc.service_config``, say) answers every call ``INVALID_ARGUMENT`` instead.

    Yields:
        Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]]:
            The port on ``127.0.0.1``, the call count per method and the per-method failure script.
    """
    counts: Dict[str, int] = {}
    script: Dict[str, List[grpc.StatusCode]] = {}

    def fail_if_scripted(method: str, context: grpc.ServicerContext) -> None:
        counts[method] = counts.get(method, 0) + 1
        if script.get(method):
            context.abort(script[method].pop(0), f"scripted failure of {method}")

    def unary(method: str) -> Callable[[bytes, grpc.ServicerContext], bytes]:
        def handle(request: bytes, context: grpc.ServicerContext) -> bytes:
            fail_if_scripted(method, context)
            return b"ok"

        return handle

    def streaming(method: str) -> Callable[[bytes, grpc.ServicerContext], Iterator[bytes]]:
        def handle(request: bytes, context: grpc.ServicerContext) -> Iterator[bytes]:
            fail_if_scripted(method, context)
            yield b"1"
            yield b"2"

        return handle

    server: grpc.Server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    handlers: Dict[str, grpc.RpcMethodHandler] = {
        "GetA": grpc.unary_unary_rpc_method_handler(unary("GetA")),
        "StartA": grpc.unary_unary_rpc_method_handler(unary("StartA")),
        "GetStream": grpc.unary_stream_rpc_method_handler(streaming("GetStream")),
        "StartStream": grpc.unary_stream_rpc_method_handler(streaming("StartStream")),
    }
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("e.S", handlers),))
    port: int = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield str(port), counts, script
    server.stop(grace=None)


# endregion

# region a fake generated client

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


# endregion
