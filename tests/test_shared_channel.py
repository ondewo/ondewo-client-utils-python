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
Tests for the opt-in shared channel: one connection for all of a client's services.

A shared channel must change no method's retry policy (the union config names each method by its
fully qualified service), must not build a channel per service, and must be closed exactly once.
"""

import json
from dataclasses import dataclass
from types import ModuleType
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)
from unittest import mock

import pytest

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils import base_services_interface as bsi
from ondewo.utils import grpc_retry_policy as policy
from ondewo.utils.async_base_client import AsyncBaseClient
from ondewo.utils.base_client import BaseClient
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_service_container import BaseServicesContainer

# service_config_json_for(<class in the Calls fixture module>) as it was before the discovery loop
# was factored out for the shared channel; the refactor must not change a single byte of it.
CALLS_SERVICE_CONFIG_SNAPSHOT: str = (
    '{"methodConfig": [{"name": [{"service": "ondewo.retrytest.Calls", "method": "ListCallers"}, '
    '{"service": "ondewo.retrytest.Calls", "method": "GetCaller"}, '
    '{"service": "ondewo.retrytest.Calls", "method": "BatchGetCallers"}, '
    '{"service": "ondewo.retrytest.Calls", "method": "Ping"}, '
    '{"service": "ondewo.retrytest.Calls", "method": "UpsertCaller"}, '
    '{"service": "ondewo.retrytest.Calls", "method": "ComputeStatistics"}], '
    '"retryPolicy": {"maxAttempts": 5, "initialBackoff": "0.1s", "maxBackoff": "3s", "backoffMultiplier": 2, '
    '"retryableStatusCodes": ["CANCELLED", "UNKNOWN", "DEADLINE_EXCEEDED", "RESOURCE_EXHAUSTED", "ABORTED", '
    '"INTERNAL", "UNAVAILABLE"]}}, {"name": [{}]}]}'
)

INTERFACE_MODULES: List[Any] = [
    pytest.param((bsi, bsi.BaseServicesInterface), id="sync"),
    pytest.param((absi, absi.AsyncBaseServicesInterface), id="async"),
]


def _service_class(module: ModuleType, base: type, name: str) -> type:
    """
    Define a concrete service-interface class inside the given fake client module.

    Args:
        module (ModuleType):
            The module the class claims to be defined in.
        base (type):
            ``BaseServicesInterface`` or ``AsyncBaseServicesInterface``.
        name (str):
            The class name.

    Returns:
        type:
            A fresh concrete subclass, so no per-class cache answers from another test.
    """
    return type(name, (base,), {"__module__": module.__name__, "stub": property(lambda self: None)})


def _policies(service_config_json: str) -> Dict[Tuple[str, str], Optional[Dict[str, Any]]]:
    """
    Map every explicitly named method of a service config to its retry policy.

    Args:
        service_config_json (str):
            A JSON service config.

    Returns:
        Dict[Tuple[str, str], Optional[Dict[str, Any]]]:
            ``(service, method)`` -> the ``retryPolicy`` of the entry naming it.
    """
    result: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
    for entry in json.loads(service_config_json)["methodConfig"]:
        for name in entry["name"]:
            if name:
                result[(name["service"], name["method"])] = entry.get("retryPolicy")
    return result


def _config() -> BaseClientConfig:
    """
    Build a config pointing at a local test endpoint.

    Returns:
        BaseClientConfig:
            ``localhost:50051`` without a certificate.
    """
    return BaseClientConfig(host="localhost", port="50051")


def test_the_refactor_kept_the_per_class_config_byte_identical(retry_test_service_module: ModuleType) -> None:
    """Verify ``service_config_json_for`` still emits exactly what it emitted before the refactor."""
    calls: type = type("Calls", (), {"__module__": retry_test_service_module.__name__})
    assert policy.service_config_json_for(calls) == CALLS_SERVICE_CONFIG_SNAPSHOT


def test_the_union_config_gives_every_method_its_own_policy(
    retry_test_service_module: ModuleType, agents_test_service_module: ModuleType
) -> None:
    """Verify the shared config gives each method exactly its per-class policy, and no mutation gains one."""
    calls: type = type("Calls", (), {"__module__": retry_test_service_module.__name__})
    agents: type = type("Agents", (), {"__module__": agents_test_service_module.__name__})
    union: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = _policies(
        policy.service_config_json_for_classes((calls, agents))
    )
    per_class: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {
        **_policies(policy.service_config_json_for(calls)),
        **_policies(policy.service_config_json_for(agents)),
    }
    assert union == per_class
    assert ("ondewo.retrytest.Agents", "GetAgent") in union
    assert ("ondewo.retrytest.Agents", "CreateAgent") not in union
    assert ("ondewo.retrytest.Agents", "TrainAgent") not in union
    assert ("ondewo.retrytest.Calls", "StartCallers") not in union
    assert json.loads(policy.service_config_json_for_classes((calls, agents)))["methodConfig"][-1] == {"name": [{}]}


def test_the_union_config_is_built_once_per_tuple(retry_test_service_module: ModuleType) -> None:
    """Verify the union config is cached per tuple of classes."""
    calls: type = type("Calls", (), {"__module__": retry_test_service_module.__name__})
    assert policy.service_config_json_for_classes((calls,)) is policy.service_config_json_for_classes((calls,))


@pytest.mark.parametrize("interface", INTERFACE_MODULES)
def test_a_given_channel_is_used_and_nothing_is_built(
    interface: Tuple[Any, type], retry_test_service_module: ModuleType, agents_test_service_module: ModuleType
) -> None:
    """Verify services handed ``grpc_channel=`` keep it and never open a channel of their own."""
    module, base = interface
    shared: mock.MagicMock = mock.MagicMock(name="shared-channel")
    calls: type = _service_class(retry_test_service_module, base, "Calls")
    agents: type = _service_class(agents_test_service_module, base, "Agents")
    with mock.patch.object(module, "_get_grpc_channel") as get_channel:
        first: Any = calls(config=_config(), use_secure_channel=True, grpc_channel=shared)
        second: Any = agents(config=_config(), use_secure_channel=True, options={("x", 1)}, grpc_channel=shared)
    assert first.grpc_channel is shared
    assert second.grpc_channel is shared
    get_channel.assert_not_called()


@pytest.mark.parametrize("interface", INTERFACE_MODULES)
def test_build_shared_channel_uses_the_union_config_and_caller_options_win(
    interface: Tuple[Any, type], retry_test_service_module: ModuleType, agents_test_service_module: ModuleType
) -> None:
    """Verify the shared channel gets the defaults, the union retry config, and caller overrides on top."""
    module, base = interface
    calls: type = _service_class(retry_test_service_module, base, "Calls")
    agents: type = _service_class(agents_test_service_module, base, "Agents")
    with mock.patch.object(module, "_get_grpc_channel") as get_channel:
        channel: Any = module.build_shared_channel(_config(), False, (calls, agents))
        module.build_shared_channel(
            _config(),
            True,
            (calls, agents),
            options={("grpc.max_send_message_length", 123), ("grpc.service_config", "{}")},
        )
    assert channel is get_channel.return_value
    default_call, override_call = get_channel.call_args_list
    assert default_call.kwargs["use_secure_channel"] is False
    defaults: Dict[str, Any] = dict(default_call.kwargs["options"])
    assert defaults == {
        **module._DEFAULT_GRPC_OPTIONS,
        "grpc.service_config": policy.service_config_json_for_classes((calls, agents)),
    }
    overridden: Dict[str, Any] = dict(override_call.kwargs["options"])
    assert override_call.kwargs["use_secure_channel"] is True
    assert overridden["grpc.max_send_message_length"] == 123
    assert overridden["grpc.service_config"] == "{}"
    assert overridden["grpc.keepalive_time_ms"] == module._DEFAULT_GRPC_OPTIONS["grpc.keepalive_time_ms"]


def test_build_shared_channel_opens_a_real_sync_channel(retry_test_service_module: ModuleType) -> None:
    """Verify an insecure shared channel really opens (the union config is accepted by gRPC core)."""
    calls: type = _service_class(retry_test_service_module, bsi.BaseServicesInterface, "Calls")
    channel: Any = bsi.build_shared_channel(_config(), False, (calls,))
    channel.close()


async def test_build_shared_channel_opens_a_real_async_channel(retry_test_service_module: ModuleType) -> None:
    """Verify an insecure async shared channel really opens inside the running event loop."""
    calls: type = _service_class(retry_test_service_module, absi.AsyncBaseServicesInterface, "Calls")
    channel: Any = absi.build_shared_channel(_config(), False, (calls,))
    await channel.close(grace=None)


@dataclass
class _SharedServices(BaseServicesContainer):
    """
    Services container whose two services share one channel.

    Attributes:
        calls (Any):
            The ``Calls`` service interface.
        agents (Any):
            The ``Agents`` service interface.
    """

    calls: Any = None
    agents: Any = None


def test_a_sync_client_sharing_one_channel_closes_it_once(
    retry_test_service_module: ModuleType, agents_test_service_module: ModuleType
) -> None:
    """Verify ``disconnect`` closes a channel two real service interfaces share exactly once."""
    calls: type = _service_class(retry_test_service_module, bsi.BaseServicesInterface, "Calls")
    agents: type = _service_class(agents_test_service_module, bsi.BaseServicesInterface, "Agents")
    shared: mock.MagicMock = mock.MagicMock(name="shared-channel")

    class _Client(BaseClient):
        """A client that opts into one shared channel."""

        def _initialize_services(
            self, config: BaseClientConfig, use_secure_channel: bool, options: Optional[Set[Tuple[str, Any]]] = None
        ) -> None:
            """
            Hand the same channel to both services.

            Args:
                config (BaseClientConfig):
                    Configuration for the client.
                use_secure_channel (bool):
                    Whether to use a secure gRPC channel.
                options (Optional[Set[Tuple[str, Any]]]):
                    Additional options for the gRPC channel.
            """
            self.services = _SharedServices(
                calls=calls(config, use_secure_channel, grpc_channel=shared),
                agents=agents(config, use_secure_channel, grpc_channel=shared),
            )

    client: _Client = _Client(config=_config())
    client.disconnect()
    shared.close.assert_called_once_with()


async def test_an_async_client_sharing_one_channel_closes_it_once(
    retry_test_service_module: ModuleType, agents_test_service_module: ModuleType
) -> None:
    """Verify async ``disconnect`` awaits the close of a shared channel exactly once."""
    calls: type = _service_class(retry_test_service_module, absi.AsyncBaseServicesInterface, "Calls")
    agents: type = _service_class(agents_test_service_module, absi.AsyncBaseServicesInterface, "Agents")
    shared: mock.MagicMock = mock.MagicMock(name="shared-channel")
    shared.close = mock.AsyncMock()

    class _Client(AsyncBaseClient):
        """An async client that opts into one shared channel."""

        def _initialize_services(
            self, config: BaseClientConfig, use_secure_channel: bool, options: Optional[Set[Tuple[str, Any]]] = None
        ) -> None:
            """
            Hand the same channel to both services.

            Args:
                config (BaseClientConfig):
                    Configuration for the client.
                use_secure_channel (bool):
                    Whether to use a secure gRPC channel.
                options (Optional[Set[Tuple[str, Any]]]):
                    Additional options for the gRPC channel.
            """
            self.services = _SharedServices(
                calls=calls(config, use_secure_channel, grpc_channel=shared),
                agents=agents(config, use_secure_channel, grpc_channel=shared),
            )

    client: _Client = _Client(config=_config())
    await client.disconnect()
    shared.close.assert_awaited_once_with(grace=None)
