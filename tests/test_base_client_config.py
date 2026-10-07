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
import subprocess
import sys
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Union,
)

import orjson
import pytest

from ondewo.utils import base_client_config as module
from ondewo.utils.base_client_config import BaseClientConfig
from tests.test_base_client_config_golden import (
    GOLDEN_PATH,
    PEM,
    REFRESH_TOKEN,
    SECRET,
    Inner,
    KeycloakConfig,
    NestedConfig,
    PipeUnionConfig,
    _without_unset_added_fields,
    all_cases,
)


@dataclass(frozen=True)
class _ConfigWithPassword(BaseClientConfig):
    """
    A downstream-style frozen config subclass carrying an extra credential field.

    Attributes:
        password (str):
            A credential field, as downstream SDK configs declare.
    """

    password: str = ""


class _Color(Enum):
    """An enum-typed field value."""

    RED = "red"


@dataclass(frozen=True)
class _OddFields(BaseClientConfig):
    """
    A subclass exercising the less common field shapes.

    Attributes:
        none_first (Union[None, int]): ``None`` listed first in the union.
        color (Optional[_Color]): An enum.
        anything (Any): Passed through.
        blob (bytes): Not JSON-native.
        computed (str): ``init=False``.
    """

    none_first: Union[None, int] = None
    color: Optional[_Color] = None
    anything: Any = None
    blob: bytes = b""
    computed: str = field(default="derived", init=False)


@dataclass(frozen=True)
class _Required(BaseClientConfig):
    """
    A subclass with a field that has no default (only legal after ``kw_only``).

    Attributes:
        token (str): Mandatory.
    """

    token: str = field(kw_only=True)


def _golden(case_id: str) -> Any:
    """
    Return one recorded dataclasses-json outcome.

    Args:
        case_id (str):
            The case.

    Returns:
        Any:
            The recorded outcome.
    """
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[case_id]


def _keycloak() -> KeycloakConfig:
    """
    Build a fully populated keycloak-style config.

    Returns:
        KeycloakConfig:
            A config carrying a password, a refresh token and a certificate.
    """
    return KeycloakConfig(
        host="localhost",
        port="50055",
        grpc_cert=PEM,
        user_name="user@ondewo.com",
        password=SECRET,
        refresh_token=REFRESH_TOKEN,
    )


class TestBaseClientConfig:
    """Construction, certificate encoding and immutability."""

    def test_host_and_port(self) -> None:
        """Verify that ``host_and_port`` joins host and port with a colon."""
        assert BaseClientConfig(host="localhost", port="50051").host_and_port == "localhost:50051"

    def test_cert_none_stays_none(self) -> None:
        """Verify that an unset ``grpc_cert`` remains ``None`` after init."""
        assert BaseClientConfig(host="localhost", port="50051").grpc_cert is None

    def test_cert_is_encoded_to_bytes(self) -> None:
        """Verify that a provided ``grpc_cert`` string is encoded to ``bytes``."""
        assert BaseClientConfig(host="localhost", port="50051", grpc_cert="my-cert").grpc_cert == b"my-cert"

    def test_is_frozen(self) -> None:
        """Verify that the frozen dataclass forbids attribute assignment."""
        config: BaseClientConfig = BaseClientConfig(host="localhost", port="50051")
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.host = "other"  # type: ignore[misc]


@pytest.mark.parametrize("cert", [None, "PEM", PEM, PEM + "é ✓ 漢"])
class TestSerializationRoundTrip:
    """``to_dict`` / ``to_json`` must give back an equal config, with the PEM carried as text."""

    def test_dict_round_trip(self, cert: Optional[str]) -> None:
        """Verify ``from_dict(to_dict())`` equals the original (it used to give ``b"b'PEM'"``)."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert BaseClientConfig.from_dict(config.to_dict()) == config

    def test_json_round_trip(self, cert: Optional[str]) -> None:
        """Verify ``from_json(to_json())`` equals the original, on the orjson and the json path."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert BaseClientConfig.from_json(config.to_json()) == config
        assert BaseClientConfig.from_json(config.to_json(indent=4), parse_int=int) == config

    def test_json_carries_the_pem_as_text(self, cert: Optional[str]) -> None:
        """Verify the JSON holds the certificate as a string, not a list of byte values."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert json.loads(config.to_json())["grpc_cert"] == cert

    def test_replace_keeps_the_certificate(self, cert: Optional[str]) -> None:
        """Verify ``dataclasses.replace`` works (it used to raise on ``bytes.encode``)."""
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert=cert)
        assert dataclasses.replace(config, host="x").grpc_cert == config.grpc_cert


def test_bytes_certificate_stays_bytes() -> None:
    """Verify a ``bytes`` certificate is accepted and kept unchanged."""
    assert BaseClientConfig(host="h", port="1", grpc_cert=b"PEM").grpc_cert == b"PEM"  # type: ignore[arg-type]


def test_empty_certificate_stays_empty() -> None:
    """Verify an empty-string certificate is left as ``""`` and serialized as ``""``."""
    config: BaseClientConfig = BaseClientConfig(host="", port="", grpc_cert="")
    assert config.grpc_cert == ""
    assert config.to_json() == '{"host":"","port":"","grpc_cert":"","grpc_client_cert":null,"grpc_client_key":null}'
    assert BaseClientConfig.from_json(config.to_json()) == config


def test_the_pem_newlines_are_escaped_in_the_json() -> None:
    """Verify a multi-line PEM is one JSON string with ``\\n`` escapes, not raw line breaks."""
    rendered: str = BaseClientConfig(host="h", port="1", grpc_cert=PEM).to_json()
    assert "\n" not in rendered
    assert "-----BEGIN CERTIFICATE-----\\nMIIBszCCAVmgAwIBAgIU\\n" in rendered


def test_a_subclass_with_a_password_round_trips_through_json() -> None:
    """Verify a frozen subclass inherits the certificate encoder and round-trips through JSON."""
    config: _ConfigWithPassword = _ConfigWithPassword(host="h", port="1", grpc_cert="PEM", password="pw")
    restored: _ConfigWithPassword = _ConfigWithPassword.from_json(config.to_json())
    assert restored == config
    assert type(restored) is _ConfigWithPassword
    assert json.loads(config.to_json())["grpc_cert"] == "PEM"


# region the outcomes that differ from dataclasses-json ON PURPOSE (DELIBERATE_DIFFERENCES)


@pytest.mark.parametrize(
    "name",
    [
        "none",
        "str_cert",
        "bytes_cert",
        "empty_cert",
        "non_ascii",
        "long",
        "int_port",
        "keycloak",
        "pipe_union",
        "nested",
    ],
)
def test_to_json_is_the_same_document_rendered_compact_and_utf8(name: str) -> None:
    """Verify ``to_json()`` is exactly dataclasses-json's document with orjson's compact UTF-8 layout."""
    old: str = _golden(f"{name}.to_json")["result"]
    new: str = _without_unset_added_fields(all_cases()[f"{name}.to_json"]())
    assert new == json.dumps(json.loads(old), separators=(",", ":"), ensure_ascii=False)
    assert json.loads(new) == json.loads(old)
    assert list(json.loads(new)) == list(json.loads(old))  # same key order


@pytest.mark.parametrize("case_id", ["from_dict.missing_mandatory_key", "from_dict.nested_missing_mandatory"])
def test_a_missing_mandatory_field_raises_type_error_instead_of_key_error(case_id: str) -> None:
    """Verify an absent field without a default raises the constructor's ``TypeError`` (was ``KeyError``)."""
    assert _golden(case_id)["error"] == "KeyError"
    with pytest.raises(TypeError, match="missing 1 required"):
        all_cases()[case_id]()


def test_a_missing_keyword_only_field_raises_type_error() -> None:
    """Verify a ``kw_only`` field without a default is mandatory, and supplied it decodes."""
    with pytest.raises(TypeError, match="token"):
        _Required.from_dict({"host": "h", "port": "1"})
    assert _Required.from_dict({"host": "h", "port": "1", "token": 7}).token == "7"


@pytest.mark.parametrize(
    "case_id, received",
    [
        ("from_dict.none", "NoneType"),
        ("from_json.list_document", "list"),
        ("from_json.string_document", "str"),
        ("from_json.null_document", "NoneType"),
    ],
)
def test_a_document_that_is_not_an_object_raises_type_error(case_id: str, received: str) -> None:
    """Verify a non-object document raises a ``TypeError`` naming the class (was ``AttributeError``)."""
    assert _golden(case_id)["error"] == "AttributeError"
    with pytest.raises(TypeError, match=f"BaseClientConfig must be decoded from a JSON object .*not {received}$"):
        all_cases()[case_id]()


def test_a_nested_value_that_is_not_an_object_raises_type_error() -> None:
    """Verify a nested dataclass field given a non-object names the nested class."""
    with pytest.raises(TypeError, match="Inner must be decoded from a JSON object"):
        NestedConfig.from_dict({"host": "h", "port": "1", "inner": "x"})


def test_bytes_given_for_the_certificate_are_kept() -> None:
    """Verify ``from_dict`` keeps ``bytes`` as the constructor does (dataclasses-json made them ``"b'PEM'"``)."""
    assert _golden("from_dict.bytes_cert")["result"]["fields"]["grpc_cert"] == repr(b"b'PEM'")
    restored: BaseClientConfig = BaseClientConfig.from_dict({"host": "h", "port": "1", "grpc_cert": b"PEM"})
    assert restored == BaseClientConfig(host="h", port="1", grpc_cert="PEM")


def test_nan_is_rejected_as_invalid_json() -> None:
    """Verify orjson rejects the non-standard ``NaN`` literal (dataclasses-json fed it to ``int()``)."""
    assert _golden("from_json.nan_into_optional_int")["error"] == "ValueError"
    with pytest.raises(json.JSONDecodeError):
        all_cases()["from_json.nan_into_optional_int"]()


def test_schema_is_gone() -> None:
    """Verify ``schema()`` (a marshmallow schema) is the one removed API."""
    assert not hasattr(BaseClientConfig, "schema")


# endregion

# region edge cases


def test_from_star_builds_the_subclass_and_keeps_it_frozen_equal_and_hashable() -> None:
    """Verify ``from_json`` builds the subclass, which stays frozen, equal, hashable and replaceable."""
    config: KeycloakConfig = _keycloak()
    restored: KeycloakConfig = KeycloakConfig.from_json(config.to_json())
    assert type(restored) is KeycloakConfig
    assert restored == config and hash(restored) == hash(config)
    assert dataclasses.replace(restored, realm="r") == dataclasses.replace(config, realm="r")
    with pytest.raises(dataclasses.FrozenInstanceError):
        restored.password = "x"  # type: ignore[misc]


def test_secrets_never_reach_repr_str_or_an_error_message() -> None:
    """Verify a secret-carrying config redacts in repr/str and that bad input never echoes a value."""
    config: KeycloakConfig = KeycloakConfig.from_json(_keycloak().to_json())
    assert SECRET not in repr(config) and REFRESH_TOKEN not in str(config)
    with pytest.raises(json.JSONDecodeError) as invalid:
        KeycloakConfig.from_json('{"host": "h", "port": "1", "password": "' + SECRET + '", ')
    assert SECRET not in str(invalid.value) and SECRET not in repr(invalid.value)
    with pytest.raises(ValueError) as unconvertible:
        KeycloakConfig.from_dict({"host": "h", "port": "1", "token_expiration_in_s": SECRET})
    assert str(unconvertible.value) == "KeycloakConfig.token_expiration_in_s: a str cannot be converted to int"
    assert unconvertible.value.__cause__ is None and unconvertible.value.__suppress_context__


def test_a_failed_conversion_raising_type_error_is_reported_as_value_error() -> None:
    """Verify ``int([1])`` (a ``TypeError``) surfaces as the same value-free ``ValueError``."""
    with pytest.raises(ValueError, match=r"^KeycloakConfig.token_expiration_in_s: a list cannot be converted to int$"):
        KeycloakConfig.from_dict({"host": "h", "port": "1", "token_expiration_in_s": [1]})


@pytest.mark.parametrize("document", [b'{"host": "h", "port": "1"}', bytearray(b'{"host": "h", "port": "1"}')])
def test_from_json_accepts_bytes(document: Union[bytes, bytearray]) -> None:
    """Verify ``from_json`` takes ``bytes`` / ``bytearray`` (what a file or socket hands over)."""
    assert BaseClientConfig.from_json(document) == BaseClientConfig(host="h", port="1")


@pytest.mark.parametrize("document", ["", "{", '{"host": "h"', "nope", '{"host": "h",}'])
def test_invalid_json_raises_json_decode_error(document: str) -> None:
    """Verify malformed input raises ``json.JSONDecodeError`` (a ``ValueError``), as before."""
    with pytest.raises(json.JSONDecodeError):
        BaseClientConfig.from_json(document)


def test_unicode_and_long_values_round_trip() -> None:
    """Verify non-ASCII and very long values survive both JSON paths unchanged."""
    config: BaseClientConfig = BaseClientConfig(host="hôst-ü.漢.example" * 50, port="1", grpc_cert="é" * 100_000)
    assert BaseClientConfig.from_json(config.to_json()) == config
    assert BaseClientConfig.from_json(config.to_json(ensure_ascii=True)) == config
    assert "\\u00f4" in config.to_json(ensure_ascii=True) and "ô" in config.to_json()


def test_unknown_keys_and_missing_optional_keys() -> None:
    """Verify unknown keys are ignored (newer writer, older reader) and absent ones take defaults."""
    restored: KeycloakConfig = KeycloakConfig.from_json('{"host": "h", "port": "1", "from_the_future": {"a": [1]}}')
    assert restored == KeycloakConfig(host="h", port="1")


def test_the_none_warnings_name_the_field_never_the_value() -> None:
    """Verify ``None`` for a non-optional field warns with dataclasses-json's text, and infer_missing too."""
    with pytest.warns(RuntimeWarning, match="'NoneType' object value of non-optional type host"):
        assert BaseClientConfig.from_dict({"host": None, "port": "1"}).host is None
    with pytest.warns(RuntimeWarning, match="Missing value of non-optional type port .* infer_missing=True"):
        assert BaseClientConfig.from_dict({"host": "h"}, infer_missing=True).port is None


def test_odd_field_shapes() -> None:
    """Verify ``None``-first unions, enums, ``Any``, ``bytes`` and ``init=False`` fields decode as before."""
    restored: _OddFields = _OddFields.from_dict(
        {"host": "h", "port": "1", "none_first": "5", "color": "red", "anything": {"k": [1]}, "computed": "ignored"}
    )
    assert restored.none_first == 5
    assert restored.color is _Color.RED
    assert restored.anything == {"k": [1]}
    assert restored.computed == "derived"
    assert _OddFields.from_dict({"host": "h", "port": "1", "color": _Color.RED}).color is _Color.RED


def test_non_json_leaves_are_rendered_like_dataclasses_json() -> None:
    """Verify ``bytes`` / sets / mapping proxies become lists / dicts on every JSON path."""

    @dataclass(frozen=True)
    class Holder(BaseClientConfig):
        blob: bytes = b"\x01\x02"
        ids: FrozenSet[int] = frozenset({3})
        proxy: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({"a": 1}))

    holder: Holder = Holder(host="h", port="1")
    expected: Dict[str, Any] = {
        "host": "h",
        "port": "1",
        "grpc_cert": None,
        "grpc_client_cert": None,
        "grpc_client_key": None,
        "blob": [1, 2],
        "ids": [3],
        "proxy": {"a": 1},
    }
    assert holder.to_dict()["blob"] == b"\x01\x02"
    assert holder.to_dict(encode_json=True) == expected
    assert json.loads(holder.to_json()) == expected
    assert json.loads(holder.to_json(indent=1)) == expected


def test_a_value_json_cannot_represent_raises_type_error_naming_the_type() -> None:
    """Verify an unrepresentable leaf fails on every path, naming the type and never the value."""

    class Opaque:
        def __repr__(self) -> str:
            return SECRET

    @dataclass(frozen=True)
    class Holder(BaseClientConfig):
        opaque: Any = None

    holder: Holder = Holder(host="h", port="1", opaque=Opaque())
    for render in (holder.to_json, lambda: holder.to_json(indent=2), lambda: holder.to_dict(encode_json=True)):
        with pytest.raises(TypeError) as raised:
            render()
        assert "Opaque" in str(raised.value) and SECRET not in str(raised.value)
    assert isinstance(orjson.JSONEncodeError("x"), TypeError)


def test_nested_dataclasses_and_collections() -> None:
    """Verify nested dataclasses decode from mappings and collections pass through."""
    config: NestedConfig = NestedConfig.from_json(
        '{"host": "h", "port": "1", "inner": {"name": "n"}, "tags": ["a"], "labels": {"k": "v"}}'
    )
    assert config.inner == Inner(name="n") and config.tags == ["a"] and config.labels == {"k": "v"}
    assert NestedConfig.from_dict(config.to_dict()) == config


def test_pep_604_optional_fields_decode() -> None:
    """Verify ``X | None`` fields (the ondewo-vtsi-client shape) coerce and accept ``None``."""
    restored: PipeUnionConfig = PipeUnionConfig.from_dict({"host": "h", "port": 1, "token_expiration_in_s": "9"})
    assert (restored.port, restored.token_expiration_in_s, restored.realm) == ("1", 9, None)


def test_the_certificate_encoder_keeps_dataclasses_json_metadata_shape() -> None:
    """Verify ``grpc_cert`` still carries ``config(encoder=...)``'s exact metadata for ``@dataclass_json`` subclasses."""
    (cert_field,) = [
        config_field for config_field in dataclasses.fields(BaseClientConfig) if config_field.name == "grpc_cert"
    ]
    assert dict(cert_field.metadata) == {"dataclasses_json": {"encoder": module._encode_grpc_cert}}


def test_importing_the_package_loads_neither_dataclasses_json_nor_marshmallow() -> None:
    """Verify the import graph no longer contains dataclasses-json or marshmallow."""
    probe: str = (
        "import sys, ondewo.utils.base_client_config, ondewo.utils.base_services_interface, "
        "ondewo.utils.async_base_services_interface\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in {'dataclasses_json', 'marshmallow'}))"
    )
    loaded: List[str] = json.loads(
        subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True).stdout.replace(
            "'", '"'
        )
    )
    assert loaded == []


# endregion
