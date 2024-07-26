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
import struct
from abc import (
    ABC,
    abstractmethod,
)
from logging import warning
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

import grpc

from ondewo.utils.base_client_config import BaseClientConfig

MAX_MESSAGE_LENGTH = 2 ** (struct.Struct("i").size * 8 - 1) - 1


def get_secure_channel(
    host: str,
    cert: str,
    options: Optional[List[Tuple[str, Any]]] = None,
) -> grpc.Channel:
    credentials = grpc.ssl_channel_credentials(root_certificates=cert)
    return grpc.secure_channel(
        target=host,
        credentials=credentials,
        options=options,
    )


def _get_grpc_channel(
    config: BaseClientConfig,
    use_secure_channel: bool,
    options: Optional[List[Tuple[str, Any]]] = None,
) -> grpc.Channel:
    if not use_secure_channel:
        warning("Using insecure grpc channel.")
        return grpc.insecure_channel(target=config.host_and_port, options=options)

    if not config.grpc_cert:
        raise ValueError(f"No grpc certificate found on config {config}.")

    return get_secure_channel(
        host=config.host_and_port,
        cert=config.grpc_cert,
        options=options,
    )


class BaseServicesInterface(ABC):
    def __init__(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        default_options: Dict[str, Any] = {
            "grpc.max_send_message_length": MAX_MESSAGE_LENGTH,
            "grpc.max_receive_message_length": MAX_MESSAGE_LENGTH,
        }

        if options:
            default_options.update(dict(options))

        updated_options: List[Tuple[str, Any]] = list(default_options.items())

        self.grpc_channel: grpc.Channel = _get_grpc_channel(
            config=config,
            use_secure_channel=use_secure_channel,
            options=updated_options,
        )

    @property
    @abstractmethod
    def stub(self) -> Any:
        pass
