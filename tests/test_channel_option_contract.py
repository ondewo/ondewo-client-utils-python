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
from tests.conftest import (
    ConfigWithPassword,
    local_config,
)

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


def _secure_channel_owner(module: Any) -> Any:
    """
    Return the module whose ``secure_channel`` the given interface module calls.

    Args:
        module (Any):
            ``base_services_interface`` or ``async_base_services_interface``.

    Returns:
        Any:
            ``grpc`` for the sync interface, ``grpc.aio`` for the async one.
    """
    return module.grpc if module is bsi else module.grpc.aio


def _options_passed(module: Any, service_class: type, options: Optional[Any] = None) -> List[Tuple[str, Any]]:
    """
    Construct the service with ``_get_grpc_channel`` patched and return the options it was handed.

    Args:
        module (Any):
            The service-interface module whose ``_get_grpc_channel`` is patched.
        service_class (type):
            The concrete class to construct.
        options (Optional[Any]):
            The caller's option overrides (a set of pairs as typed, or any container ``dict()`` takes).
            Defaults to ``None``.

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


@pytest.mark.parametrize("interface", INTERFACES)
def test_get_secure_channel_builds_credentials(interface: Tuple[Any, type]) -> None:
    """Verify ``get_secure_channel`` builds SSL credentials and hands the options to the secure channel."""
    module, _ = interface
    with (
        mock.patch.object(module.grpc, "ssl_channel_credentials") as creds,
        mock.patch.object(_secure_channel_owner(module), "secure_channel") as secure_channel,
    ):
        channel: Any = module.get_secure_channel(host="localhost:50051", cert="cert-bytes", options=[("k", 1)])
    # a str cert is normalized to bytes before being handed to gRPC
    creds.assert_called_once_with(root_certificates=b"cert-bytes", private_key=None, certificate_chain=None)
    # options must reach gRPC: a get_secure_channel that dropped them would silently lose the
    # retry policy, the keepalive and the message-size limits on every TLS channel
    secure_channel.assert_called_once_with(target="localhost:50051", credentials=creds.return_value, options=[("k", 1)])
    assert channel is secure_channel.return_value


@pytest.mark.parametrize("interface", INTERFACES)
def test_secure_channel_via_init(interface: Tuple[Any, type]) -> None:
    """Verify ``__init__`` opens a TLS channel with the class's full default options."""
    module, base = interface
    service_class: type = _concrete(base)
    with (
        mock.patch.object(module.grpc, "ssl_channel_credentials") as creds,
        mock.patch.object(_secure_channel_owner(module), "secure_channel") as secure_channel,
    ):
        service: Any = service_class(config=local_config(cert="my-cert"), use_secure_channel=True)
    assert service.grpc_channel is secure_channel.return_value
    creds.assert_called_once_with(root_certificates=b"my-cert", private_key=None, certificate_chain=None)
    expected_options: List[Tuple[str, Any]] = module._grpc_options_items_for(service_class)
    secure_channel.assert_called_once_with(
        target="localhost:50051", credentials=creds.return_value, options=expected_options
    )
    options: Dict[str, Any] = dict(expected_options)
    assert options["grpc.service_config"] == service_config_json_for(service_class)
    assert options["grpc.enable_retries"] == 1
    assert options["grpc.max_send_message_length"] == module.MAX_MESSAGE_LENGTH
    assert options["grpc.max_receive_message_length"] == module.MAX_MESSAGE_LENGTH


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("cert", [None, ""], ids=["no-cert", "empty-cert"])
def test_a_secure_channel_without_a_certificate_is_refused_without_rendering_the_config(
    interface: Tuple[Any, type], cert: Optional[str]
) -> None:
    """Verify an unset and an empty certificate both refuse TLS, naming class and target but no field value."""
    _, base = interface
    config: ConfigWithPassword = ConfigWithPassword(host="h", port="1", grpc_cert=cert, password="hunter2")
    with pytest.raises(ValueError, match="No grpc certificate") as error:
        _concrete(base)(config=config, use_secure_channel=True)
    assert "hunter2" not in str(error.value)
    assert "hunter2" not in repr(error.value)
    assert "h:1" in str(error.value)
    assert "ConfigWithPassword" in str(error.value)


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("container", [list, tuple, set, dict], ids=lambda container: container.__name__)
def test_every_option_container_merges_alike(interface: Tuple[Any, type], container: type) -> None:
    """Verify a list, tuple, set or dict of overrides replaces a default in place and appends a new key."""
    module, base = interface
    service_class: type = _concrete(base)
    overrides: List[Tuple[str, Any]] = [("grpc.max_send_message_length", 123), ("x.new_key", 1)]
    passed: List[Tuple[str, Any]] = _options_passed(module, service_class, container(overrides))
    defaults: List[Tuple[str, Any]] = module._grpc_options_items_for(service_class)
    assert passed == [(key, 123 if key == "grpc.max_send_message_length" else value) for key, value in defaults] + [
        ("x.new_key", 1)
    ]


@pytest.mark.parametrize("interface", INTERFACES)
def test_a_key_repeated_in_a_list_takes_its_last_value(interface: Tuple[Any, type]) -> None:
    """Pin ``dict()`` semantics: of two values for one key the later one wins."""
    module, base = interface
    passed: Dict[str, Any] = dict(
        _options_passed(
            module,
            _concrete(base),
            [("grpc.max_send_message_length", 1), ("grpc.max_send_message_length", 2)],
        )
    )
    assert passed["grpc.max_send_message_length"] == 2


@pytest.mark.parametrize("interface", INTERFACES)
@pytest.mark.parametrize("empty", [None, set(), [], (), {}], ids=["None", "set", "list", "tuple", "dict"])
def test_empty_options_pass_the_cached_defaults_object(interface: Tuple[Any, type], empty: Any) -> None:
    """Verify no options, of any container type, hand over the per-class cached list itself (no copy)."""
    module, base = interface
    service_class: type = _concrete(base)
    assert _options_passed(module, service_class, empty) is module._grpc_options_items_for(service_class)


@pytest.mark.parametrize("interface", INTERFACES)
def test_a_caller_override_never_mutates_the_cached_defaults(interface: Tuple[Any, type]) -> None:
    """Verify an override neither edits the per-class cache nor the module defaults, on either path."""
    module, base = interface
    service_class: type = _concrete(base)
    cached: List[Tuple[str, Any]] = module._grpc_options_items_for(service_class)
    cached_before: List[Tuple[str, Any]] = list(cached)
    defaults_before: Dict[str, Any] = dict(module._DEFAULT_GRPC_OPTIONS)
    overrides: Set[Tuple[str, Any]] = {("grpc.max_send_message_length", 123), ("grpc.service_config", "{}")}
    _options_passed(module, service_class, overrides)
    with mock.patch.object(module, "_get_grpc_channel"):
        module.build_shared_channel(local_config(), False, (service_class,), options=overrides)
    assert module._grpc_options_items_for(service_class) is cached
    assert cached == cached_before
    assert module._DEFAULT_GRPC_OPTIONS == defaults_before
