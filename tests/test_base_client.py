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
Unit tests for the ``BaseClient`` abstract base class.

Exercises service initialization, connection, and disconnection behavior using
lightweight concrete subclasses backed by mock services.
"""

from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Set,
    Tuple,
)
from unittest import mock

import pytest

from ondewo.utils.base_client import BaseClient
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_service_container import BaseServicesContainer
from tests.conftest import local_config


@dataclass
class _Services(BaseServicesContainer):
    """
    Concrete services container used by the test clients.

    Attributes:
        svc (Any):
            A single mock service exposing a ``grpc_channel`` attribute.
    """

    svc: Any = None


def _make_service() -> Any:
    """
    Create a mock service with a mock gRPC channel.

    Returns:
        Any:
            A mock service whose ``grpc_channel`` attribute is itself a mock,
            allowing assertions on channel interactions such as ``close``.
    """
    service: mock.MagicMock = mock.MagicMock()
    service.grpc_channel = mock.MagicMock()
    return service


class _Client(BaseClient):
    """
    Concrete ``BaseClient`` subclass that populates ``services`` on initialization.
    """

    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Initialize ``services`` with a single mock service.

        Args:
            config (BaseClientConfig):
                Configuration for the client.
            use_secure_channel (bool):
                Whether to use a secure gRPC channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Additional options for the gRPC channel.

        Returns:
            None
        """
        self.services = _Services(svc=_make_service())


class _EmptyClient(BaseClient):
    """
    Concrete ``BaseClient`` subclass that never sets ``services``.

    Used to exercise the guard clause that raises when ``services`` remains undefined.
    """

    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Deliberately leave ``services`` unset to hit the guard clause.

        Args:
            config (BaseClientConfig):
                Configuration for the client.
            use_secure_channel (bool):
                Whether to use a secure gRPC channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Additional options for the gRPC channel.

        Returns:
            None
        """
        # deliberately leaves ``self.services`` unset to hit the guard clause
        return


def test_init_sets_services() -> None:
    """Verify that constructing a client initializes its ``services`` attribute."""
    client: _Client = _Client(config=local_config())
    assert client.services is not None


def test_init_without_services_raises() -> None:
    """Verify that a client leaving ``services`` unset raises ``ValueError``."""
    with pytest.raises(ValueError, match="must be defined"):
        _EmptyClient(config=local_config())


def test_connect_when_already_connected_raises() -> None:
    """Verify that connecting while already connected raises ``ConnectionError``."""
    client: _Client = _Client(config=local_config())
    connected: Any = client.services
    channel: Any = connected.svc.grpc_channel
    with pytest.raises(ConnectionError, match="already has an open connection"):
        client.connect(config=local_config(), use_secure_channel=True)
    assert client.services is connected
    channel.close.assert_not_called()


def test_disconnect_closes_channels_and_clears() -> None:
    """Verify that disconnecting closes each gRPC channel and clears ``services``."""
    client: _Client = _Client(config=local_config())
    service: Any = client.services.svc  # type: ignore[union-attr]
    client.disconnect()
    service.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_disconnecting_twice_raises() -> None:
    """Verify a second ``disconnect`` raises ``AttributeError`` and does not close the channel again."""
    client: _Client = _Client(config=local_config())
    service: Any = client.services.svc  # type: ignore[union-attr]
    client.disconnect()
    with pytest.raises(AttributeError, match="is not defined"):
        client.disconnect()
    service.grpc_channel.close.assert_called_once_with()


def test_connect_after_disconnect_reinitializes() -> None:
    """Verify that connecting after a disconnect re-initializes ``services``."""
    client: _Client = _Client(config=local_config())
    old_channel: Any = client.services.svc.grpc_channel  # type: ignore[union-attr]
    client.disconnect()
    assert client.services is None
    client.connect(config=local_config(), use_secure_channel=True)
    assert client.services is not None
    assert client.services.svc.grpc_channel is not old_channel  # type: ignore[union-attr]


def test_init_and_connect_forward_every_argument() -> None:
    """Verify ``__init__`` and ``connect`` hand config, channel security and options to ``_initialize_services``."""
    config: BaseClientConfig = local_config()
    with mock.patch.object(
        _Client, "_initialize_services", autospec=True, side_effect=_Client._initialize_services
    ) as initialize:
        default: _Client = _Client(config=config)
        client: _Client = _Client(config=config, use_secure_channel=False, options={("k", 1)})
        client.disconnect()
        client.connect(config=config, use_secure_channel=False, options={("k", 2)})
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


def _client_with(services: BaseServicesContainer) -> _Client:
    """
    Build a connected client and swap in the given services container.

    Args:
        services (BaseServicesContainer):
            The container the client should hold.

    Returns:
        _Client:
            A client whose ``services`` is ``services``.
    """
    client: _Client = _Client(config=local_config())
    client.services = services
    return client


def test_disconnect_closes_inherited_service_channels() -> None:
    """Verify a service declared on a parent container is closed too (``__annotations__`` omits it)."""
    parent: Any = _make_service()
    child: Any = _make_service()
    client: _Client = _client_with(_ChildServices(parent_svc=parent, child_svc=child))
    client.disconnect()
    parent.grpc_channel.close.assert_called_once_with()
    child.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_a_failing_close_still_closes_the_others_and_clears() -> None:
    """Verify one raising ``close()`` neither leaks the other channels nor leaves ``services`` set."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("close failed")
    second: Any = _make_service()
    client: _Client = _client_with(_TwoServices(first=first, second=second))
    with pytest.raises(RuntimeError, match="close failed"):
        client.disconnect()
    second.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_only_the_first_close_error_is_raised() -> None:
    """Verify that when several closes fail, the first error is the one re-raised."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("first")
    second: Any = _make_service()
    second.grpc_channel.close.side_effect = ValueError("second")
    client: _Client = _client_with(_TwoServices(first=first, second=second))
    with pytest.raises(RuntimeError, match="first"):
        client.disconnect()
    assert client.services is None


def test_a_missing_channel_in_an_earlier_field_still_closes_later_channels() -> None:
    """Verify a field without a channel neither stops the loop nor hides its error."""
    second: Any = _make_service()
    client: _Client = _client_with(_TwoServices(first=None, second=second))
    with pytest.raises(AttributeError, match="grpc_channel"):
        client.disconnect()
    second.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_an_interrupt_during_one_close_still_closes_the_rest() -> None:
    """Verify a ``KeyboardInterrupt`` in one close leaves no later channel open and still propagates."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = KeyboardInterrupt
    second: Any = _make_service()
    client: _Client = _client_with(_TwoServices(first=first, second=second))
    with pytest.raises(KeyboardInterrupt):
        client.disconnect()
    second.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_a_shared_channel_is_closed_once() -> None:
    """Verify one channel held by two distinct services is closed exactly once."""
    first: Any = _make_service()
    second: Any = _make_service()
    second.grpc_channel = first.grpc_channel
    client: _Client = _client_with(_TwoServices(first=first, second=second))
    client.disconnect()
    first.grpc_channel.close.assert_called_once_with()
    assert client.services is None
