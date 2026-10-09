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
Abstract base class for asynchronous ONDEWO gRPC Python clients.

Provides the async counterpart of ``BaseClient`` with awaitable ``connect`` and
``disconnect`` methods that manage the lifecycle of the underlying gRPC channels.
"""

import dataclasses
from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Any,
    Optional,
    Set,
    Tuple,
)

from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_service_container import BaseServicesContainer


class AsyncBaseClient(ABC):
    """
    Abstract base class for async ONDEWO clients.

    Attributes:
        services: A container for the service clients initialized by the client.
    """

    def __init__(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool = True,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Initialize the async client and its service clients.

        Args:
            config (BaseClientConfig):
                Configuration for the client.
            use_secure_channel (bool):
                Whether to use a secure gRPC channel. Defaults to ``True``.
            options (Optional[Set[Tuple[str, Any]]]):
                Additional options for the gRPC channel. Defaults to ``None``.

        Raises:
            ValueError:
                If the ``services`` attribute is not defined after initialization.
        """
        self.services: Optional[BaseServicesContainer] = None
        self._initialize_services(
            config=config,
            use_secure_channel=use_secure_channel,
            options=options,
        )

        if not self.services:
            raise ValueError(f"The attribute `services` must be defined in class {self.__class__.__name__}.")

    @abstractmethod
    def _initialize_services(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Initialize the service clients.

        Args:
            config (BaseClientConfig):
                Configuration for the client.
            use_secure_channel (bool):
                Whether to use a secure gRPC channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Additional options for the gRPC channel. Defaults to ``None``.
        """
        pass

    async def connect(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Establish a connection to the services.

        Args:
            config (BaseClientConfig):
                Configuration for the client.
            use_secure_channel (bool):
                Whether to use a secure gRPC channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Additional options for the gRPC channel. Defaults to ``None``.

        Raises:
            ConnectionError:
                If a connection is already established.
        """
        if self.services:
            raise ConnectionError("The current client already has an open connection.")

        self._initialize_services(
            config=config,
            use_secure_channel=use_secure_channel,
            options=options,
        )

    async def disconnect(self) -> None:
        """
        Asynchronously close every service's gRPC channel and clear the services.

        Every field of the services dataclass is visited, inherited ones included, and a channel
        shared by several services (see ``build_shared_channel``) is closed exactly once. A
        ``close()`` that raises, or a cancellation / interrupt during one, does not leave the
        remaining channels open: every channel is attempted, ``services`` is cleared regardless,
        and the first error (``CancelledError`` included) is re-raised.

        Raises:
            AttributeError:
                If the ``services`` attribute is not defined.
            Exception:
                The first exception raised by a channel's ``close()``, after all channels were
                attempted.
        """
        if not self.services:
            raise AttributeError("The attribute `services` is not defined.")

        first_error: Optional[BaseException] = None
        closed: Set[int] = set()
        try:
            # dataclasses.fields() and not __annotations__: on Python 3.14 an instance has no
            # __annotations__ (PEP 649), and on every version __annotations__ omits the fields a
            # parent container declares, so their channels leaked.
            for service_field in dataclasses.fields(self.services):
                # The lookup sits inside the try too: a field without a channel (e.g. None) must not
                # leave the channels of the fields after it open.
                try:
                    channel: Any = getattr(self.services, service_field.name).grpc_channel
                    if id(channel) in closed:
                        continue
                    closed.add(id(channel))
                    await channel.close(grace=None)
                # BaseException: a CancelledError (asyncio.wait_for, shutdown) or KeyboardInterrupt
                # must not leave the remaining channels open; it is re-raised after the loop.
                except BaseException as error:
                    first_error = first_error or error
        finally:
            self.services = None
        if first_error is not None:
            raise first_error
