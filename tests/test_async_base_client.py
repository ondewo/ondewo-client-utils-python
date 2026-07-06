# Copyright 2017-2024 ONDEWO GmbH
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

from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Set,
    Tuple,
)
from unittest import mock

import pytest

from ondewo.utils.async_base_client import AsyncBaseClient
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_service_container import BaseServicesContainer


@dataclass
class _Services(BaseServicesContainer):
    svc: Any = None


def _make_service() -> Any:
    service = mock.MagicMock()
    service.grpc_channel = mock.MagicMock()
    service.grpc_channel.close = mock.AsyncMock()
    return service


class _AsyncClient(AsyncBaseClient):
    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        self.services = _Services(svc=_make_service())


class _EmptyAsyncClient(AsyncBaseClient):
    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        # deliberately leaves ``self.services`` unset to hit the guard clause
        return


def _config() -> BaseClientConfig:
    return BaseClientConfig(host="localhost", port="50051")


def test_init_sets_services() -> None:
    client = _AsyncClient(config=_config())
    assert client.services is not None


def test_init_without_services_raises() -> None:
    with pytest.raises(ValueError, match="must be defined"):
        _EmptyAsyncClient(config=_config())


async def test_connect_when_already_connected_raises() -> None:
    client = _AsyncClient(config=_config())
    with pytest.raises(ConnectionError, match="already has an open connection"):
        await client.connect(config=_config(), use_secure_channel=True)


async def test_disconnect_closes_channels_and_clears() -> None:
    client = _AsyncClient(config=_config())
    service = client.services.svc  # type: ignore[union-attr]
    await client.disconnect()
    service.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_disconnect_without_services_raises() -> None:
    client = _AsyncClient(config=_config())
    client.services = None
    with pytest.raises(AttributeError, match="is not defined"):
        await client.disconnect()


async def test_connect_after_disconnect_reinitializes() -> None:
    client = _AsyncClient(config=_config())
    await client.disconnect()
    assert client.services is None
    await client.connect(config=_config(), use_secure_channel=True)
    assert client.services is not None
