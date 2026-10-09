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

import ipaddress
import json
import warnings
from collections.abc import (
    Collection,
    Mapping,
)
from dataclasses import (
    MISSING,
    dataclass,
    field,
    fields,
    is_dataclass,
)
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_type_hints,
)

import orjson

TBaseClientConfig = TypeVar("TBaseClientConfig", bound="BaseClientConfig")

# The field-metadata key dataclasses-json reads its per-field encoder from. ``grpc_cert`` keeps its
# encoder under this key, as plain data, so a downstream subclass that is still decorated with
# ``@dataclass_json`` (ondewo-sip-client, -vtsi-client, -csi-client, -t2s-client, -survey-client)
# keeps writing the certificate as text. ``to_dict`` here honours the same key.
FIELD_METADATA_KEY: str = "dataclasses_json"

# Field types whose values ``from_dict`` converts the way dataclasses-json did: ``type_(value)``.
_COERCED_TYPES: Tuple[type, ...] = (str, int, float, bool, Enum)


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


def _json_default(value: Any) -> Any:
    """
    Render a value neither JSON nor orjson can encode natively, as dataclasses-json's encoder did.

    Args:
        value (Any):
            The value, e.g. ``bytes`` or a ``set`` held by a subclass field.

    Returns:
        Any:
            An ``Enum``'s value, or a ``list`` for a collection (``bytes`` become their byte values, as
            before). Mappings never get here: :func:`_to_plain` has already turned them into dicts.

    Raises:
        TypeError:
            If the value is of any other type. The message names the type, never the value.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Collection):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class _JSONEncoder(json.JSONEncoder):
    """The ``json`` encoder ``to_json`` uses when it is given ``json.dumps`` keyword arguments."""

    def default(self, o: Any) -> Any:
        """
        Delegate to :func:`_json_default`.

        Args:
            o (Any):
                A value ``json`` cannot encode natively.

        Returns:
            Any:
                See :func:`_json_default`.
        """
        return _json_default(o)


def _to_plain(value: Any) -> Any:
    """
    Convert a dataclass (recursively) into dicts and lists, applying per-field encoders.

    Mirrors dataclasses-json's ``_asdict``: a dataclass becomes a dict in field order (a field with an
    encoder under :data:`FIELD_METADATA_KEY` is passed through it), a mapping a dict, any other
    collection except ``str`` / ``bytes`` / an ``Enum`` a list; every other value is kept as it is.

    Args:
        value (Any):
            A dataclass instance or a field value.

    Returns:
        Any:
            The plain representation.
    """
    if is_dataclass(value) and not isinstance(value, type):
        result: Dict[str, Any] = {}
        for value_field in fields(value):
            encoder: Optional[Callable[[Any], Any]] = value_field.metadata.get(FIELD_METADATA_KEY, {}).get("encoder")
            field_value: Any = getattr(value, value_field.name)
            result[value_field.name] = encoder(field_value) if encoder else _to_plain(field_value)
        return result
    if isinstance(value, Mapping):
        return {_to_plain(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, Collection) and not isinstance(value, (str, bytes, Enum)):
        return [_to_plain(item) for item in value]
    return value


def _encode_json_type(value: Any) -> Any:
    """
    Make a :func:`_to_plain` value JSON-compatible, as ``to_dict(encode_json=True)`` always did.

    Args:
        value (Any):
            A plain value.

    Returns:
        Any:
            ``value`` with every non-JSON leaf rendered by :func:`_json_default`.
    """
    if isinstance(value, list):
        return [_encode_json_type(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode_json_type(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return _json_default(value)


def _is_optional(type_: Any) -> bool:
    """
    Tell whether a field type admits ``None`` (``Optional[X]``, ``X | None``, a ``Union`` with ``None``, ``Any``).

    Args:
        type_ (Any):
            A resolved field type.

    Returns:
        bool:
            ``True`` if ``None`` is a legitimate value.
    """
    return type_ is Any or type(None) in get_args(type_)


def _decode_value(owner: type, name: str, type_: Any, value: Any, infer_missing: bool) -> Any:
    """
    Convert one decoded JSON value to its field's type, the way dataclasses-json did.

    * ``None`` stays ``None``; a ``RuntimeWarning`` names a non-optional field (never the value).
    * ``Optional[X]`` / ``X | None`` is decoded as ``X``.
    * A dataclass type is built from a mapping (an instance is kept).
    * ``str`` / ``int`` / ``float`` / ``bool`` / an ``Enum`` is converted with ``type_(value)`` unless the
      value already has that type, so a port given as ``50051`` becomes ``"50051"``. ``bytes`` given for a
      ``str`` field are kept, exactly as the constructor keeps them (dataclasses-json produced ``"b'...'"``).
    * Anything else, collections included, is passed through as decoded.

    Args:
        owner (type):
            The dataclass being decoded, for messages.
        name (str):
            The field name, for messages.
        type_ (Any):
            The resolved field type.
        value (Any):
            The decoded value.
        infer_missing (bool):
            The ``from_dict`` flag, which only selects the warning text here.

    Returns:
        Any:
            The converted value.

    Raises:
        ValueError:
            If the conversion fails. The message names the field and the value's type, never the value.
    """
    if value is None:
        if not _is_optional(type_):
            warning: str = f"value of non-optional type {name} detected when decoding {owner.__name__}"
            if infer_missing:
                warnings.warn(
                    f"Missing {warning} and was defaulted to None by infer_missing=True. "
                    f"Set infer_missing=False (the default) to prevent this behavior.",
                    RuntimeWarning,
                )
            else:
                warnings.warn(f"'NoneType' object {warning}.", RuntimeWarning)
        return None
    arguments: Tuple[Any, ...] = get_args(type_)
    if len(arguments) == 2 and type(None) in arguments:
        type_ = arguments[0] if arguments[1] is type(None) else arguments[1]
    if is_dataclass(type_) and isinstance(type_, type):
        return value if is_dataclass(value) else _decode_dataclass(type_, value, infer_missing)
    if not (isinstance(type_, type) and issubclass(type_, _COERCED_TYPES)):
        return value
    if isinstance(value, type_):
        return value
    if type_ is str and isinstance(value, bytes):
        return value
    convert: Callable[[Any], Any] = type_
    try:
        return convert(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{owner.__name__}.{name}: a {type(value).__name__} cannot be converted to {type_.__name__}"
        ) from None


def _decode_dataclass(klass: Type[Any], kvs: Any, infer_missing: bool) -> Any:
    """
    Build a dataclass from a mapping: unknown keys are ignored, absent ones take their default.

    Args:
        klass (Type[Any]):
            The dataclass to build.
        kvs (Any):
            The decoded document; an instance of ``klass`` is returned unchanged.
        infer_missing (bool):
            Pass ``None`` for absent fields that have no default (with a ``RuntimeWarning``).

    Returns:
        Any:
            The new instance (or ``kvs`` if it already is one).

    Raises:
        TypeError:
            If ``kvs`` is not a mapping, or a field without a default is absent (the constructor's
            error). The messages name the class and field, never a value.
    """
    if isinstance(kvs, klass):
        return kvs
    if kvs is None and infer_missing:
        kvs = {}
    if not isinstance(kvs, Mapping):
        raise TypeError(f"{klass.__name__} must be decoded from a JSON object (a mapping), not {type(kvs).__name__}")
    types: Dict[str, Any] = get_type_hints(klass)
    init_kwargs: Dict[str, Any] = {}
    for klass_field in fields(klass):
        if not klass_field.init:
            continue
        if klass_field.name in kvs:
            value: Any = kvs[klass_field.name]
        elif klass_field.default is not MISSING:
            value = klass_field.default
        elif klass_field.default_factory is not MISSING:
            value = klass_field.default_factory()
        elif infer_missing:
            value = None
        else:
            continue
        init_kwargs[klass_field.name] = _decode_value(
            klass, klass_field.name, types[klass_field.name], value, infer_missing
        )
    return klass(**init_kwargs)


@dataclass(frozen=True)
class BaseClientConfig:
    """
    Configuration for the ONDEWO python client.

    ``to_dict`` / ``from_dict`` / ``to_json`` / ``from_json`` are implemented here on top of orjson and
    keep the names, calls and outputs dataclasses-json gave them (pinned by
    ``tests/test_base_client_config_golden.py``), so a subclass, frozen stdlib dataclass or not, inherits
    them and ``from_*`` builds the subclass. ``schema()`` is gone: it returned a ``marshmallow.Schema``.

    Attributes:
        host (str):
            IP address of the ONDEWO QA services host (e.g., 'localhost', '127.22.444.11', etc.)
        port (str):
            Port of the ONDEWO QA services host (e.g., '50444', etc.)
        grpc_cert (Optional[str]):
            The PEM CONTENT (``str`` or ``bytes``, e.g. ``Path("ca.pem").read_text()``), not a file path,
            of the root certificate required for setting up a secure gRPC channel. This field must be
            set unless the client is instantiated using `use_secure_channel=False` (not recommended). A
            ``str`` is encoded to ``bytes`` on construction and ``bytes`` are kept as they are;
            ``to_dict`` / ``to_json`` carry the PEM as text, so ``from_dict`` / ``from_json`` and
            ``dataclasses.replace`` give back an equal config.
        grpc_client_cert (Optional[str]):
            The PEM CONTENT (``str`` or ``bytes``), not a file path, of the client certificate chain
            presented to a server that requires mutual TLS. Set it together with ``grpc_client_key``, or
            neither: without both the channel is plain TLS and the server asks for no client certificate.
            Encoded and serialized like ``grpc_cert``.
        grpc_client_key (Optional[str]):
            The PEM CONTENT (``str`` or ``bytes``), not a file path, of the private key of
            ``grpc_client_cert``. Encoded and serialized like ``grpc_cert``: ``repr`` hides it, but
            ``to_dict`` / ``to_json`` carry it in clear text, so treat a serialized config as a secret.
    """

    host: str
    port: str
    grpc_cert: Optional[str] = field(default=None, metadata={FIELD_METADATA_KEY: {"encoder": _encode_grpc_cert}})
    grpc_client_cert: Optional[str] = field(
        default=None,
        metadata={FIELD_METADATA_KEY: {"encoder": _encode_grpc_cert}},
    )
    # repr=False: a config is printed into logs and tracebacks, and this is a private key.
    grpc_client_key: Optional[str] = field(
        default=None,
        repr=False,
        metadata={FIELD_METADATA_KEY: {"encoder": _encode_grpc_cert}},
    )

    def __post_init__(self) -> None:
        """
        Encode the gRPC certificates and key to bytes after the frozen dataclass is initialised.

        A non-empty ``str`` value of ``grpc_cert``, ``grpc_client_cert`` or ``grpc_client_key`` is encoded
        to ``bytes`` using ``object.__setattr__`` (required because the dataclass is frozen). ``bytes``
        (e.g. from ``dataclasses.replace`` on an existing config), ``""`` and ``None`` are left unchanged.

        Returns:
            None:
                This method mutates the instance in place and returns nothing.

        Raises:
            ValueError:
                If exactly one of ``grpc_client_cert`` and ``grpc_client_key`` is set: a client
                certificate cannot be presented without its key, nor a key without its certificate.
        """
        name: str
        for name in ("grpc_cert", "grpc_client_cert", "grpc_client_key"):
            value: Any = getattr(self, name)
            if isinstance(value, str) and value:
                object.__setattr__(self, name, value.encode())
        if bool(self.grpc_client_cert) != bool(self.grpc_client_key):
            # Never interpolate either value: the key is a secret.
            raise ValueError(
                f"{type(self).__name__} for {self.host_and_port} sets only one of grpc_client_cert and "
                "grpc_client_key; set both to use mutual TLS, or neither."
            )

    @property
    def host_and_port(self) -> str:
        """
        Return the host and port combined into a single connection string.

        An IPv6 literal is bracketed (``"::1"`` becomes ``"[::1]:50051"``): gRPC cannot resolve
        ``"::1:50051"``. A host that is already bracketed or carries a scheme (``"ipv6:[::1]"``,
        ``"dns:..."``, ``"unix:..."``) is left as it is.

        Returns:
            str:
                The host and port in the format ``"host:port"``.
        """
        try:
            is_ipv6: bool = ipaddress.ip_address(self.host).version == 6
        except ValueError:
            is_ipv6 = False
        return f"[{self.host}]:{self.port}" if is_ipv6 else f"{self.host}:{self.port}"

    def to_dict(self, encode_json: bool = False) -> Dict[str, Any]:
        """
        Return the configuration as a dictionary, one entry per field in declaration order.

        ``grpc_cert`` is PEM text. Nested dataclasses become dicts, other collections lists.

        Args:
            encode_json (bool):
                Also render values JSON has no type for (an ``Enum`` becomes its value, ``bytes``
                and other collections become lists). Defaults to ``False``.

        Returns:
            Dict[str, Any]:
                The fields and their values.
        """
        result: Dict[str, Any] = _to_plain(self)
        return _encode_json_type(result) if encode_json else result

    def to_json(self, **kwargs: Any) -> str:
        """
        Serialize the configuration to a JSON object, carrying ``grpc_cert`` as PEM text.

        Without arguments the document is rendered by orjson: compact (no spaces after ``,`` and
        ``:``) and UTF-8 (non-ASCII characters are not ``\\u`` escaped). With any ``json.dumps``
        keyword argument (``indent``, ``sort_keys``, ``ensure_ascii``, ``separators``, ...) it is
        rendered by ``json.dumps`` with exactly those arguments, which is byte-identical to what
        dataclasses-json produced for the same call.

        Args:
            **kwargs (Any):
                Optional ``json.dumps`` keyword arguments.

        Returns:
            str:
                The JSON document.
        """
        if kwargs:
            return json.dumps(self.to_dict(), cls=_JSONEncoder, **kwargs)
        # OPT_NON_STR_KEYS: stringify e.g. int mapping keys, as json.dumps (and dataclasses-json) does.
        return orjson.dumps(self.to_dict(), default=_json_default, option=orjson.OPT_NON_STR_KEYS).decode()

    @classmethod
    def from_dict(cls: Type[TBaseClientConfig], kvs: Any, *, infer_missing: bool = False) -> TBaseClientConfig:
        """
        Build a configuration of THIS class (a subclass builds itself) from a mapping.

        Keys that are not fields are ignored, so a configuration written by a newer client loads on an
        older one; absent fields take their defaults. Values are converted as dataclasses-json did
        (e.g. a port ``50051`` becomes ``"50051"``; see :func:`_decode_value`), and an instance of the
        class is returned unchanged.

        Args:
            kvs (Any):
                The field values, normally a ``dict``.
            infer_missing (bool):
                Pass ``None`` for an absent field without a default (with a ``RuntimeWarning``) instead
                of failing. Defaults to ``False``.

        Returns:
            TBaseClientConfig:
                The configuration.

        Raises:
            TypeError:
                If ``kvs`` is not a mapping, or a field without a default is absent.
            ValueError:
                If a value cannot be converted to its field's type.
        """
        config: TBaseClientConfig = _decode_dataclass(cls, kvs, infer_missing)
        return config

    @classmethod
    def from_json(
        cls: Type[TBaseClientConfig],
        s: Union[str, bytes, bytearray],
        *,
        infer_missing: bool = False,
        **kwargs: Any,
    ) -> TBaseClientConfig:
        """
        Build a configuration of THIS class from a JSON object (see :meth:`from_dict`).

        The document is parsed by orjson; with ``json.loads`` keyword arguments (``parse_int``,
        ``parse_float``, ``object_hook``, ...) it is parsed by ``json.loads`` with exactly those.

        Args:
            s (Union[str, bytes, bytearray]):
                The JSON document.
            infer_missing (bool):
                See :meth:`from_dict`. Defaults to ``False``.
            **kwargs (Any):
                Optional ``json.loads`` keyword arguments.

        Returns:
            TBaseClientConfig:
                The configuration.

        Raises:
            json.JSONDecodeError:
                If ``s`` is not valid JSON (orjson's ``JSONDecodeError`` is a subclass), including the
                non-standard ``NaN`` / ``Infinity`` literals.
            TypeError:
                If the document is not a JSON object, or a field without a default is absent.
            ValueError:
                If a value cannot be converted to its field's type.
        """
        document: Any = json.loads(s, **kwargs) if kwargs else orjson.loads(s)
        return cls.from_dict(document, infer_missing=infer_missing)
