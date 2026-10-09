"""
Mutual TLS: a client certificate on ``BaseClientConfig``, presented by the sync and the async channel helpers.

Both modes are pinned:

* **TLS only** (no ``grpc_client_cert`` / ``grpc_client_key``): the channel verifies the server and presents nothing.
* **Mutual TLS** (both set): the channel additionally presents the client leaf, which a server that requires
  client certificates checks against its own CA.

The handshake tests run a real gRPC server per case (sync and ``grpc.aio``) with certificates minted per session, so
they prove what a server actually accepts and refuses, not only which arguments reach ``ssl_channel_credentials``.
"""

import dataclasses
import datetime
import json
from concurrent import futures
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
)
from unittest import mock

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import (
    hashes,
    serialization,
)
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import (
    ExtendedKeyUsageOID,
    NameOID,
)

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils import base_services_interface as bsi
from ondewo.utils.base_client_config import BaseClientConfig

SERVER_NAME: str = "localhost"
METHOD: str = "/test.Echo/Ping"
#: A refused handshake is retried for ~15 s without this, and reads as a hang rather than as a refusal.
CLIENT_OPTIONS: List[Tuple[str, Any]] = [("grpc.enable_retries", 0)]
TIMEOUT_IN_S: float = 10.0


class Pki:
    """One throwaway CA with a server leaf (SAN ``localhost``) and a client leaf, all PEM bytes."""

    def __init__(self, name: str) -> None:
        self._ca_key: ec.EllipticCurvePrivateKey = ec.generate_private_key(ec.SECP256R1())
        self.ca_cert: bytes = self._issue(f"{name}-ca", self._ca_key.public_key(), ca=True, issuer=None)
        server_key: ec.EllipticCurvePrivateKey = ec.generate_private_key(ec.SECP256R1())
        self.server_key: bytes = _pem_key(server_key)
        self.server_cert: bytes = self._issue(
            f"{name}-server",
            server_key.public_key(),
            ca=False,
            issuer=x509.load_pem_x509_certificate(self.ca_cert),
            usage=ExtendedKeyUsageOID.SERVER_AUTH,
            san=SERVER_NAME,
        )
        client_key: ec.EllipticCurvePrivateKey = ec.generate_private_key(ec.SECP256R1())
        self.client_key: bytes = _pem_key(client_key)
        self.client_cert: bytes = self._issue(
            f"{name}-client",
            client_key.public_key(),
            ca=False,
            issuer=x509.load_pem_x509_certificate(self.ca_cert),
            usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        )

    def _issue(
        self,
        subject: str,
        public_key: ec.EllipticCurvePublicKey,
        ca: bool,
        issuer: Optional[x509.Certificate],
        usage: Optional[x509.ObjectIdentifier] = None,
        san: Optional[str] = None,
    ) -> bytes:
        now: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)
        name: x509.Name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
        builder: x509.CertificateBuilder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name if issuer is None else issuer.subject)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        if usage is not None:
            builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
        if san is not None:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        return builder.sign(self._ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)


def _pem_key(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def pki() -> Pki:
    return Pki("deployment")


@pytest.fixture(scope="module")
def foreign() -> Pki:
    return Pki("foreign")


def _server_credentials(pki: Pki, require_client_auth: bool) -> grpc.ServerCredentials:
    return grpc.ssl_server_credentials(
        [(pki.server_key, pki.server_cert)],
        root_certificates=pki.ca_cert if require_client_auth else None,
        require_client_auth=require_client_auth,
    )


def _echo_handler() -> grpc.GenericRpcHandler:
    return grpc.method_handlers_generic_handler(
        "test.Echo",
        {"Ping": grpc.unary_unary_rpc_method_handler(lambda request, context: request)},
    )


def _config(port: int, pki: Pki, client: Optional[Pki] = None) -> BaseClientConfig:
    """A config trusting ``pki``'s CA, presenting ``client``'s leaf when given (mutual TLS)."""
    return BaseClientConfig(
        host=SERVER_NAME,
        port=str(port),
        grpc_cert=pki.ca_cert.decode(),
        grpc_client_cert=None if client is None else client.client_cert.decode(),
        grpc_client_key=None if client is None else client.client_key.decode(),
    )


@pytest.fixture
def sync_server() -> Iterator[Callable[[Pki, bool], int]]:
    """Start a sync TLS server on an ephemeral port; ``(pki, require_client_auth) -> port``."""
    servers: List[grpc.Server] = []

    def start(pki: Pki, require_client_auth: bool) -> int:
        server: grpc.Server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        server.add_generic_rpc_handlers((_echo_handler(),))
        port: int = server.add_secure_port("localhost:0", _server_credentials(pki, require_client_auth))
        server.start()
        servers.append(server)
        return port

    yield start
    for server in servers:
        server.stop(grace=None)


@pytest.fixture
async def async_server() -> Any:
    """Start a ``grpc.aio`` TLS server on an ephemeral port; ``(pki, require_client_auth) -> port``."""
    servers: List[grpc.aio.Server] = []

    async def start(pki: Pki, require_client_auth: bool) -> int:
        server: grpc.aio.Server = grpc.aio.server()
        server.add_generic_rpc_handlers((_echo_handler(),))
        port: int = server.add_secure_port("localhost:0", _server_credentials(pki, require_client_auth))
        await server.start()
        servers.append(server)
        return port

    yield start
    for server in servers:
        await server.stop(grace=None)


def _ping(config: BaseClientConfig) -> bytes:
    channel: grpc.Channel = bsi._get_grpc_channel(config=config, use_secure_channel=True, options=CLIENT_OPTIONS)
    try:
        response: bytes = channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S)
        return response
    finally:
        channel.close()


async def _async_ping(config: BaseClientConfig) -> bytes:
    channel: grpc.aio.Channel = absi._get_grpc_channel(config=config, use_secure_channel=True, options=CLIENT_OPTIONS)
    try:
        response: bytes = await channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S)
        return response
    finally:
        await channel.close()


class TestTheConfigCarriesAClientCertificate:
    @staticmethod
    def test_tls_only_is_the_default() -> None:
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_cert="ca")
        assert (config.grpc_client_cert, config.grpc_client_key) == (None, None)

    @staticmethod
    def test_str_pems_are_encoded_to_bytes_like_grpc_cert() -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_cert="ca",
            grpc_client_cert="client-cert",
            grpc_client_key="client-key",
        )
        assert (config.grpc_client_cert, config.grpc_client_key) == (b"client-cert", b"client-key")

    @staticmethod
    def test_bytes_pems_are_kept() -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_client_cert=b"client-cert",  # type: ignore[arg-type]  # bytes are accepted, as for grpc_cert
            grpc_client_key=b"client-key",  # type: ignore[arg-type]
        )
        assert (config.grpc_client_cert, config.grpc_client_key) == (b"client-cert", b"client-key")

    @staticmethod
    @pytest.mark.parametrize(
        "client_cert, client_key",
        [("client-cert", None), (None, "client-key"), ("client-cert", ""), ("", "client-key")],
        ids=["cert-without-key", "key-without-cert", "cert-with-empty-key", "key-with-empty-cert"],
    )
    def test_half_a_client_identity_is_refused(client_cert: Optional[str], client_key: Optional[str]) -> None:
        with pytest.raises(ValueError, match="set both to use mutual TLS, or neither") as refusal:
            BaseClientConfig(host="h", port="1", grpc_client_cert=client_cert, grpc_client_key=client_key)
        assert "client-key" not in str(refusal.value)

    @staticmethod
    def test_empty_pems_mean_tls_only() -> None:
        config: BaseClientConfig = BaseClientConfig(host="h", port="1", grpc_client_cert="", grpc_client_key="")
        assert (config.grpc_client_cert, config.grpc_client_key) == ("", "")

    @staticmethod
    def test_the_private_key_never_appears_in_the_repr() -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_client_cert="client-cert",
            grpc_client_key="very-secret-key",
        )
        assert "very-secret-key" not in repr(config)
        assert "grpc_client_key" not in repr(config)

    @staticmethod
    def test_serialization_round_trips_losslessly() -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_cert="ca",
            grpc_client_cert="client-cert",
            grpc_client_key="client-key",
        )
        plain: Dict[str, Any] = config.to_dict()
        assert (plain["grpc_client_cert"], plain["grpc_client_key"]) == ("client-cert", "client-key")
        assert json.loads(config.to_json())["grpc_client_key"] == "client-key"
        assert BaseClientConfig.from_dict(plain) == config
        assert BaseClientConfig.from_json(config.to_json()) == config
        assert dataclasses.replace(config, port="2").grpc_client_key == b"client-key"

    @staticmethod
    def test_a_document_written_before_mutual_tls_still_loads() -> None:
        config: BaseClientConfig = BaseClientConfig.from_json('{"host": "h", "port": "1", "grpc_cert": "ca"}')
        assert (config.grpc_client_cert, config.grpc_client_key) == (None, None)


@pytest.mark.parametrize("module", [bsi, absi], ids=["sync", "async"])
class TestTheChannelHelpersPassTheIdentity:
    @staticmethod
    def test_get_secure_channel_presents_the_client_leaf(module: Any) -> None:
        with (
            mock.patch.object(module.grpc, "ssl_channel_credentials") as credentials,
            mock.patch.object(module.grpc if module is bsi else module.grpc.aio, "secure_channel"),
        ):
            module.get_secure_channel(host="h:1", cert="ca", client_cert="client-cert", client_key="client-key")
        credentials.assert_called_once_with(
            root_certificates=b"ca",
            private_key=b"client-key",
            certificate_chain=b"client-cert",
        )

    @staticmethod
    def test_get_secure_channel_passes_bytes_through(module: Any) -> None:
        with (
            mock.patch.object(module.grpc, "ssl_channel_credentials") as credentials,
            mock.patch.object(module.grpc if module is bsi else module.grpc.aio, "secure_channel"),
        ):
            module.get_secure_channel(host="h:1", cert=b"ca", client_cert=b"client-cert", client_key=b"client-key")
        credentials.assert_called_once_with(
            root_certificates=b"ca",
            private_key=b"client-key",
            certificate_chain=b"client-cert",
        )

    @staticmethod
    def test_the_config_identity_reaches_the_credentials(module: Any) -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_cert="ca",
            grpc_client_cert="client-cert",
            grpc_client_key="client-key",
        )
        with (
            mock.patch.object(module.grpc, "ssl_channel_credentials") as credentials,
            mock.patch.object(module.grpc if module is bsi else module.grpc.aio, "secure_channel"),
        ):
            module._get_grpc_channel(config=config, use_secure_channel=True)
        credentials.assert_called_once_with(
            root_certificates=b"ca",
            private_key=b"client-key",
            certificate_chain=b"client-cert",
        )

    @staticmethod
    def test_a_plaintext_channel_is_refused_for_a_client_identity(module: Any) -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_client_cert="client-cert",
            grpc_client_key="very-secret-key",
        )
        with pytest.raises(ValueError, match="use a secure channel") as refusal:
            module._get_grpc_channel(config=config, use_secure_channel=False)
        assert "very-secret-key" not in str(refusal.value)

    @staticmethod
    def test_a_client_identity_does_not_replace_the_server_trust_anchor(module: Any) -> None:
        config: BaseClientConfig = BaseClientConfig(
            host="h",
            port="1",
            grpc_client_cert="client-cert",
            grpc_client_key="client-key",
        )
        with pytest.raises(ValueError, match="No grpc certificate found"):
            module._get_grpc_channel(config=config, use_secure_channel=True)


class TestARealSyncHandshake:
    @staticmethod
    def test_mutual_tls_with_a_leaf_from_the_servers_ca_is_served(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
    ) -> None:
        port: int = sync_server(pki, True)
        assert _ping(_config(port, pki, client=pki)) == b"ping"

    @staticmethod
    def test_mutual_tls_without_a_client_leaf_is_refused(sync_server: Callable[[Pki, bool], int], pki: Pki) -> None:
        port: int = sync_server(pki, True)
        with pytest.raises(grpc.RpcError) as refusal:
            _ping(_config(port, pki))
        assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE  # type: ignore[attr-defined]

    @staticmethod
    def test_mutual_tls_with_a_leaf_from_another_ca_is_refused(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
        foreign: Pki,
    ) -> None:
        port: int = sync_server(pki, True)
        with pytest.raises(grpc.RpcError) as refusal:
            _ping(_config(port, pki, client=foreign))
        assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE  # type: ignore[attr-defined]

    @staticmethod
    def test_tls_only_server_serves_a_client_without_a_leaf(sync_server: Callable[[Pki, bool], int], pki: Pki) -> None:
        port: int = sync_server(pki, False)
        assert _ping(_config(port, pki)) == b"ping"

    @staticmethod
    def test_tls_only_server_also_serves_a_client_presenting_a_leaf(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
    ) -> None:
        port: int = sync_server(pki, False)
        assert _ping(_config(port, pki, client=pki)) == b"ping"

    @staticmethod
    def test_the_client_still_verifies_the_server(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
        foreign: Pki,
    ) -> None:
        """Presenting a leaf does not weaken server verification: trusting another CA still fails."""
        port: int = sync_server(pki, True)
        with pytest.raises(grpc.RpcError) as refusal:
            _ping(_config(port, foreign, client=pki))
        assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE  # type: ignore[attr-defined]


class TestARealAsyncHandshake:
    @staticmethod
    async def test_mutual_tls_with_a_leaf_from_the_servers_ca_is_served(async_server: Any, pki: Pki) -> None:
        port: int = await async_server(pki, True)
        assert await _async_ping(_config(port, pki, client=pki)) == b"ping"

    @staticmethod
    async def test_mutual_tls_without_a_client_leaf_is_refused(async_server: Any, pki: Pki) -> None:
        port: int = await async_server(pki, True)
        with pytest.raises(grpc.aio.AioRpcError) as refusal:
            await _async_ping(_config(port, pki))
        assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE

    @staticmethod
    async def test_mutual_tls_with_a_leaf_from_another_ca_is_refused(
        async_server: Any,
        pki: Pki,
        foreign: Pki,
    ) -> None:
        port: int = await async_server(pki, True)
        with pytest.raises(grpc.aio.AioRpcError) as refusal:
            await _async_ping(_config(port, pki, client=foreign))
        assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE

    @staticmethod
    async def test_tls_only_server_serves_a_client_without_a_leaf(async_server: Any, pki: Pki) -> None:
        port: int = await async_server(pki, False)
        assert await _async_ping(_config(port, pki)) == b"ping"


def _crlf(pem: bytes) -> bytes:
    return pem.replace(b"\n", b"\r\n")


@pytest.mark.parametrize("module", [bsi, absi], ids=["sync", "async"])
class TestGetSecureChannelValidatesTheIdentity:
    @staticmethod
    @pytest.mark.parametrize(
        "client_cert, client_key",
        [
            (b"SECRETCERT", None),
            (None, b"SECRETKEY"),
            (b"", b"SECRETKEY"),
            (b"SECRETCERT", b""),
            ("SECRETCERT", None),
            (None, "SECRETKEY"),
        ],
        ids=["cert-only", "key-only", "empty-cert", "empty-key", "str-cert-only", "str-key-only"],
    )
    def test_get_secure_channel_refuses_half_a_client_identity(
        module: Any,
        client_cert: Optional[Any],
        client_key: Optional[Any],
    ) -> None:
        """Half an identity would make grpc core CHECK-fail and abort() the process; it raises instead."""
        with mock.patch.object(module.grpc, "ssl_channel_credentials") as credentials:
            with pytest.raises(ValueError, match="set both to use mutual TLS, or neither") as refusal:
                module.get_secure_channel(host="h:1", cert=b"ca", client_cert=client_cert, client_key=client_key)
        credentials.assert_not_called()
        assert "SECRETCERT" not in str(refusal.value)
        assert "SECRETKEY" not in str(refusal.value)

    @staticmethod
    @pytest.mark.parametrize("empty", [b"", ""], ids=["bytes", "str"])
    def test_an_empty_identity_on_both_is_plain_tls(module: Any, empty: Any) -> None:
        with (
            mock.patch.object(module.grpc, "ssl_channel_credentials") as credentials,
            mock.patch.object(module.grpc if module is bsi else module.grpc.aio, "secure_channel"),
        ):
            module.get_secure_channel(host="h:1", cert=b"ca", client_cert=empty, client_key=empty)
        credentials.assert_called_once_with(root_certificates=b"ca", private_key=None, certificate_chain=None)


class TestARealHandshakeThroughTheSharedChannel:
    @staticmethod
    def test_an_empty_identity_is_served_by_a_tls_only_server(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
    ) -> None:
        port: int = sync_server(pki, False)
        channel: grpc.Channel = bsi.get_secure_channel(
            host=f"{SERVER_NAME}:{port}", cert=pki.ca_cert, options=CLIENT_OPTIONS, client_cert=b"", client_key=b""
        )
        try:
            assert channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S) == b"ping"
        finally:
            channel.close()

    @staticmethod
    @pytest.mark.parametrize("with_leaf", [True, False], ids=["with-leaf", "without-leaf"])
    def test_sync_shared_channel_against_a_mutual_tls_server(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
        with_leaf: bool,
    ) -> None:
        port: int = sync_server(pki, True)
        channel: grpc.Channel = bsi.build_shared_channel(
            config=_config(port, pki, client=pki if with_leaf else None),
            use_secure_channel=True,
            service_classes=(),
            options={("grpc.enable_retries", 0)},
        )
        try:
            if with_leaf:
                assert channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S) == b"ping"
            else:
                with pytest.raises(grpc.RpcError) as refusal:
                    channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S)
                assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE  # type: ignore[attr-defined]
        finally:
            channel.close()

    @staticmethod
    @pytest.mark.parametrize("with_leaf", [True, False], ids=["with-leaf", "without-leaf"])
    async def test_async_shared_channel_against_a_mutual_tls_server(
        async_server: Any,
        pki: Pki,
        with_leaf: bool,
    ) -> None:
        port: int = await async_server(pki, True)
        # Built inside the running loop: a grpc.aio channel binds to the loop it is created on.
        channel: grpc.aio.Channel = absi.build_shared_channel(
            config=_config(port, pki, client=pki if with_leaf else None),
            use_secure_channel=True,
            service_classes=(),
            options={("grpc.enable_retries", 0)},
        )
        try:
            if with_leaf:
                assert await channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S) == b"ping"
            else:
                with pytest.raises(grpc.aio.AioRpcError) as refusal:
                    await channel.unary_unary(METHOD)(b"ping", timeout=TIMEOUT_IN_S)
                assert refusal.value.code() is grpc.StatusCode.UNAVAILABLE
        finally:
            await channel.close()

    @staticmethod
    def test_crlf_terminated_pems_complete_the_mutual_tls_handshake(
        sync_server: Callable[[Pki, bool], int],
        pki: Pki,
    ) -> None:
        """PEMs saved on Windows (CRLF line endings) are accepted for the CA, the client leaf and its key."""
        port: int = sync_server(pki, True)
        config: BaseClientConfig = BaseClientConfig(
            host=SERVER_NAME,
            port=str(port),
            grpc_cert=_crlf(pki.ca_cert).decode(),
            grpc_client_cert=_crlf(pki.client_cert).decode(),
            grpc_client_key=_crlf(pki.client_key).decode(),
        )
        assert _ping(config) == b"ping"
