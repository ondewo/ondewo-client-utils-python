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
from ondewo.utils.base_services_interface import BaseServicesInterface


class BaseClient(ABC):
    """
    Abstract base class for ONDEWO clients.

    Attributes:
        services: A container for the service clients initialized by the client.
    """

    def __init__(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool = True,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
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
                Additional options for the gRPC channel.
        """
        pass

    def connect(
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
                Additional options for the gRPC channel.

        Raises:
            ConnectionError: If a connection is already established.
        """
        if self.services:
            raise ConnectionError("The current client already has an open connection.")

        self._initialize_services(
            config=config,
            use_secure_channel=use_secure_channel,
            options=options,
        )

    def disconnect(self) -> None:
        """
        Disconnect all gRPC channels and clear the services.

        Raises:
            AttributeError: If `services` is not defined.
        """
        if not self.services:
            raise AttributeError("The attribute `services` is not defined.")

        for service_name in self.services.__annotations__.keys():
            service: BaseServicesInterface = self.services.__getattribute__(service_name)
            service.grpc_channel.close()

        self.services = None
