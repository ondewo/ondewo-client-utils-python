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
import json
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

        # https://github.com/grpc/grpc-proto/blob/master/grpc/service_config/service_config.proto
        service_config_json: str = json.dumps(
            {
                "methodConfig": [
                    {
                        "name": [
                            # To apply retry to all methods, put [{}] in the "name" field
                            {}
                            # For a specific set of services and endpoint calls
                            # {"service": "<package>.<service>", "method": "<rpc endpoint>"}
                            # For example:
                            #  {"service": "ondewo.nlu.Users", "method": "Login"}
                        ],
                        "retryPolicy": {
                            "maxAttempts": 10,
                            "initialBackoff": "0.1s",
                            "maxBackoff": "3s",
                            "backoffMultiplier": 2,
                            "retryableStatusCodes": [
                                grpc.StatusCode.CANCELLED.name,
                                grpc.StatusCode.UNKNOWN.name,
                                grpc.StatusCode.DEADLINE_EXCEEDED.name,
                                grpc.StatusCode.NOT_FOUND.name,
                                grpc.StatusCode.RESOURCE_EXHAUSTED.name,
                                grpc.StatusCode.ABORTED.name,
                                grpc.StatusCode.INTERNAL.name,
                                grpc.StatusCode.UNAVAILABLE.name,
                                grpc.StatusCode.DATA_LOSS.name,
                            ],
                        },
                    }
                ]
            }
        )

        default_options: Dict[str, Any] = {
            "grpc.max_send_message_length": MAX_MESSAGE_LENGTH,
            "grpc.max_receive_message_length": MAX_MESSAGE_LENGTH,
            "grpc.keepalive_time_ms": 2 ** 31 - 1,
            "grpc.keepalive_timeout_ms": 60000,
            "grpc.keepalive_permit_without_calls": False,
            "grpc.http2.max_pings_without_data": 2,
            "grpc.dns_enable_srv_queries": 1,
            "grpc.enable_retries": 1,
            "grpc.service_config": service_config_json,
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
