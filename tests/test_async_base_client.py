# Copyright 2017-2026 ONDEWO GmbH
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
Async pytest suite for :class:`AsyncBaseClient`.

Exercises service initialisation, the connection/disconnection guards, and gRPC channel
teardown using lightweight in-memory stub clients backed by :mod:`unittest.mock`.
"""

from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Set,
    Tuple,
)
from unittest import mock

import asyncio
import pytest

from ondewo.utils.async_base_client import AsyncBaseClient
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_service_container import BaseServicesContainer
from tests.conftest import local_config


@dataclass
class _Services(BaseServicesContainer):
    """
    Minimal services container exposing a single stub service.

    Attributes:
        svc (Any):
            The stubbed service client, or ``None`` when left unset.
    """

    svc: Any = None


def _make_service() -> Any:
    """
    Build a stub service whose gRPC channel closes via an async mock.

    Returns:
        Any:
            A :class:`unittest.mock.MagicMock` service whose ``grpc_channel.close``
            attribute is an awaitable :class:`unittest.mock.AsyncMock`.
    """
    service: Any = mock.MagicMock()
    service.grpc_channel = mock.MagicMock()
    service.grpc_channel.close = mock.AsyncMock()
    return service


class _AsyncClient(AsyncBaseClient):
    """Concrete async client whose services are initialised with a stub."""

    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Populate ``self.services`` with a single stub service.

        Args:
            config (BaseClientConfig):
                Client configuration (unused by this stub).
            use_secure_channel (bool):
                Whether a secure channel would be used (unused by this stub).
            options (Optional[Set[Tuple[str, Any]]]):
                Optional gRPC channel options (unused by this stub).

        Returns:
            None
        """
        self.services = _Services(svc=_make_service())


class _EmptyAsyncClient(AsyncBaseClient):
    """Concrete async client that never initialises ``services``."""

    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Return without setting ``self.services`` to exercise the guard clause.

        Args:
            config (BaseClientConfig):
                Client configuration (unused by this stub).
            use_secure_channel (bool):
                Whether a secure channel would be used (unused by this stub).
            options (Optional[Set[Tuple[str, Any]]]):
                Optional gRPC channel options (unused by this stub).

        Returns:
            None
        """
        # deliberately leaves ``self.services`` unset to hit the guard clause
        return


def test_init_sets_services() -> None:
    """Verify that constructing a client populates ``services``."""
    client: _AsyncClient = _AsyncClient(config=local_config())
    assert client.services is not None


def test_init_without_services_raises() -> None:
    """Verify that a client leaving ``services`` unset raises ``ValueError``."""
    with pytest.raises(ValueError, match="must be defined"):
        _EmptyAsyncClient(config=local_config())


async def test_connect_when_already_connected_raises() -> None:
    """Verify that connecting an already-connected client raises ``ConnectionError``."""
    client: _AsyncClient = _AsyncClient(config=local_config())
    connected: Any = client.services
    channel: Any = connected.svc.grpc_channel
    with pytest.raises(ConnectionError, match="already has an open connection"):
        await client.connect(config=local_config(), use_secure_channel=True)
    assert client.services is connected
    channel.close.assert_not_awaited()


async def test_disconnect_closes_channels_and_clears() -> None:
    """Verify that disconnecting closes each gRPC channel and clears ``services``."""
    client: _AsyncClient = _AsyncClient(config=local_config())
    service: Any = client.services.svc  # type: ignore[union-attr]
    await client.disconnect()
    service.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_disconnecting_twice_raises() -> None:
    """Verify a second ``disconnect`` raises ``AttributeError`` and does not close the channel again."""
    client: _AsyncClient = _AsyncClient(config=local_config())
    service: Any = client.services.svc  # type: ignore[union-attr]
    await client.disconnect()
    with pytest.raises(AttributeError, match="is not defined"):
        await client.disconnect()
    service.grpc_channel.close.assert_awaited_once_with(grace=None)


async def test_connect_after_disconnect_reinitializes() -> None:
    """Verify that a client can reconnect after a disconnect."""
    client: _AsyncClient = _AsyncClient(config=local_config())
    old_channel: Any = client.services.svc.grpc_channel  # type: ignore[union-attr]
    await client.disconnect()
    assert client.services is None
    await client.connect(config=local_config(), use_secure_channel=True)
    assert client.services is not None
    assert client.services.svc.grpc_channel is not old_channel  # type: ignore[union-attr]


async def test_init_and_connect_forward_every_argument() -> None:
    """Verify ``__init__`` and ``connect`` hand config, channel security and options to ``_initialize_services``."""
    config: BaseClientConfig = local_config()
    with mock.patch.object(
        _AsyncClient, "_initialize_services", autospec=True, side_effect=_AsyncClient._initialize_services
    ) as initialize:
        default: _AsyncClient = _AsyncClient(config=config)
        client: _AsyncClient = _AsyncClient(config=config, use_secure_channel=False, options={("k", 1)})
        await client.disconnect()
        await client.connect(config=config, use_secure_channel=False, options={("k", 2)})
    assert initialize.call_args_list == [
        mock.call(default, config=config, use_secure_channel=True, options=None),
        mock.call(client, config=config, use_secure_channel=False, options={("k", 1)}),
        mock.call(client, config=config, use_secure_channel=False, options={("k", 2)}),
    ]


@dataclass
class _ParentServices(BaseServicesContainer):
    """
    Services container declaring one service, to be extended by a child container.

    Attributes:
        parent_svc (Any):
            A mock service declared on the parent dataclass.
    """

    parent_svc: Any = None


@dataclass
class _ChildServices(_ParentServices):
    """
    Services container inheriting ``parent_svc`` and declaring ``child_svc``.

    Attributes:
        child_svc (Any):
            A mock service declared on the child dataclass.
    """

    child_svc: Any = None


@dataclass
class _TwoServices(BaseServicesContainer):
    """
    Services container with two fields, used for the failing-close and shared-channel cases.

    Attributes:
        first (Any):
            The first mock service.
        second (Any):
            The second mock service.
    """

    first: Any = None
    second: Any = None


def _client_with(services: BaseServicesContainer) -> _AsyncClient:
    """
    Build a connected async client and swap in the given services container.

    Args:
        services (BaseServicesContainer):
            The container the client should hold.

    Returns:
        _AsyncClient:
            A client whose ``services`` is ``services``.
    """
    client: _AsyncClient = _AsyncClient(config=local_config())
    client.services = services
    return client


async def test_disconnect_closes_inherited_service_channels() -> None:
    """Verify a service declared on a parent container is closed too (``__annotations__`` omits it)."""
    parent: Any = _make_service()
    child: Any = _make_service()
    client: _AsyncClient = _client_with(_ChildServices(parent_svc=parent, child_svc=child))
    await client.disconnect()
    parent.grpc_channel.close.assert_awaited_once_with(grace=None)
    child.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_a_failing_close_still_closes_the_others_and_clears() -> None:
    """Verify one raising ``close()`` neither leaks the other channels nor leaves ``services`` set."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("close failed")
    second: Any = _make_service()
    client: _AsyncClient = _client_with(_TwoServices(first=first, second=second))
    with pytest.raises(RuntimeError, match="close failed"):
        await client.disconnect()
    second.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_only_the_first_close_error_is_raised() -> None:
    """Verify that when several closes fail, the first error is the one re-raised."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("first")
    second: Any = _make_service()
    second.grpc_channel.close.side_effect = ValueError("second")
    client: _AsyncClient = _client_with(_TwoServices(first=first, second=second))
    with pytest.raises(RuntimeError, match="first"):
        await client.disconnect()
    assert client.services is None


async def test_a_missing_channel_in_an_earlier_field_still_closes_later_channels() -> None:
    """Verify a field without a channel neither stops the loop nor hides its error."""
    second: Any = _make_service()
    client: _AsyncClient = _client_with(_TwoServices(first=None, second=second))
    with pytest.raises(AttributeError, match="grpc_channel"):
        await client.disconnect()
    second.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_a_cancelled_disconnect_still_closes_every_channel() -> None:
    """Verify a cancellation during one close (e.g. ``asyncio.wait_for``) closes the rest, then propagates."""
    started: asyncio.Event = asyncio.Event()

    async def _hang(grace: Any = None) -> None:
        started.set()
        await asyncio.Event().wait()

    first: Any = _make_service()
    first.grpc_channel.close.side_effect = _hang
    second: Any = _make_service()
    client: _AsyncClient = _client_with(_TwoServices(first=first, second=second))
    task: asyncio.Task = asyncio.ensure_future(client.disconnect())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    second.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None


async def test_a_shared_channel_is_closed_once() -> None:
    """Verify one channel held by two distinct services is closed exactly once."""
    first: Any = _make_service()
    second: Any = _make_service()
    second.grpc_channel = first.grpc_channel
    client: _AsyncClient = _client_with(_TwoServices(first=first, second=second))
    await client.disconnect()
    first.grpc_channel.close.assert_awaited_once_with(grace=None)
    assert client.services is None
