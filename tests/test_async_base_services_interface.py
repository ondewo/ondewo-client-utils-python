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

from typing import Any
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
    @property
    def stub(self) -> Any:
        return "the-async-stub"


def _config(cert: Any = None) -> BaseClientConfig:
    return BaseClientConfig(host="localhost", port="50051", grpc_cert=cert)


def test_max_message_length_is_int32_max() -> None:
    assert MAX_MESSAGE_LENGTH == 2 ** 31 - 1


def test_keepalive_enabled_only_during_active_calls() -> None:
    # Keepalive pings are on (long-lived streams stay warm, half-open sockets
    # get detected) but only while a call is active, so idle channels never
    # trigger a server "too_many_pings" GOAWAY.
    options = absi._DEFAULT_GRPC_OPTIONS
    assert options["grpc.keepalive_time_ms"] == 30000
    assert options["grpc.keepalive_permit_without_calls"] is False
    assert options["grpc.http2.max_pings_without_data"] == 0


async def test_insecure_channel_without_options() -> None:
    service = _ConcreteAsyncService(config=_config(), use_secure_channel=False)
    assert service.grpc_channel is not None
    assert service.stub == "the-async-stub"
    await service.grpc_channel.close(grace=None)


async def test_insecure_channel_with_options_merges_defaults() -> None:
    service = _ConcreteAsyncService(
        config=_config(),
        use_secure_channel=False,
        options={("grpc.max_send_message_length", 123)},
    )
    assert service.grpc_channel is not None
    await service.grpc_channel.close(grace=None)


def test_get_secure_channel_builds_credentials() -> None:
    with mock.patch.object(absi.grpc, "ssl_channel_credentials") as creds, mock.patch.object(
        absi.grpc.aio, "secure_channel"
    ) as secure_channel:
        channel = get_secure_channel(host="localhost:50051", cert="cert-bytes", options=[])
    creds.assert_called_once_with(root_certificates="cert-bytes")
    secure_channel.assert_called_once()
    assert channel is secure_channel.return_value


def test_secure_channel_via_init() -> None:
    with mock.patch.object(absi.grpc, "ssl_channel_credentials"), mock.patch.object(
        absi.grpc.aio, "secure_channel"
    ) as secure_channel:
        service = _ConcreteAsyncService(config=_config(cert="my-cert"), use_secure_channel=True)
    assert service.grpc_channel is secure_channel.return_value


def test_secure_channel_missing_cert_raises() -> None:
    with pytest.raises(ValueError, match="No grpc certificate"):
        _ConcreteAsyncService(config=_config(cert=None), use_secure_channel=True)
