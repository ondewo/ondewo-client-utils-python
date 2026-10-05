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
"""Async gRPC service interface base classes and channel factory helpers.

Async counterpart of ``base_services_interface`` built on ``grpc.aio``: it
provides channel factory helpers and the abstract ``AsyncBaseServicesInterface``.
"""

import logging
import struct
from abc import (
    ABC,
    abstractmethod,
)
from functools import lru_cache
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

# A module logger, never the root one: logging.warning() at module level runs basicConfig() and
# installs a stderr handler on the HOST application's root logger.
_LOGGER: logging.Logger = logging.getLogger(__name__)

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
) -> grpc.aio.Channel:
    """
    Create a secure asynchronous gRPC channel to the given host.

    Args:
        host (str):
            Target address in the form "host:port" to connect to.
        cert (Union[str, bytes]):
            Root certificate used to establish the TLS connection. A ``str`` is encoded to
            ``bytes`` before being handed to gRPC; ``BaseClientConfig.__post_init__`` already
            supplies ``bytes``.
        options (Optional[List[Tuple[str, Any]]]):
            Optional list of gRPC channel options as (key, value) tuples.

    Returns:
        grpc.aio.Channel:
            A secure asynchronous gRPC channel connected to the target host.
    """
    root_certificates: bytes = cert.encode() if isinstance(cert, str) else cert
    credentials: grpc.ChannelCredentials = grpc.ssl_channel_credentials(root_certificates=root_certificates)
    return grpc.aio.secure_channel(
        target=host,
        credentials=credentials,
        options=options,
    )


def _get_grpc_channel(
    config: BaseClientConfig,
    use_secure_channel: bool,
    options: Optional[List[Tuple[str, Any]]] = None,
) -> grpc.aio.Channel:
    """
    Build an asynchronous gRPC channel, secure or insecure, from a client config.

    Args:
        config (BaseClientConfig):
            Client configuration providing the host, port and optional certificate.
        use_secure_channel (bool):
            Whether to create a secure (TLS) channel. If False an insecure channel
            is created instead.
        options (Optional[List[Tuple[str, Any]]]):
            Optional list of gRPC channel options as (key, value) tuples.

    Returns:
        grpc.aio.Channel:
            A secure or insecure asynchronous gRPC channel.

    Raises:
        ValueError:
            If a secure channel is requested but the config has no gRPC certificate.
    """
    if not use_secure_channel:
        _LOGGER.warning("Using an INSECURE (plaintext) gRPC channel to %s.", config.host_and_port)
        return grpc.aio.insecure_channel(target=config.host_and_port, options=options)

    if not config.grpc_cert:
        # Never interpolate the config itself: a downstream subclass may carry a password field.
        raise ValueError(
            f"No grpc certificate found on {type(config).__name__} for {config.host_and_port}; "
            "pass grpc_cert or use_secure_channel=False."
        )

    return get_secure_channel(
        host=config.host_and_port,
        cert=config.grpc_cert,
        options=options,
    )


class AsyncBaseServicesInterface(ABC):
    """
    Abstract base class for async ONDEWO gRPC service interfaces.

    Attributes:
        grpc_channel (grpc.aio.Channel):
            The asynchronous gRPC channel used to communicate with the service.
    """

    def __init__(
        self,
        config: BaseClientConfig,
        use_secure_channel: bool,
        options: Optional[Set[Tuple[str, Any]]] = None,
    ) -> None:
        """
        Initialize the async service interface and open its gRPC channel.

        Args:
            config (BaseClientConfig):
                Client configuration providing the host, port and optional certificate.
            use_secure_channel (bool):
                Whether to create a secure (TLS) channel.
            options (Optional[Set[Tuple[str, Any]]]):
                Optional set of gRPC channel options as (key, value) tuples that
                override the default options. Passing ``("grpc.service_config", <json>)``
                replaces the default retry policy, which retries idempotent methods only (see
                ``ondewo.utils.grpc_retry_policy``).
        """

        default_options: List[Tuple[str, Any]] = _grpc_options_items_for(type(self))
        if options:
            merged_options: Dict[str, Any] = dict(default_options)
            merged_options.update(dict(options))
            updated_options: List[Tuple[str, Any]] = list(merged_options.items())
        else:
            updated_options = default_options

        self.grpc_channel: grpc.aio.Channel = _get_grpc_channel(
            config=config,
            use_secure_channel=use_secure_channel,
            options=updated_options,
        )

    @property
    @abstractmethod
    def stub(self) -> Any:
        """
        Return the concrete gRPC stub used to issue RPC calls.

        Returns:
            Any:
                The gRPC service stub implemented by the concrete subclass.
        """
        pass
