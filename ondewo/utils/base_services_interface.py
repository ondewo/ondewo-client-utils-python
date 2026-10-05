# Copyright 2020-2026 ONDEWO GmbH
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
"""Synchronous gRPC channel helpers and the base service interface for ONDEWO clients.

Provides secure and insecure ``grpc.Channel`` factory helpers, the shared default channel
options (maximum message sizes, keepalive settings and the retry policy), and the
:class:`BaseServicesInterface` abstract base class from which every synchronous ONDEWO
gRPC service client derives.
"""

import struct
from abc import (
    ABC,
    abstractmethod,
)
from functools import lru_cache
from logging import warning
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

import grpc

from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.grpc_retry_policy import (
    build_service_config_json,
    service_config_json_for,
)

MAX_MESSAGE_LENGTH: int = 2 ** (struct.Struct("i").size * 8 - 1) - 1

# The default channel options are constant and assembled once at import time so that
# building a client with many services stays cheap (ultra low latency). The retry policy is
# per service: only idempotent methods are retried (see ``ondewo.utils.grpc_retry_policy``).
# ``_SERVICE_CONFIG_JSON`` is the config for a class whose services cannot be found, i.e. no
# method retried beyond gRPC's transparent retries; ``_grpc_options_items_for`` swaps in the
# per-class config, built once per class and cached.
_SERVICE_CONFIG_JSON: str = build_service_config_json([])

_DEFAULT_GRPC_OPTIONS: Dict[str, Any] = {
    "grpc.max_send_message_length": MAX_MESSAGE_LENGTH,
    "grpc.max_receive_message_length": MAX_MESSAGE_LENGTH,
    # Keepalive keeps long-lived streaming RPCs warm and detects half-open
    # connections. Pings fire only during active calls (permit_without_calls
    # stays False) to avoid a server "too_many_pings" GOAWAY on idle channels;
    # max_pings_without_data=0 lets pings continue through silent stream gaps.
    "grpc.keepalive_time_ms": 30000,
    "grpc.keepalive_timeout_ms": 60000,
    "grpc.keepalive_permit_without_calls": False,
    "grpc.http2.max_pings_without_data": 0,
    "grpc.dns_enable_srv_queries": 1,
    "grpc.enable_retries": 1,
    "grpc.service_config": _SERVICE_CONFIG_JSON,
}


@lru_cache(maxsize=None)
def _grpc_options_items_for(service_class: type) -> List[Tuple[str, Any]]:
    """
    Return the default channel options for a service-interface class, built once per class.

    Args:
        service_class (type):
            The concrete service-interface class being instantiated.

    Returns:
        List[Tuple[str, Any]]:
            The default options with ``grpc.service_config`` set to the class's retry policy.
    """
    options: Dict[str, Any] = dict(_DEFAULT_GRPC_OPTIONS)
    options["grpc.service_config"] = service_config_json_for(service_class)
    return list(options.items())


def get_secure_channel(
    host: str,
    cert: Union[str, bytes],
    options: Optional[List[Tuple[str, Any]]] = None,
) -> grpc.Channel:
    """
    Create a secure (TLS) gRPC channel to the given host.

    Args:
        host (str):
            Target host in ``"host:port"`` form to connect to.
        cert (Union[str, bytes]):
            Root certificate used to verify the server. A ``str`` is encoded to ``bytes``
            before being handed to gRPC; ``BaseClientConfig.__post_init__`` already supplies
            ``bytes``.
        options (Optional[List[Tuple[str, Any]]]):
            Optional gRPC channel options as ``(key, value)`` pairs. Defaults to ``None``.

    Returns:
        grpc.Channel:
            A secure channel configured with the supplied credentials and options.
    """
    root_certificates: bytes = cert.encode() if isinstance(cert, str) else cert
    credentials: grpc.ChannelCredentials = grpc.ssl_channel_credentials(root_certificates=root_certificates)
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
    """
    Build a gRPC channel for the given client configuration.

    Args:
        config (BaseClientConfig):
            Client configuration providing the host, port and optional gRPC certificate.
        use_secure_channel (bool):
            If ``True`` build a secure (TLS) channel; if ``False`` build an insecure channel.
        options (Optional[List[Tuple[str, Any]]]):
            Optional gRPC channel options as ``(key, value)`` pairs. Defaults to ``None``.

    Returns:
        grpc.Channel:
            A secure or insecure channel depending on ``use_secure_channel``.

    Raises:
        ValueError:
            If a secure channel is requested but ``config.grpc_cert`` is not set.
    """
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
    """
    Abstract base class for synchronous ONDEWO gRPC service clients.

    Sets up the shared ``grpc.Channel`` used to talk to a service and requires subclasses
    to expose the concrete service ``stub``.

    Attributes:
        grpc_channel (grpc.Channel):
            The gRPC channel connecting to the configured service host.
    """

    def __init__(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Initialize the interface and open the underlying gRPC channel.

        Args:
            config (BaseClientConfig):
                Client configuration providing the host, port and optional gRPC certificate.
            use_secure_channel (bool):
                If ``True`` open a secure (TLS) channel; if ``False`` open an insecure channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Optional gRPC channel option overrides as ``(key, value)`` pairs merged on top of
                the default options. Defaults to ``None``, in which case the default options are
                used unchanged. Passing ``("grpc.service_config", <json>)`` replaces the default
                retry policy, which retries idempotent methods only (see
                ``ondewo.utils.grpc_retry_policy``).

        Returns:
            None
        """
        default_options: List[Tuple[str, Any]] = _grpc_options_items_for(type(self))
        if options:
            merged_options: Dict[str, Any] = dict(default_options)
            merged_options.update(dict(options))
            updated_options: List[Tuple[str, Any]] = list(merged_options.items())
        else:
            updated_options = default_options

        self.grpc_channel: grpc.Channel = _get_grpc_channel(
            config=config,
            use_secure_channel=use_secure_channel,
            options=updated_options,
        )

    @property
    @abstractmethod
    def stub(self) -> Any:
        """
        Return the concrete gRPC service stub.

        Returns:
            Any:
                The service-specific gRPC stub used to issue RPCs.
        """
        pass
