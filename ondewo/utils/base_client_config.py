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

import json
from dataclasses import (
    dataclass,
    fields,
)
from typing import (
    Any,
    Dict,
    Mapping,
    Optional,
    Type,
    TypeVar,
)

TBaseClientConfig = TypeVar("TBaseClientConfig", bound="BaseClientConfig")


@dataclass(frozen=True)
class BaseClientConfig:
    """
    Configuration for the ONDEWO python client.

    Serialization helpers (``to_dict`` / ``from_dict`` / ``to_json`` / ``from_json``) are implemented here
    directly rather than being injected by ``dataclasses_json``. Dropping that decorator removes the
    ``dataclasses-json`` -> ``marshmallow`` dependency chain from every ONDEWO client package, which is the
    whole point: the schema machinery it pulled in was never used, only the four helpers below were.

    Compared with the previous ``dataclasses_json`` behaviour:

    * ``to_dict`` / ``to_json`` / ``from_dict`` / ``from_json`` keep their signatures and their semantics —
      unknown keys are ignored on read, and a missing mandatory field still raises. The one difference is the
      exception type: a missing mandatory field now raises ``TypeError`` (the natural error for an absent
      constructor argument) where ``dataclasses_json`` raised ``KeyError``.
    * ``schema()`` is **gone**. It returned a ``marshmallow.Schema`` and cannot exist without marshmallow.
      No ONDEWO client used it.
    * ``to_json`` no longer corrupts ``grpc_cert``. ``__post_init__`` encodes the certificate to ``bytes``,
      and ``dataclasses_json`` serialized those bytes as a list of integers, so a
      ``from_json(to_json(config))`` round trip silently produced ``b"[109, 121, ...]"`` instead of the
      certificate. Bytes are now decoded back to ``str``, so the round trip is lossless.

    Attributes:
        host (str):
            IP address of the ONDEWO QA services host (e.g., 'localhost', '127.22.444.11', etc.)
        port (str):
            Port of the ONDEWO QA services host (e.g., '50444', etc.)
        grpc_cert (Optional[str]):
            The certificate required for setting up a secure gRPC channel. This field must be set unless
            the client is instantiated using `use_secure_channel=False` (not recommended).
    """

    host: str
    port: str
    grpc_cert: Optional[str] = None

    def __post_init__(self) -> None:
        """
        Encode the gRPC certificate to bytes after the frozen dataclass is initialised.

        The certificate is provided as a ``str`` on construction and is transparently encoded to
        ``bytes`` here using ``object.__setattr__`` (required because the dataclass is frozen). If
        ``grpc_cert`` is ``None`` it is left unchanged.

        Returns:
            None:
                This method mutates the instance in place and returns nothing.
        """
        object.__setattr__(self, "grpc_cert", self.grpc_cert.encode() if self.grpc_cert else self.grpc_cert)

    @property
    def host_and_port(self) -> str:
        """
        Return the host and port combined into a single connection string.

        Returns:
            str:
                The host and port in the format ``"host:port"``.
        """
        return f"{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        """
        Return the configuration as a plain, JSON-serializable dictionary.

        ``grpc_cert`` is decoded back to ``str``, because ``__post_init__`` stores it as ``bytes`` and
        ``bytes`` is not JSON-serializable.

        Returns:
            Dict[str, Any]:
                One entry per dataclass field, in declaration order.
        """
        result: Dict[str, Any] = {}
        for config_field in fields(self):
            value: Any = getattr(self, config_field.name)
            result[config_field.name] = value.decode() if isinstance(value, bytes) else value
        return result

    def to_json(self, **kwargs: Any) -> str:
        """
        Serialize the configuration to a JSON string.

        Args:
            **kwargs (Any):
                Additional keyword arguments forwarded to :func:`json.dumps` (e.g. ``indent``).

        Returns:
            str:
                The JSON representation of :meth:`to_dict`.
        """
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls: Type[TBaseClientConfig], kvs: Mapping[str, Any]) -> TBaseClientConfig:
        """
        Build a configuration from a mapping, ignoring keys that are not fields of this class.

        Unknown keys are dropped rather than rejected, so a configuration file written for a newer client
        version still loads on an older one.

        Args:
            kvs (Mapping[str, Any]):
                The field values. Keys that do not name a field of ``cls`` are ignored.

        Returns:
            TBaseClientConfig:
                A new instance of ``cls``.

        Raises:
            TypeError:
                If a mandatory field is absent from ``kvs``.
        """
        field_names = {config_field.name for config_field in fields(cls)}
        return cls(**{key: value for key, value in kvs.items() if key in field_names})

    @classmethod
    def from_json(cls: Type[TBaseClientConfig], s: str, **kwargs: Any) -> TBaseClientConfig:
        """
        Build a configuration from a JSON string.

        Args:
            s (str):
                The JSON document, which must decode to an object.
            **kwargs (Any):
                Additional keyword arguments forwarded to :func:`json.loads`.

        Returns:
            TBaseClientConfig:
                A new instance of ``cls``.

        Raises:
            TypeError:
                If a mandatory field is absent from the decoded object.
            json.JSONDecodeError:
                If ``s`` is not valid JSON.
        """
        return cls.from_dict(json.loads(s, **kwargs))
