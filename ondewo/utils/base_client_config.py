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

"""Data class holding the host, port and gRPC certificate configuration for ONDEWO gRPC clients."""

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Optional,
    Union,
)

from dataclasses_json import (
    config,
    dataclass_json,
)


def _encode_grpc_cert(value: Optional[Union[str, bytes]]) -> Optional[str]:
    """
    Serialize ``grpc_cert`` as PEM text, so ``to_dict`` / ``to_json`` round-trip through ``from_*``.

    Args:
        value (Optional[Union[str, bytes]]):
            The certificate as held by the config (``bytes`` after ``__post_init__``).

    Returns:
        Optional[str]:
            The certificate decoded to ``str``, or ``value`` unchanged if it is not ``bytes``.
    """
    return value.decode() if isinstance(value, bytes) else value


@dataclass_json
@dataclass(frozen=True)
class BaseClientConfig:
    """
    Configuration for the ONDEWO python client.

    Attributes:
        host (str):
            IP address of the ONDEWO QA services host (e.g., 'localhost', '127.22.444.11', etc.)
        port (str):
            Port of the ONDEWO QA services host (e.g., '50444', etc.)
        grpc_cert (Optional[str]):
            The PEM root certificate required for setting up a secure gRPC channel. This field must be
            set unless the client is instantiated using `use_secure_channel=False` (not recommended). A
            ``str`` is encoded to ``bytes`` on construction and ``bytes`` are kept as they are;
            ``to_dict`` / ``to_json`` carry the PEM as text, so ``from_dict`` / ``from_json`` and
            ``dataclasses.replace`` give back an equal config.
    """

    host: str
    port: str
    grpc_cert: Optional[str] = field(default=None, metadata=config(encoder=_encode_grpc_cert))

    def __post_init__(self) -> None:
        """
        Encode the gRPC certificate to bytes after the frozen dataclass is initialised.

        A non-empty ``str`` certificate is encoded to ``bytes`` using ``object.__setattr__`` (required
        because the dataclass is frozen). ``bytes`` (e.g. from ``dataclasses.replace`` on an existing
        config), ``""`` and ``None`` are left unchanged.

        Returns:
            None:
                This method mutates the instance in place and returns nothing.
        """
        if isinstance(self.grpc_cert, str) and self.grpc_cert:
            object.__setattr__(self, "grpc_cert", self.grpc_cert.encode())

    @property
    def host_and_port(self) -> str:
        """
        Return the host and port combined into a single connection string.

        Returns:
            str:
                The host and port in the format ``"host:port"``.
        """
        return f"{self.host}:{self.port}"
