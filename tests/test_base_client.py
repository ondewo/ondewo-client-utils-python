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


@pytest.fixture
def config() -> BaseClientConfig:
    """
    Provide a ``BaseClientConfig`` pointing at a local host and port.

    Returns:
        BaseClientConfig:
            Configuration targeting ``localhost:50051``.
    """
    return BaseClientConfig(host="localhost", port="50051")


def test_init_sets_services(config: BaseClientConfig) -> None:
    """Verify that constructing a client initializes its ``services`` attribute."""
    client: _Client = _Client(config=config)
    assert client.services is not None


def test_init_without_services_raises(config: BaseClientConfig) -> None:
    """Verify that a client leaving ``services`` unset raises ``ValueError``."""
    with pytest.raises(ValueError, match="must be defined"):
        _EmptyClient(config=config)


def test_connect_when_already_connected_raises(config: BaseClientConfig) -> None:
    """Verify that connecting while already connected raises ``ConnectionError``."""
    client: _Client = _Client(config=config)
    with pytest.raises(ConnectionError, match="already has an open connection"):
        client.connect(config=config, use_secure_channel=True)


def test_disconnect_closes_channels_and_clears(config: BaseClientConfig) -> None:
    """Verify that disconnecting closes each gRPC channel and clears ``services``."""
    client: _Client = _Client(config=config)
    service: Any = client.services.svc  # type: ignore[union-attr]
    client.disconnect()
    service.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_disconnect_without_services_raises(config: BaseClientConfig) -> None:
    """Verify that disconnecting without ``services`` raises ``AttributeError``."""
    client: _Client = _Client(config=config)
    client.services = None
    with pytest.raises(AttributeError, match="is not defined"):
        client.disconnect()


def test_connect_after_disconnect_reinitializes(config: BaseClientConfig) -> None:
    """Verify that connecting after a disconnect re-initializes ``services``."""
    client: _Client = _Client(config=config)
    client.disconnect()
    assert client.services is None
    client.connect(config=config, use_secure_channel=True)
    assert client.services is not None


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


def _client_with(services: BaseServicesContainer, config: BaseClientConfig) -> _Client:
    """
    Build a connected client and swap in the given services container.

    Args:
        services (BaseServicesContainer):
            The container the client should hold.
        config (BaseClientConfig):
            Configuration for the client.

    Returns:
        _Client:
            A client whose ``services`` is ``services``.
    """
    client: _Client = _Client(config=config)
    client.services = services
    return client


def test_disconnect_closes_inherited_service_channels(config: BaseClientConfig) -> None:
    """Verify a service declared on a parent container is closed too (``__annotations__`` omits it)."""
    parent: Any = _make_service()
    child: Any = _make_service()
    client: _Client = _client_with(_ChildServices(parent_svc=parent, child_svc=child), config)
    client.disconnect()
    parent.grpc_channel.close.assert_called_once_with()
    child.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_a_failing_close_still_closes_the_others_and_clears(config: BaseClientConfig) -> None:
    """Verify one raising ``close()`` neither leaks the other channels nor leaves ``services`` set."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("close failed")
    second: Any = _make_service()
    client: _Client = _client_with(_TwoServices(first=first, second=second), config)
    with pytest.raises(RuntimeError, match="close failed"):
        client.disconnect()
    second.grpc_channel.close.assert_called_once_with()
    assert client.services is None


def test_only_the_first_close_error_is_raised(config: BaseClientConfig) -> None:
    """Verify that when several closes fail, the first error is the one re-raised."""
    first: Any = _make_service()
    first.grpc_channel.close.side_effect = RuntimeError("first")
    second: Any = _make_service()
    second.grpc_channel.close.side_effect = ValueError("second")
    client: _Client = _client_with(_TwoServices(first=first, second=second), config)
    with pytest.raises(RuntimeError, match="first"):
        client.disconnect()
    assert client.services is None


def test_a_shared_channel_is_closed_once(config: BaseClientConfig) -> None:
    """Verify a channel held by two services is closed exactly once."""
    shared: Any = _make_service()
    client: _Client = _client_with(_TwoServices(first=shared, second=shared), config)
    client.disconnect()
    shared.grpc_channel.close.assert_called_once_with()


def test_services_are_cleared_when_a_service_has_no_channel(config: BaseClientConfig) -> None:
    """Verify ``services`` is cleared even when reading a channel raises."""
    client: _Client = _client_with(_TwoServices(first=_make_service(), second=None), config)
    with pytest.raises(AttributeError, match="grpc_channel"):
        client.disconnect()
    assert client.services is None
