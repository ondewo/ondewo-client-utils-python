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

"""Async unit tests for :class:`ondewo.utils.async_base_services_interface.AsyncBaseServicesInterface`."""

import logging
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Tuple,
)
from unittest import mock

import grpc
import pytest

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils import base_services_interface as bsi
from ondewo.utils.async_base_services_interface import (
    MAX_MESSAGE_LENGTH,
    AsyncBaseServicesInterface,
    get_secure_channel,
)
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.grpc_retry_policy import service_config_json_for


class _ConcreteAsyncService(AsyncBaseServicesInterface):
    """
    Minimal concrete :class:`AsyncBaseServicesInterface` used for testing.

    The abstract base class cannot be instantiated directly, so this subclass
    provides a trivial :pyattr:`stub` implementation to exercise the asynchronous
    channel construction performed in ``AsyncBaseServicesInterface.__init__``.
    """

    @property
    def stub(self) -> Any:
        """
        Return a placeholder stub identifying this concrete test service.

        Returns:
            Any:
                The constant sentinel string ``"the-async-stub"``.
        """
        return "the-async-stub"


def _config(cert: Any = None) -> BaseClientConfig:
    """
    Build a :class:`BaseClientConfig` pointing at a local test endpoint.

    Args:
        cert (Any):
            Optional gRPC certificate forwarded to ``grpc_cert``. Defaults to ``None``.

    Returns:
        BaseClientConfig:
            A config for ``localhost:50051`` carrying the supplied certificate.
    """
    return BaseClientConfig(host="localhost", port="50051", grpc_cert=cert)


def test_max_message_length_is_int32_max() -> None:
    """
    Verify that ``MAX_MESSAGE_LENGTH`` equals the signed 32-bit integer maximum.

    Returns:
        None:
            This test returns nothing; it asserts on the constant value.
    """
    assert MAX_MESSAGE_LENGTH == 2**31 - 1


def test_keepalive_enabled_only_during_active_calls() -> None:
    """
    Verify keepalive is configured to ping only while a call is active.

    Returns:
        None:
            This test returns nothing; it asserts on the default gRPC options.
    """
    # Keepalive pings are on (long-lived streams stay warm, half-open sockets
    # get detected) but only while a call is active, so idle channels never
    # trigger a server "too_many_pings" GOAWAY.
    options: Dict[str, Any] = absi._DEFAULT_GRPC_OPTIONS
    assert options["grpc.keepalive_time_ms"] == 30000
    assert options["grpc.keepalive_permit_without_calls"] is False
    # 2 (gRPC's default), never 0 = unlimited: a default grpc-core server GOAWAYs a client that
    # keeps pinging a silent stream ("too_many_pings", measured after ~50 s at a 10 s keepalive),
    # tearing down the shared connection and every non-retried RPC on it.
    assert options["grpc.http2.max_pings_without_data"] == 2


async def test_insecure_channel_without_options() -> None:
    """
    Verify an insecure channel is built when ``use_secure_channel`` is ``False``.

    Returns:
        None:
            This test returns nothing; it asserts the channel and stub are set.
    """
    service: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(), use_secure_channel=False)
    # a real channel: gRPC core accepted every default option, the service config included
    assert isinstance(service.grpc_channel, grpc.aio.Channel)
    assert service.stub == "the-async-stub"
    await service.grpc_channel.close(grace=None)


def test_get_secure_channel_builds_credentials() -> None:
    """
    Verify ``get_secure_channel`` builds SSL credentials and a secure channel.

    Returns:
        None:
            This test returns nothing; it asserts on the mocked gRPC calls.
    """
    with (
        mock.patch.object(absi.grpc, "ssl_channel_credentials") as creds,
        mock.patch.object(absi.grpc.aio, "secure_channel") as secure_channel,
    ):
        channel = get_secure_channel(host="localhost:50051", cert="cert-bytes", options=[])
    # a str cert is normalized to bytes before being handed to gRPC
    creds.assert_called_once_with(root_certificates=b"cert-bytes", private_key=None, certificate_chain=None)
    # options must reach gRPC: a get_secure_channel that dropped them would silently lose the
    # retry policy, the keepalive and the message-size limits on every TLS channel
    secure_channel.assert_called_once_with(target="localhost:50051", credentials=creds.return_value, options=[])
    assert channel is secure_channel.return_value


def test_secure_channel_via_init() -> None:
    """Verify ``__init__`` opens a TLS channel with the class's full default options."""
    with (
        mock.patch.object(absi.grpc, "ssl_channel_credentials") as creds,
        mock.patch.object(absi.grpc.aio, "secure_channel") as secure_channel,
    ):
        service: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(cert="my-cert"), use_secure_channel=True)
    assert service.grpc_channel is secure_channel.return_value
    creds.assert_called_once_with(root_certificates=b"my-cert", private_key=None, certificate_chain=None)
    expected_options: List[Tuple[str, Any]] = absi._grpc_options_items_for(_ConcreteAsyncService)
    secure_channel.assert_called_once_with(
        target="localhost:50051", credentials=creds.return_value, options=expected_options
    )
    options: Dict[str, Any] = dict(expected_options)
    assert options["grpc.service_config"] == service_config_json_for(_ConcreteAsyncService)
    assert options["grpc.enable_retries"] == 1
    assert options["grpc.max_send_message_length"] == MAX_MESSAGE_LENGTH
    assert options["grpc.max_receive_message_length"] == MAX_MESSAGE_LENGTH


def test_secure_channel_missing_cert_raises() -> None:
    """
    Verify init raises ``ValueError`` when a secure channel lacks a certificate.

    Returns:
        None:
            This test returns nothing; it asserts a ``ValueError`` is raised.

    Raises:
        AssertionError:
            If the expected ``ValueError`` is not raised.
    """
    with pytest.raises(ValueError, match="No grpc certificate"):
        _ConcreteAsyncService(config=_config(cert=None), use_secure_channel=True)


@dataclass(frozen=True)
class _ConfigWithPassword(BaseClientConfig):
    """
    A downstream-style config subclass carrying a credential that must never reach an error message.

    Attributes:
        password (str):
            A credential field.
    """

    password: str = ""


async def test_insecure_warning_uses_a_module_logger_and_names_the_target(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the insecure warning leaves the root logger alone and names the plaintext target."""
    root: logging.Logger = logging.getLogger()
    # A host application that configured no logging: module-level logging.warning() would run
    # basicConfig() here and leave a stderr handler on the root logger.
    monkeypatch.setattr(root, "handlers", [])
    unconfigured: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(), use_secure_channel=False)
    assert root.handlers == []
    await unconfigured.grpc_channel.close(grace=None)

    monkeypatch.setattr(root, "handlers", [caplog.handler])
    with caplog.at_level(logging.WARNING, logger="ondewo.utils.async_base_services_interface"):
        service: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(), use_secure_channel=False)
    records: List[logging.LogRecord] = [
        r for r in caplog.records if r.name == "ondewo.utils.async_base_services_interface"
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "localhost:50051" in records[0].getMessage()
    await service.grpc_channel.close(grace=None)


def test_missing_cert_error_never_renders_the_config() -> None:
    """Verify the missing-certificate error names class and target but not the config's fields."""
    config: _ConfigWithPassword = _ConfigWithPassword(host="h", port="1", password="hunter2")
    with pytest.raises(ValueError, match="No grpc certificate") as error:
        _ConcreteAsyncService(config=config, use_secure_channel=True)
    assert "hunter2" not in str(error.value)
    assert "hunter2" not in repr(error.value)
    assert "h:1" in str(error.value)
    assert "_ConfigWithPassword" in str(error.value)


def test_srv_queries_are_not_enabled_by_default() -> None:
    """Verify the grpclb-only SRV lookup is off (15.9 ms vs 1.4 ms per channel to 127.0.0.1)."""
    assert "grpc.dns_enable_srv_queries" not in absi._DEFAULT_GRPC_OPTIONS


def test_sync_and_async_default_options_are_identical() -> None:
    """Verify the two hand-maintained copies of the default channel options cannot drift."""
    assert dict(bsi._DEFAULT_GRPC_OPTIONS) == absi._DEFAULT_GRPC_OPTIONS
