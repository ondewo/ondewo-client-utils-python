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

from ondewo.utils import base_services_interface as bsi
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_services_interface import (
    MAX_MESSAGE_LENGTH,
    BaseServicesInterface,
    get_secure_channel,
)


class _ConcreteService(BaseServicesInterface):
    @property
    def stub(self) -> Any:
        return "the-stub"


def _config(cert: Any = None) -> BaseClientConfig:
    return BaseClientConfig(host="localhost", port="50051", grpc_cert=cert)


def test_max_message_length_is_int32_max() -> None:
    assert MAX_MESSAGE_LENGTH == 2 ** 31 - 1


def test_keepalive_enabled_only_during_active_calls() -> None:
    # Keepalive pings are on (long-lived streams stay warm, half-open sockets
    # get detected) but only while a call is active, so idle channels never
    # trigger a server "too_many_pings" GOAWAY.
    options = bsi._DEFAULT_GRPC_OPTIONS
    assert options["grpc.keepalive_time_ms"] == 30000
    assert options["grpc.keepalive_permit_without_calls"] is False
    assert options["grpc.http2.max_pings_without_data"] == 0


def test_insecure_channel_without_options() -> None:
    service = _ConcreteService(config=_config(), use_secure_channel=False)
    assert service.grpc_channel is not None
    assert service.stub == "the-stub"


def test_insecure_channel_with_options_merges_defaults() -> None:
    service = _ConcreteService(
        config=_config(),
        use_secure_channel=False,
        options={("grpc.max_send_message_length", 123)},
    )
    assert service.grpc_channel is not None


def test_default_options_are_shared_and_not_reserialized() -> None:
    # The pre-materialized default options list is reused for the no-options path.
    assert bsi._DEFAULT_GRPC_OPTIONS_ITEMS[0][0].startswith("grpc.")
    assert isinstance(bsi._SERVICE_CONFIG_JSON, str)


def test_get_secure_channel_builds_credentials() -> None:
    with mock.patch.object(bsi.grpc, "ssl_channel_credentials") as creds, mock.patch.object(
        bsi.grpc, "secure_channel"
    ) as secure_channel:
        channel = get_secure_channel(host="localhost:50051", cert="cert-bytes", options=[])
    creds.assert_called_once_with(root_certificates="cert-bytes")
    secure_channel.assert_called_once()
    assert channel is secure_channel.return_value


def test_secure_channel_via_init() -> None:
    with mock.patch.object(bsi.grpc, "ssl_channel_credentials"), mock.patch.object(
        bsi.grpc, "secure_channel"
    ) as secure_channel:
        service = _ConcreteService(config=_config(cert="my-cert"), use_secure_channel=True)
    assert service.grpc_channel is secure_channel.return_value


def test_secure_channel_missing_cert_raises() -> None:
    with pytest.raises(ValueError, match="No grpc certificate"):
        _ConcreteService(config=_config(cert=None), use_secure_channel=True)
