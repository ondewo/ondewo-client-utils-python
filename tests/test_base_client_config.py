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

"""Unit tests for :class:`ondewo.utils.base_client_config.BaseClientConfig`."""

import dataclasses
import json
from dataclasses import dataclass
from typing import Optional

import pytest
from dataclasses_json import dataclass_json

from ondewo.utils.base_client_config import BaseClientConfig


@dataclass_json
@dataclass(frozen=True)
class _ConfigWithPassword(BaseClientConfig):
    """
    A downstream-style frozen config subclass carrying an extra credential field.

    Attributes:
        password (str):
            A credential field, as downstream SDK configs declare.
    """

    password: str = ""


class TestBaseClientConfig:
    """
    Test suite verifying the behaviour of :class:`BaseClientConfig`.

    The tests cover host/port composition, gRPC certificate encoding, dataclass
    immutability (``frozen=True``) and the ``dataclass_json`` serialization helpers.
    """

    def test_host_and_port(self) -> None:
        """Verify that ``host_and_port`` joins host and port with a colon.

        Returns:
            None:
                This test returns nothing; it asserts on the composed value.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        assert config.host_and_port == "localhost:50051"

    def test_cert_none_stays_none(self) -> None:
        """Verify that an unset ``grpc_cert`` remains ``None`` after init.

        Returns:
            None:
                This test returns nothing; it asserts on the certificate value.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        assert config.grpc_cert is None

    def test_cert_is_encoded_to_bytes(self) -> None:
        """Verify that a provided ``grpc_cert`` string is encoded to ``bytes``.

        Returns:
            None:
                This test returns nothing; it asserts on the encoded certificate.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051", grpc_cert="my-cert")
        assert config.grpc_cert == b"my-cert"

    def test_is_frozen(self) -> None:
        """Verify that the frozen dataclass forbids attribute assignment.

        Returns:
            None:
                This test returns nothing; it asserts a ``FrozenInstanceError`` is raised.

        Raises:
            AssertionError:
                If assigning to an attribute does not raise ``FrozenInstanceError``.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        # dataclass(frozen=True) forbids attribute assignment
        try:
            config.host = "other"  # type: ignore[misc]
        except Exception as exc:  # dataclasses raises FrozenInstanceError
            assert exc.__class__.__name__ == "FrozenInstanceError"
        else:  # pragma: no cover
            raise AssertionError("expected the config to be frozen")


@pytest.mark.parametrize("cert", [None, "PEM"])
class TestSerializationRoundTrip:
    """``to_dict`` / ``to_json`` must give back an equal config, with the PEM carried as text."""

    def test_dict_round_trip(self, cert: Optional[str]) -> None:
        """Verify ``from_dict(to_dict())`` equals the original (it used to give ``b"b'PEM'"``)."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert BaseClientConfig.from_dict(config.to_dict()) == config  # type: ignore[attr-defined]

    def test_json_round_trip(self, cert: Optional[str]) -> None:
        """Verify ``from_json(to_json())`` equals the original (it used to give a byte-list PEM)."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert BaseClientConfig.from_json(config.to_json()) == config  # type: ignore[attr-defined]

    def test_json_carries_the_pem_as_text(self, cert: Optional[str]) -> None:
        """Verify the JSON holds the certificate as a string, not a list of byte values."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert json.loads(config.to_json())["grpc_cert"] == cert  # type: ignore[attr-defined]

    def test_replace_keeps_the_certificate(self, cert: Optional[str]) -> None:
        """Verify ``dataclasses.replace`` works (it used to raise on ``bytes.encode``)."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert dataclasses.replace(config, host="x").grpc_cert == config.grpc_cert


def test_bytes_certificate_stays_bytes() -> None:
    """Verify a ``bytes`` certificate is accepted and kept unchanged."""
    assert BaseClientConfig(host="h", port="1", grpc_cert=b"PEM").grpc_cert == b"PEM"  # type: ignore[arg-type]


def test_empty_certificate_stays_empty() -> None:
    """Verify an empty-string certificate is left as ``""``."""
    assert BaseClientConfig(host="h", port="1", grpc_cert="").grpc_cert == ""


def test_a_subclass_with_a_password_round_trips_through_json() -> None:
    """Verify a frozen subclass inherits the certificate encoder and round-trips through JSON."""
    config: _ConfigWithPassword = _ConfigWithPassword(host="h", port="1", grpc_cert="PEM", password="pw")
    assert _ConfigWithPassword.from_json(config.to_json()) == config  # type: ignore[attr-defined]
    assert json.loads(config.to_json())["grpc_cert"] == "PEM"  # type: ignore[attr-defined]
