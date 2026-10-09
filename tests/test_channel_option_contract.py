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
The channel-option contract of ``__init__``, pinned for BOTH the sync and the async interface.

The two modules are hand-maintained copies, so every assertion here runs against each of them:
the options handed to ``_get_grpc_channel``, the caller-override merge order, and the per-class cache.
"""

import json
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
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.grpc_retry_policy import service_config_json_for

INTERFACES: List[Any] = [
    pytest.param((bsi, bsi.BaseServicesInterface), id="sync"),
    pytest.param((absi, absi.AsyncBaseServicesInterface), id="async"),
]


def _concrete(base: type) -> type:
    """
    Define a fresh concrete service-interface class, so no per-class cache answers from another test.

    Args:
        base (type):
            ``BaseServicesInterface`` or ``AsyncBaseServicesInterface``.

    Returns:
        type:
            A concrete subclass whose ``stub`` property returns ``None``.
    """
    return type("Concrete", (base,), {"stub": property(lambda self: None)})


def _options_passed(
    module: Any, service_class: type, options: Optional[Set[Tuple[str, Any]]] = None
) -> List[Tuple[str, Any]]:
    """
    Construct the service with ``_get_grpc_channel`` patched and return the options it was handed.

    Args:
        module (Any):
            The service-interface module whose ``_get_grpc_channel`` is patched.
        service_class (type):
            The concrete class to construct.
        options (Optional[Set[Tuple[str, Any]]]):
            The caller's option overrides. Defaults to ``None``.

    Returns:
        List[Tuple[str, Any]]:
            The ``options`` keyword ``_get_grpc_channel`` received.
    """
    config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
    with mock.patch.object(module, "_get_grpc_channel") as get_channel:
        service: Any = service_class(config=config, use_secure_channel=False, options=options)
    assert service.grpc_channel is get_channel.return_value
    get_channel.assert_called_once()
    assert get_channel.call_args.kwargs["config"] is config
    assert get_channel.call_args.kwargs["use_secure_channel"] is False
    passed: List[Tuple[str, Any]] = get_channel.call_args.kwargs["options"]
    return passed


@pytest.mark.parametrize("interface", INTERFACES)
def test_without_options_the_class_defaults_are_passed(interface: Tuple[Any, type]) -> None:
    """Verify the channel gets the defaults with the class's own retry config, nothing else."""
    module, base = interface
    service_class: type = _concrete(base)
    passed: List[Tuple[str, Any]] = _options_passed(module, service_class)
    assert passed == module._grpc_options_items_for(service_class)
    assert dict(passed) == {
        **module._DEFAULT_GRPC_OPTIONS,
        "grpc.service_config": service_config_json_for(service_class),
    }


@pytest.mark.parametrize("interface", INTERFACES)
def test_a_caller_option_overrides_one_default_and_keeps_the_rest(interface: Tuple[Any, type]) -> None:
    """Verify caller options are merged ON TOP of the defaults (the merge order matters)."""
    module, base = interface
    service_class: type = _concrete(base)
    passed: Dict[str, Any] = dict(_options_passed(module, service_class, {("grpc.max_send_message_length", 123)}))
    assert passed["grpc.max_send_message_length"] == 123
    assert passed == {
        **dict(module._grpc_options_items_for(service_class)),
        "grpc.max_send_message_length": 123,
    }


@pytest.mark.parametrize("interface", INTERFACES)
def test_a_caller_service_config_wins(interface: Tuple[Any, type]) -> None:
    """Verify ``("grpc.service_config", ...)`` replaces the per-class retry policy."""
    module, base = interface
    own_config: str = json.dumps({"methodConfig": [{"name": [{}], "timeout": "1s"}]})
    passed: Dict[str, Any] = dict(_options_passed(module, _concrete(base), {("grpc.service_config", own_config)}))
    assert passed["grpc.service_config"] == own_config
    assert passed["grpc.enable_retries"] == 1


@pytest.mark.parametrize("interface", INTERFACES)
def test_the_default_options_are_built_once_per_class(interface: Tuple[Any, type]) -> None:
    """Verify two instances of one class receive the very same cached options list."""
    module, base = interface
    service_class: type = _concrete(base)
    first: List[Tuple[str, Any]] = _options_passed(module, service_class)
    second: List[Tuple[str, Any]] = _options_passed(module, service_class)
    assert first is second


@pytest.mark.parametrize("interface", INTERFACES)
def test_the_recovery_and_dead_connection_defaults_are_pinned(interface: Tuple[Any, type]) -> None:
    """
    Verify the measured reconnect and dead-connection settings, on both interfaces.

    ``max_reconnect_backoff_ms`` 5 s (gRPC default 120 s: up to ~65 s to recover after an outage),
    ``http2.ping_timeout_ms`` and ``keepalive_timeout_ms`` 20 s (detect a dropped connection in
    ~40 s instead of ~85 s); the GOAWAY-safe keepalive settings stay as they were.
    """
    module, _ = interface
    assert {
        key: module._DEFAULT_GRPC_OPTIONS[key]
        for key in (
            "grpc.max_reconnect_backoff_ms",
            "grpc.http2.ping_timeout_ms",
            "grpc.keepalive_timeout_ms",
            "grpc.keepalive_time_ms",
            "grpc.keepalive_permit_without_calls",
            "grpc.http2.max_pings_without_data",
        )
    } == {
        "grpc.max_reconnect_backoff_ms": 5000,
        "grpc.http2.ping_timeout_ms": 20000,
        "grpc.keepalive_timeout_ms": 20000,
        "grpc.keepalive_time_ms": 30000,
        "grpc.keepalive_permit_without_calls": False,
        "grpc.http2.max_pings_without_data": 2,
    }
