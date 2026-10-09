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
Behavioural tests: the service interfaces retry idempotent methods only.

Written against the public surface (the channel options a service interface opens its channel
with, and a real in-process gRPC server), so they also run against the previous blanket policy,
which retried EVERY method on nine status codes, and fail there. That policy re-sent a
non-idempotent ``StartCallers`` the server was already executing and deployed a batch twice
(ondewo-vtsi-release #115).
"""

import json
from concurrent import futures
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
)
from unittest import mock

import grpc
import pytest

from ondewo.utils import base_services_interface as bsi
from ondewo.utils.async_base_services_interface import AsyncBaseServicesInterface
from ondewo.utils.base_services_interface import BaseServicesInterface
from tests.conftest import (
    CALL_TIMEOUT_IN_S,
    RETRY_TEST_SERVICE,
    local_config,
)

NON_IDEMPOTENT_METHODS: List[str] = ["StartCallers", "CreateCaller", "DeleteCaller", "Getaway"]
READ_METHODS: List[str] = ["ListCallers", "GetCaller", "BatchGetCallers", "Ping"]
DECLARED_IDEMPOTENT_METHODS: List[str] = ["UpsertCaller", "ComputeStatistics"]
RETRIED_FOR_IDEMPOTENT: List[str] = [
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
    "UNKNOWN",
    "RESOURCE_EXHAUSTED",
    "ABORTED",
    "CANCELLED",
]


def _service_class(module: ModuleType, base: type) -> type:
    """
    Define a concrete service-interface class inside the given (fake client) module.

    Args:
        module (ModuleType):
            The module the class claims to be defined in.
        base (type):
            ``BaseServicesInterface`` or ``AsyncBaseServicesInterface``.

    Returns:
        type:
            A concrete subclass whose ``stub`` property returns ``None``.
    """
    return type("Calls", (base,), {"__module__": module.__name__, "stub": property(lambda self: None)})


def _service_config_of(service_class: type) -> Dict[str, Any]:
    """
    Return the parsed gRPC service config a service interface opens its channel with.

    Args:
        service_class (type):
            A concrete synchronous service-interface class.

    Returns:
        Dict[str, Any]:
            The parsed ``grpc.service_config`` channel option.
    """
    with mock.patch.object(bsi, "_get_grpc_channel") as get_channel:
        service_class(config=local_config(), use_secure_channel=False)
    channel_options: Dict[str, Any] = dict(get_channel.call_args.kwargs["options"])
    service_config: Dict[str, Any] = json.loads(channel_options["grpc.service_config"])
    return service_config


def _retry_policy(service_config: Dict[str, Any], method: str) -> Optional[Dict[str, Any]]:
    """
    Resolve the retry policy gRPC applies to a method, by gRPC's name-matching precedence.

    An entry naming the exact method beats one naming its whole service, which beats ``{}``.

    Args:
        service_config (Dict[str, Any]):
            A parsed gRPC service config.
        method (str):
            A method of :data:`RETRY_TEST_SERVICE`.

    Returns:
        Optional[Dict[str, Any]]:
            The ``retryPolicy`` that applies, or ``None`` if the matching entry has none.
    """
    candidates: List[Dict[str, str]] = [
        {"service": RETRY_TEST_SERVICE, "method": method},
        {"service": RETRY_TEST_SERVICE},
        {},
    ]
    for candidate in candidates:
        for method_config in service_config["methodConfig"]:
            if candidate in method_config["name"]:
                policy: Optional[Dict[str, Any]] = method_config.get("retryPolicy")
                return policy
    return None


def _retried_codes(service_config: Dict[str, Any], method: str) -> List[str]:
    """
    Return the status codes on which gRPC re-sends a method.

    Args:
        service_config (Dict[str, Any]):
            A parsed gRPC service config.
        method (str):
            A method of :data:`RETRY_TEST_SERVICE`.

    Returns:
        List[str]:
            The retryable status code names; empty when no retry policy applies.
    """
    policy: Optional[Dict[str, Any]] = _retry_policy(service_config, method)
    codes: List[str] = policy["retryableStatusCodes"] if policy else []
    return codes


@pytest.mark.parametrize("method", NON_IDEMPOTENT_METHODS)
def test_a_non_idempotent_method_gets_no_retry_policy(retry_test_service_module: ModuleType, method: str) -> None:
    """
    Verify a mutation resolves to NO retry policy, so no status re-sends it (UNAVAILABLE: the #115 GOAWAY case).

    Stronger than checking a list of codes: a policy with any code (or a hedging policy) would fail here.
    """
    service_config: Dict[str, Any] = _service_config_of(
        _service_class(retry_test_service_module, BaseServicesInterface)
    )
    assert _retry_policy(service_config, method) is None
    assert _retried_codes(service_config, method) == []


@pytest.mark.parametrize("method", READ_METHODS + DECLARED_IDEMPOTENT_METHODS)
def test_an_idempotent_method_is_retried_on_the_broad_set(retry_test_service_module: ModuleType, method: str) -> None:
    """Verify read verbs and proto-declared idempotent methods retry on every transient status."""
    service_config: Dict[str, Any] = _service_config_of(
        _service_class(retry_test_service_module, BaseServicesInterface)
    )
    retried: List[str] = _retried_codes(service_config, method)
    assert sorted(retried) == sorted(RETRIED_FOR_IDEMPOTENT)
    assert "NOT_FOUND" not in retried and "DATA_LOSS" not in retried


# region end to end: a real in-process gRPC server counting how often each handler runs


@pytest.fixture
def counting_server() -> Iterator[Tuple[str, Dict[str, List[str]], Dict[str, List[grpc.StatusCode]]]]:
    """
    Start an in-process gRPC server for :data:`RETRY_TEST_SERVICE` that counts handler invocations.

    Each method answers the next status code queued in ``script[method]`` (``OK`` once empty).

    Yields:
        Tuple[str, Dict[str, List[str]], Dict[str, List[grpc.StatusCode]]]:
            The server port, the invocation log per method, and the per-method status script.
    """
    invocations: Dict[str, List[str]] = {}
    script: Dict[str, List[grpc.StatusCode]] = {}

    def handler_for(method: str) -> Callable[[bytes, grpc.ServicerContext], bytes]:
        def handle(request: bytes, context: grpc.ServicerContext) -> bytes:
            invocations.setdefault(method, []).append(method)
            queued: List[grpc.StatusCode] = script.get(method, [])
            if queued:
                context.abort(queued.pop(0), f"scripted failure of {method}")
            return b""

        return handle

    server: grpc.Server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                RETRY_TEST_SERVICE,
                {
                    name: grpc.unary_unary_rpc_method_handler(handler_for(name))
                    for name in ["StartCallers", "ListCallers"]
                },
            ),
        )
    )
    port: int = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield str(port), invocations, script
    server.stop(grace=None)


@pytest.mark.parametrize("status", [grpc.StatusCode.INTERNAL, grpc.StatusCode.UNAVAILABLE])
def test_a_failing_non_idempotent_rpc_runs_exactly_once(
    retry_test_service_module: ModuleType,
    counting_server: Tuple[str, Dict[str, List[str]], Dict[str, List[grpc.StatusCode]]],
    status: grpc.StatusCode,
) -> None:
    """Verify the server executes a failing ``StartCallers`` once: the client never re-sends it."""
    port, invocations, script = counting_server
    script["StartCallers"] = [status] * 10
    service: Any = _service_class(retry_test_service_module, BaseServicesInterface)(
        config=local_config(host="127.0.0.1", port=port), use_secure_channel=False
    )
    try:
        with pytest.raises(grpc.RpcError) as raised:
            service.grpc_channel.unary_unary(f"/{RETRY_TEST_SERVICE}/StartCallers")(b"", timeout=CALL_TIMEOUT_IN_S)
    finally:
        service.grpc_channel.close()
    assert raised.value.code() == status
    assert len(invocations["StartCallers"]) == 1


def test_an_idempotent_rpc_is_retried_until_it_succeeds(
    retry_test_service_module: ModuleType,
    counting_server: Tuple[str, Dict[str, List[str]], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify a ``ListCallers`` answered UNAVAILABLE once is re-sent and then succeeds."""
    port, invocations, script = counting_server
    script["ListCallers"] = [grpc.StatusCode.UNAVAILABLE]
    service: Any = _service_class(retry_test_service_module, BaseServicesInterface)(
        config=local_config(host="127.0.0.1", port=port), use_secure_channel=False
    )
    try:
        assert (
            service.grpc_channel.unary_unary(f"/{RETRY_TEST_SERVICE}/ListCallers")(b"", timeout=CALL_TIMEOUT_IN_S)
            == b""
        )
    finally:
        service.grpc_channel.close()
    assert len(invocations["ListCallers"]) == 2


async def test_the_async_interface_retries_idempotent_methods_only(
    retry_test_service_module: ModuleType,
    counting_server: Tuple[str, Dict[str, List[str]], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify the ``grpc.aio`` interface applies the same per-method policy end to end."""
    port, invocations, script = counting_server
    script["StartCallers"] = [grpc.StatusCode.INTERNAL] * 10
    script["ListCallers"] = [grpc.StatusCode.UNAVAILABLE]
    service: Any = _service_class(retry_test_service_module, AsyncBaseServicesInterface)(
        config=local_config(host="127.0.0.1", port=port), use_secure_channel=False
    )
    try:
        with pytest.raises(grpc.aio.AioRpcError):
            await service.grpc_channel.unary_unary(f"/{RETRY_TEST_SERVICE}/StartCallers")(
                b"", timeout=CALL_TIMEOUT_IN_S
            )
        assert (
            await service.grpc_channel.unary_unary(f"/{RETRY_TEST_SERVICE}/ListCallers")(b"", timeout=CALL_TIMEOUT_IN_S)
            == b""
        )
    finally:
        await service.grpc_channel.close()
    assert len(invocations["StartCallers"]) == 1
    assert len(invocations["ListCallers"]) == 2


# endregion
