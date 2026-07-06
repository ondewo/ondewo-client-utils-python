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

from ondewo.utils.base_client_config import BaseClientConfig


class TestBaseClientConfig:
    def test_host_and_port(self) -> None:
        config = BaseClientConfig(host="localhost", port="50051")
        assert config.host_and_port == "localhost:50051"

    def test_cert_none_stays_none(self) -> None:
        config = BaseClientConfig(host="localhost", port="50051")
        assert config.grpc_cert is None

    def test_cert_is_encoded_to_bytes(self) -> None:
        config = BaseClientConfig(host="localhost", port="50051", grpc_cert="my-cert")
        assert config.grpc_cert == b"my-cert"

    def test_is_frozen(self) -> None:
        config = BaseClientConfig(host="localhost", port="50051")
        # dataclass(frozen=True) forbids attribute assignment
        try:
            config.host = "other"  # type: ignore[misc]
        except Exception as exc:  # dataclasses raises FrozenInstanceError
            assert exc.__class__.__name__ == "FrozenInstanceError"
        else:  # pragma: no cover
            raise AssertionError("expected the config to be frozen")

    def test_dataclass_json_roundtrip(self) -> None:
        config = BaseClientConfig(host="localhost", port="50051")
        # dataclass_json adds to_json / from_dict helpers
        assert config.to_dict()["host"] == "localhost"  # type: ignore[attr-defined]
