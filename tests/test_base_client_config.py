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

import json

import pytest

from ondewo.utils.base_client_config import BaseClientConfig


class TestBaseClientConfig:
    """
    Test suite verifying the behaviour of :class:`BaseClientConfig`.

    The tests cover host/port composition, gRPC certificate encoding, dataclass
    immutability (``frozen=True``) and the hand-rolled serialization helpers that replaced
    ``dataclasses_json``.
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

    def test_to_dict_returns_every_field(self) -> None:
        """Verify that ``to_dict`` emits one entry per dataclass field.

        Returns:
            None:
                This test returns nothing; it asserts on the serialized mapping.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        assert config.to_dict() == {"host": "localhost", "port": "50051", "grpc_cert": None}

    def test_to_dict_decodes_the_certificate_back_to_str(self) -> None:
        """Verify that the ``bytes`` certificate is decoded so the mapping stays JSON-serializable.

        Returns:
            None:
                This test returns nothing; it asserts on the decoded certificate.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051", grpc_cert="my-cert")
        assert config.to_dict()["grpc_cert"] == "my-cert"

    def test_to_json_serializes_the_mapping(self) -> None:
        """Verify that ``to_json`` produces the JSON form of ``to_dict`` and forwards kwargs.

        Returns:
            None:
                This test returns nothing; it asserts on the JSON document.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        assert json.loads(config.to_json()) == config.to_dict()
        assert "\n" in config.to_json(indent=2)

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """Verify that a mapping carrying unknown keys still loads.

        This keeps a configuration written for a newer client version readable by an older one.

        Returns:
            None:
                This test returns nothing; it asserts on the resulting configuration.
        """
        config: BaseClientConfig = BaseClientConfig.from_dict(
            {"host": "localhost", "port": "50051", "field_from_a_newer_version": 1},
        )
        assert config.host == "localhost"
        assert config.port == "50051"

    def test_from_dict_raises_when_a_mandatory_field_is_missing(self) -> None:
        """Verify that omitting a mandatory field is rejected rather than silently defaulted.

        Returns:
            None:
                This test returns nothing; it asserts that ``TypeError`` is raised.
        """
        with pytest.raises(TypeError):
            BaseClientConfig.from_dict({"port": "50051"})

    def test_from_json_round_trips_including_the_certificate(self) -> None:
        """Verify that ``from_json(to_json(config))`` reproduces the original configuration.

        This is a regression test: ``dataclasses_json`` serialized the ``bytes`` certificate as a list of
        integers, so the round trip used to yield ``b"[109, 121, ...]"`` instead of the certificate.

        Returns:
            None:
                This test returns nothing; it asserts on the round-tripped configuration.
        """
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051", grpc_cert="my-cert")
        restored: BaseClientConfig = BaseClientConfig.from_json(config.to_json())
        assert restored == config
        assert restored.grpc_cert == b"my-cert"
