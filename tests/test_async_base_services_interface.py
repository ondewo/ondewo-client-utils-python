# Copyright 2020-2024 ONDEWO GmbH
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

from typing import (
    Any,
    Dict,
)
from unittest import mock

import pytest

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils.async_base_services_interface import (
    MAX_MESSAGE_LENGTH,
    AsyncBaseServicesInterface,
    get_secure_channel,
)
from ondewo.utils.base_client_config import BaseClientConfig


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
    assert MAX_MESSAGE_LENGTH == 2 ** 31 - 1


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
    assert options["grpc.http2.max_pings_without_data"] == 0


async def test_insecure_channel_without_options() -> None:
    """
    Verify an insecure channel is built when ``use_secure_channel`` is ``False``.

    Returns:
        None:
            This test returns nothing; it asserts the channel and stub are set.
    """
    service: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(), use_secure_channel=False)
    assert service.grpc_channel is not None
    assert service.stub == "the-async-stub"
    await service.grpc_channel.close(grace=None)


async def test_insecure_channel_with_options_merges_defaults() -> None:
    """
    Verify custom options are merged with the defaults on an insecure channel.

    Returns:
        None:
            This test returns nothing; it asserts the merged channel is built.
    """
    service: _ConcreteAsyncService = _ConcreteAsyncService(
        config=_config(),
        use_secure_channel=False,
        options={("grpc.max_send_message_length", 123)},
    )
    assert service.grpc_channel is not None
    await service.grpc_channel.close(grace=None)


def test_get_secure_channel_builds_credentials() -> None:
    """
    Verify ``get_secure_channel`` builds SSL credentials and a secure channel.

    Returns:
        None:
            This test returns nothing; it asserts on the mocked gRPC calls.
    """
    with mock.patch.object(absi.grpc, "ssl_channel_credentials") as creds, mock.patch.object(
        absi.grpc.aio, "secure_channel"
    ) as secure_channel:
        channel = get_secure_channel(host="localhost:50051", cert="cert-bytes", options=[])
    creds.assert_called_once_with(root_certificates="cert-bytes")
    secure_channel.assert_called_once()
    assert channel is secure_channel.return_value


def test_secure_channel_via_init() -> None:
    """
    Verify a secure channel is created during init when a certificate is present.

    Returns:
        None:
            This test returns nothing; it asserts the channel is the secure one.
    """
    with mock.patch.object(absi.grpc, "ssl_channel_credentials"), mock.patch.object(
        absi.grpc.aio, "secure_channel"
    ) as secure_channel:
        service: _ConcreteAsyncService = _ConcreteAsyncService(config=_config(cert="my-cert"), use_secure_channel=True)
    assert service.grpc_channel is secure_channel.return_value


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
