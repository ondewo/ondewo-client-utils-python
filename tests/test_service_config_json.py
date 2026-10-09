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
Edge cases of the gRPC service-config JSON (the ``grpc.service_config`` channel option).

grpc-core validates that document when the channel is created and, if it rejects it, fails EVERY
RPC on the channel with ``INVALID_ARGUMENT: Failed to create channel`` -- a duplicated method path,
a second default entry, a ``maxAttempts`` below 2 or a duration without its ``s`` suffix all do
that (measured, grpcio 1.81). So every shape below is fed to a real sync and a real ``grpc.aio``
channel, and acceptance means an RPC reaches the server.
"""

import json
import re
import sys
from time import perf_counter
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Set,
    Tuple,
)
from unittest import mock

import grpc
import pytest
from google.protobuf import (
    descriptor_pb2,
    descriptor_pool,
)
from google.protobuf.descriptor import ServiceDescriptor

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils import base_services_interface as bsi
from ondewo.utils import grpc_retry_policy as policy
from ondewo.utils.async_base_services_interface import AsyncBaseServicesInterface
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_services_interface import BaseServicesInterface
from tests.conftest import (
    CALL_TIMEOUT_IN_S,
    _register_fake_client,
)

UNKNOWN: int = descriptor_pb2.MethodOptions.IDEMPOTENCY_UNKNOWN
IDEMPOTENT: int = descriptor_pb2.MethodOptions.IDEMPOTENT
NO_SIDE_EFFECTS: int = descriptor_pb2.MethodOptions.NO_SIDE_EFFECTS

# (idempotency_level, client_streaming, server_streaming)
MethodSpec = Tuple[int, bool, bool]
UNARY: MethodSpec = (UNKNOWN, False, False)

DEFAULT_ENTRY: Dict[str, Any] = {"name": [{}]}
DURATION: "re.Pattern[str]" = re.compile(r"^\d+(\.\d{1,9})?s$")


def _service(package: str, name: str, methods: Dict[str, MethodSpec]) -> ServiceDescriptor:
    """
    Build a real ``ServiceDescriptor`` in a private descriptor pool.

    Args:
        package (str):
            The proto package, e.g. ``"ondewo.edge.v1"``.
        name (str):
            The service name.
        methods (Dict[str, MethodSpec]):
            Method name -> ``(idempotency_level, client_streaming, server_streaming)``.

    Returns:
        ServiceDescriptor:
            The service.
    """
    file_proto: descriptor_pb2.FileDescriptorProto = descriptor_pb2.FileDescriptorProto(
        name=f"{package.replace('.', '/')}/{name.lower()}.proto", package=package, syntax="proto3"
    )
    file_proto.message_type.add(name="Msg")
    service: descriptor_pb2.ServiceDescriptorProto = file_proto.service.add(name=name)
    for method_name, (level, client_streaming, server_streaming) in methods.items():
        service.method.add(
            name=method_name,
            input_type=f".{package}.Msg",
            output_type=f".{package}.Msg",
            client_streaming=client_streaming,
            server_streaming=server_streaming,
            options=descriptor_pb2.MethodOptions(idempotency_level=level),  # type: ignore[arg-type]
        )
    pool: descriptor_pool.DescriptorPool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    return pool.FindFileByName(file_proto.name).services_by_name[name]


def _retried(config_json: str) -> Set[Tuple[str, str]]:
    """
    Return the ``(service, method)`` pairs the config gives a retry policy.

    Args:
        config_json (str):
            A service config.

    Returns:
        Set[Tuple[str, str]]:
            The retried methods.
    """
    return {
        (name["service"], name["method"])
        for entry in json.loads(config_json)["methodConfig"]
        if "retryPolicy" in entry
        for name in entry["name"]
    }


def _assert_well_formed(config_json: str) -> None:
    """
    Assert the structural rules grpc-core enforces, plus determinism.

    Args:
        config_json (str):
            A service config.
    """
    assert config_json.isascii()
    config: Dict[str, Any] = json.loads(config_json)
    assert json.dumps(config) == config_json  # canonical: a re-render is byte-identical
    entries: List[Dict[str, Any]] = config["methodConfig"]
    assert entries[-1] == DEFAULT_ENTRY and entries.count(DEFAULT_ENTRY) == 1
    paths: List[Tuple[str, str]] = [
        (name["service"], name["method"]) for entry in entries[:-1] for name in entry["name"]
    ]
    assert len(paths) == len(set(paths)), "a duplicated method path makes grpc-core reject the whole channel"
    for entry in entries[:-1]:
        retry_policy: Dict[str, Any] = entry["retryPolicy"]
        assert 2 <= retry_policy["maxAttempts"] <= 5  # gRPC requires >= 2 and clamps above 5
        assert DURATION.match(retry_policy["initialBackoff"]) and DURATION.match(retry_policy["maxBackoff"])
        assert retry_policy["backoffMultiplier"] > 0
        assert set(retry_policy["retryableStatusCodes"]) <= {code.name for code in grpc.StatusCode}


# region what a config contains

SHAPES: Dict[str, List[ServiceDescriptor]] = {
    "no services": [],
    "a service without methods": [_service("ondewo.edge", "Empty", {})],
    "only idempotent methods": [_service("ondewo.edge", "Reads", {"GetA": UNARY, "ListA": UNARY})],
    "only non-idempotent methods": [_service("ondewo.edge", "Writes", {"CreateA": UNARY, "DeleteA": UNARY})],
    "several services, nested packages": [
        _service("ondewo.edge.v1.inner", "Alpha", {"GetA": UNARY, "StartA": UNARY}),
        _service("ondewo.edge", "Beta", {"ListB": UNARY}),
    ],
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_every_shape_is_well_formed(shape: str) -> None:
    """Verify each shape renders a deterministic config grpc-core's rules allow."""
    _assert_well_formed(policy.build_service_config_json(SHAPES[shape]))


def test_the_configs_are_exactly_the_expected_documents() -> None:
    """Verify the full documents, including package-qualified service names, field for field."""
    retry_policy: Dict[str, Any] = policy.IDEMPOTENT_RETRY_POLICY
    assert json.loads(policy.build_service_config_json([])) == {"methodConfig": [DEFAULT_ENTRY]}
    assert json.loads(policy.build_service_config_json(SHAPES["a service without methods"])) == {
        "methodConfig": [DEFAULT_ENTRY]
    }
    assert json.loads(policy.build_service_config_json(SHAPES["only non-idempotent methods"])) == {
        "methodConfig": [DEFAULT_ENTRY]
    }
    assert json.loads(policy.build_service_config_json(SHAPES["several services, nested packages"])) == {
        "methodConfig": [
            {
                "name": [
                    {"service": "ondewo.edge.v1.inner.Alpha", "method": "GetA"},
                    {"service": "ondewo.edge.Beta", "method": "ListB"},
                ],
                "retryPolicy": retry_policy,
            },
            DEFAULT_ENTRY,
        ]
    }


def test_a_service_listed_twice_is_named_once() -> None:
    """Verify a duplicated service (same ``full_name``) does not duplicate its method paths."""
    reads: ServiceDescriptor = SHAPES["only idempotent methods"][0]
    same_name_other_pool: ServiceDescriptor = _service("ondewo.edge", "Reads", {"GetA": UNARY, "ListA": UNARY})
    config_json: str = policy.build_service_config_json([reads, reads, same_name_other_pool])
    _assert_well_formed(config_json)
    assert config_json == policy.build_service_config_json([reads])


READ_NAMES: List[str] = ["Get", "List", "Ping", "Check", "Validate", "BatchGet", "GetX", "Get2", "Get_x", "ListX"]
NOT_READ_NAMES: List[str] = ["Getaway", "Listen", "Pinger", "Checkout", "Validated", "BatchGetter", "get", "SipGetX"]


def test_read_verbs_match_exactly_or_as_a_prefix_word_only() -> None:
    """Verify exact verbs and verb-prefixed names are retried, look-alikes are not."""
    methods: Dict[str, MethodSpec] = {name: UNARY for name in READ_NAMES + NOT_READ_NAMES}
    retried: Set[Tuple[str, str]] = _retried(policy.build_service_config_json([_service("e", "S", methods)]))
    assert retried == {("e.S", name) for name in READ_NAMES}


def test_streaming_methods_follow_the_same_name_rule() -> None:
    """Verify server-, client- and bidi-streaming methods are classified by name like unary ones."""
    methods: Dict[str, MethodSpec] = {
        "GetControlStream": (UNKNOWN, False, True),
        "ListenEvents": (UNKNOWN, False, True),
        "StreamAudio": (UNKNOWN, True, False),
        "UploadFile": (UNKNOWN, True, False),
        "GetUpdates": (UNKNOWN, True, True),
        "Converse": (UNKNOWN, True, True),
    }
    config_json: str = policy.build_service_config_json([_service("e", "S", methods)])
    _assert_well_formed(config_json)
    assert _retried(config_json) == {("e.S", "GetControlStream"), ("e.S", "GetUpdates")}


def test_the_declared_idempotency_level_wins_over_the_name_and_the_denylist() -> None:
    """Verify NO_SIDE_EFFECTS / IDEMPOTENT retry any name, IDEMPOTENCY_UNKNOWN falls back to the name."""
    sessions: ServiceDescriptor = _service(
        "ondewo.nlu",
        "Sessions",
        {
            "GetSessionReview": (IDEMPOTENT, False, False),  # denylisted, but declared idempotent
            "GetLatestSessionReview": UNARY,  # denylisted, undeclared: not retried
            "DeleteSession": (NO_SIDE_EFFECTS, False, False),
            "UpdateSession": (IDEMPOTENT, False, False),
            "CreateSession": UNARY,
            "GetSession": UNARY,
        },
    )
    assert _retried(policy.build_service_config_json([sessions])) == {
        ("ondewo.nlu.Sessions", "GetSessionReview"),
        ("ondewo.nlu.Sessions", "DeleteSession"),
        ("ondewo.nlu.Sessions", "UpdateSession"),
        ("ondewo.nlu.Sessions", "GetSession"),
    }


@pytest.mark.parametrize("name", ["Gétaway", "Get✓", "Список"])
def test_protobuf_refuses_non_ascii_names_so_the_config_is_always_ascii(name: str) -> None:
    """Verify a non-ASCII method name cannot even become a descriptor (the config cannot carry one)."""
    with pytest.raises(TypeError, match="invalid name"):
        _service("e", "S", {name: UNARY})


# endregion

# region grpc-core accepts every produced config, and enforces it


EDGE_METHODS: Dict[str, MethodSpec] = {
    "GetA": UNARY,
    "StartA": UNARY,
    "GetStream": (UNKNOWN, False, True),
    "StartStream": (UNKNOWN, False, True),
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_grpc_core_accepts_every_shape_on_a_sync_channel(
    shape: str, edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]]
) -> None:
    """Verify the channel is usable: an unknown method answers UNIMPLEMENTED, not INVALID_ARGUMENT."""
    port: str = edge_server[0]
    options: List[Tuple[str, Any]] = [
        ("grpc.enable_retries", 1),
        ("grpc.service_config", policy.build_service_config_json(SHAPES[shape])),
    ]
    with grpc.insecure_channel(f"127.0.0.1:{port}", options=options) as channel:
        with pytest.raises(grpc.RpcError) as raised:
            channel.unary_unary("/e.S/Nope")(b"", timeout=CALL_TIMEOUT_IN_S)
    assert raised.value.code() == grpc.StatusCode.UNIMPLEMENTED


@pytest.mark.parametrize("shape", sorted(SHAPES))
async def test_grpc_core_accepts_every_shape_on_an_async_channel(
    shape: str, edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]]
) -> None:
    """Verify a ``grpc.aio`` channel accepts the config: UNIMPLEMENTED, not INVALID_ARGUMENT."""
    port: str = edge_server[0]
    options: List[Tuple[str, Any]] = [
        ("grpc.enable_retries", 1),
        ("grpc.service_config", policy.build_service_config_json(SHAPES[shape])),
    ]
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}", options=options) as channel:
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await channel.unary_unary("/e.S/Nope")(b"", timeout=CALL_TIMEOUT_IN_S)
    assert raised.value.code() == grpc.StatusCode.UNIMPLEMENTED


def test_a_duplicated_path_would_have_broken_the_channel(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify the failure mode the de-duplication prevents, so the guard above is not vacuous."""
    port: str = edge_server[0]
    duplicated: Dict[str, Any] = json.loads(policy.build_service_config_json([_service("e", "S", EDGE_METHODS)]))
    duplicated["methodConfig"][0]["name"].append(duplicated["methodConfig"][0]["name"][0])
    options: List[Tuple[str, Any]] = [("grpc.service_config", json.dumps(duplicated))]
    with grpc.insecure_channel(f"127.0.0.1:{port}", options=options) as channel:
        with pytest.raises(grpc.RpcError) as raised:
            channel.unary_unary("/e.S/GetA")(b"", timeout=CALL_TIMEOUT_IN_S)
    assert raised.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert edge_server[1] == {}


def test_ten_thousand_methods_build_fast_and_are_accepted_by_grpc_core(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify a huge service (10k methods, half of them reads) stays cheap to describe and gRPC parses it."""
    methods: Dict[str, MethodSpec] = {f"{'Get' if index % 2 else 'Start'}M{index}": UNARY for index in range(10_000)}
    service: ServiceDescriptor = _service("e", "Huge", methods)
    start_time: float = perf_counter()
    config_json: str = policy.build_service_config_json([service])
    assert perf_counter() - start_time < 0.5  # measured ~8 ms
    _assert_well_formed(config_json)
    assert len(_retried(config_json)) == 5_000
    options: List[Tuple[str, Any]] = [("grpc.enable_retries", 1), ("grpc.service_config", config_json)]
    with grpc.insecure_channel(f"127.0.0.1:{edge_server[0]}", options=options) as channel:
        with pytest.raises(grpc.RpcError) as raised:
            channel.unary_unary("/e.S/Nope")(b"", timeout=CALL_TIMEOUT_IN_S)
    assert raised.value.code() == grpc.StatusCode.UNIMPLEMENTED


def _edge_service_class(base: type) -> Tuple[type, Tuple[ModuleType, ...]]:
    """
    Register a fake generated client for ``e.S`` and define a service interface in it.

    Args:
        base (type):
            ``BaseServicesInterface`` or ``AsyncBaseServicesInterface``.

    Returns:
        Tuple[type, Tuple[ModuleType, ...]]:
            The class and the registered modules (to unregister).
    """
    registered: Tuple[ModuleType, ...] = _register_fake_client("edge", "SStub", _service("e", "S", EDGE_METHODS).file)
    service_class: type = type("S", (base,), {"__module__": registered[-1].__name__, "stub": property(lambda s: None)})
    return service_class, registered


@pytest.fixture
def edge_classes() -> Iterator[Callable[[type], type]]:
    """
    Provide a factory for ``e.S`` service-interface classes, unregistering their modules afterwards.

    Yields:
        Callable[[type], type]:
            ``base -> class``.
    """
    registered_modules: List[ModuleType] = []

    def make(base: type) -> type:
        service_class, registered = _edge_service_class(base)
        registered_modules.extend(registered)
        return service_class

    yield make
    for module in registered_modules:
        sys.modules.pop(module.__name__, None)


def test_a_streaming_read_is_re_opened_and_a_streaming_mutation_is_not(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]], edge_classes: Callable[[type], type]
) -> None:
    """Verify end to end that a server-streaming read failing before its first response is retried."""
    port, counts, script = edge_server
    script["GetStream"] = [grpc.StatusCode.UNAVAILABLE]
    script["StartStream"] = [grpc.StatusCode.UNAVAILABLE]
    service: Any = edge_classes(BaseServicesInterface)(
        config=BaseClientConfig(host="127.0.0.1", port=port), use_secure_channel=False
    )
    try:
        assert list(service.grpc_channel.unary_stream("/e.S/GetStream")(b"", timeout=CALL_TIMEOUT_IN_S)) == [b"1", b"2"]
        with pytest.raises(grpc.RpcError):
            list(service.grpc_channel.unary_stream("/e.S/StartStream")(b"", timeout=CALL_TIMEOUT_IN_S))
    finally:
        service.grpc_channel.close()
    assert counts == {"GetStream": 2, "StartStream": 1}


async def test_the_async_interface_enforces_the_same_policy_on_streams(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]], edge_classes: Callable[[type], type]
) -> None:
    """Verify the ``grpc.aio`` interface retries the streaming read and not the streaming mutation."""
    port, counts, script = edge_server
    script["GetStream"] = [grpc.StatusCode.UNAVAILABLE]
    script["StartStream"] = [grpc.StatusCode.UNAVAILABLE]
    service: Any = edge_classes(AsyncBaseServicesInterface)(
        config=BaseClientConfig(host="127.0.0.1", port=port), use_secure_channel=False
    )
    try:
        assert [
            item async for item in service.grpc_channel.unary_stream("/e.S/GetStream")(b"", timeout=CALL_TIMEOUT_IN_S)
        ] == [b"1", b"2"]
        with pytest.raises(grpc.aio.AioRpcError):
            [
                item
                async for item in service.grpc_channel.unary_stream("/e.S/StartStream")(b"", timeout=CALL_TIMEOUT_IN_S)
            ]
    finally:
        await service.grpc_channel.close()
    assert counts == {"GetStream": 2, "StartStream": 1}


@pytest.mark.parametrize("interface_module, base", [(bsi, BaseServicesInterface), (absi, AsyncBaseServicesInterface)])
def test_the_config_is_built_once_however_many_services_are_constructed(
    interface_module: ModuleType, base: type, edge_classes: Callable[[type], type]
) -> None:
    """Verify N constructions of one class build the config once and hand over the same string object."""
    service_class: type = edge_classes(base)
    seen: List[str] = []
    with (
        mock.patch.object(policy, "build_service_config_json", wraps=policy.build_service_config_json) as build,
        mock.patch.object(interface_module, "_get_grpc_channel") as get_channel,
    ):
        for _ in range(5):
            service_class(config=BaseClientConfig(host="localhost", port="1"), use_secure_channel=False)
            seen.append(dict(get_channel.call_args.kwargs["options"])["grpc.service_config"])
    assert build.call_count == 1
    assert all(config_json is seen[0] for config_json in seen)
    assert _retried(seen[0]) == {("e.S", "GetA"), ("e.S", "GetStream")}


# endregion
