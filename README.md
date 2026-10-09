<p align="center">
    <a href="https://www.ondewo.com">
      <img alt="ONDEWO Logo" src="https://raw.githubusercontent.com/ondewo/ondewo-logos/master/github/ondewo_logo_github_2.png"/>
    </a>
</p>

Ondewo Client Utils Library
======================

This library contains base classes and utilities for higher-level interface clients interacting with gRPC servers.

Python Installation
-------------------

The library requires Python 3.12 or newer. You can install it directly from PyPI:

```bash
pip install ondewo-client-utils
```

For development, clone it and let the Makefile set up [uv](https://docs.astral.sh/uv/), the locked
runtime + dev dependencies in `.venv` and the pre-commit hooks:

```bash
git clone git@github.com:ondewo/ondewo-client-utils-python.git
cd ondewo-client-utils-python
make setup_developer_environment_locally
make test            # unit tests + the 100% coverage gate
```

Client configuration
--------------------

`BaseClientConfig` (`host`, `port`, `grpc_cert`, `grpc_client_cert`, `grpc_client_key`) is a frozen dataclass that
the SDKs subclass with their own `@dataclass(frozen=True)` fields. It serializes with
[orjson](https://github.com/ijl/orjson); `from_dict` / `from_json` build the class they are called on and ignore
unknown keys, so a config written by a newer client loads on an older one. Certificates and the key are carried as
PEM text, and an unset one as `null`:

```python
config = BaseClientConfig(host="localhost", port="50051", grpc_cert=pem_text)
text = config.to_json()
# '{"host":"localhost","port":"50051","grpc_cert":"-----BEGIN ...","grpc_client_cert":null,"grpc_client_key":null}'
assert BaseClientConfig.from_json(text) == config
pretty = config.to_json(indent=2, sort_keys=True)  # any json.dumps keyword argument uses json.dumps
```

TLS, mutual TLS and certificates
--------------------------------

gRPC encrypts with **TLS**. "SSL" in names such as `grpc.ssl_channel_credentials` or
`grpc.ssl_target_name_override` is legacy naming; no SSL protocol version is ever negotiated.

| Mode                           | Service / channel argument | Config fields                                                  |
|--------------------------------|----------------------------|----------------------------------------------------------------|
| Plaintext (not for production) | `use_secure_channel=False` | none                                                           |
| Server-authenticated TLS       | `use_secure_channel=True`  | `grpc_cert` = PEM of the CA that signed the server certificate |
| Mutual TLS                     | `use_secure_channel=True`  | `grpc_cert` plus `grpc_client_cert` and `grpc_client_key`      |

Rules the code enforces:

- The three fields hold **PEM content** (`str` or `bytes`), **not file paths**. Read the files yourself.
- `grpc_client_cert` and `grpc_client_key` go together: setting only one raises `ValueError` when the config is
  built (and `get_secure_channel` refuses half a pair the same way). Neither set means plain server-authenticated TLS.
- `use_secure_channel=False` with a config that carries a client certificate raises `ValueError` instead of silently
  dropping the identity; a secure channel without `grpc_cert` raises `ValueError` too. No message renders a PEM.
- The server certificate is verified against `grpc_cert`, and the host you connect to must match one of the
  certificate's subject alternative names (SAN). When you connect by IP and the certificate has no IP SAN, tell gRPC
  which name to check with the channel option `("grpc.ssl_target_name_override", "<name in the SAN>")`.

In the examples, `Calls` / `Agents` are service interfaces built on `BaseServicesInterface` (see [Usage](#usage)),
and `AsyncCalls` / `AsyncAgents` their `AsyncBaseServicesInterface` counterparts. One channel per service:

```python
from pathlib import Path

from ondewo.utils.base_client_config import BaseClientConfig

config = BaseClientConfig(
    host="10.0.0.5",
    port="50051",
    grpc_cert=Path("certs/ca.pem").read_text(),
    grpc_client_cert=Path("certs/client.pem").read_text(),  # leave both out for server-authenticated TLS
    grpc_client_key=Path("certs/client.key").read_text(),
)
calls = Calls(
    config=config,
    use_secure_channel=True,
    options={("grpc.ssl_target_name_override", "nlu.example.internal")},  # only when connecting by IP
)
```

One shared channel (see [below](#one-connection-for-all-services-low-latency)) takes the same config:

```python
from ondewo.utils.base_services_interface import build_shared_channel

channel = build_shared_channel(config, use_secure_channel=True, service_classes=(Calls, Agents))
calls = Calls(config=config, use_secure_channel=True, grpc_channel=channel)
agents = Agents(config=config, use_secure_channel=True, grpc_channel=channel)
```

The async interfaces (`AsyncBaseServicesInterface`, `ondewo.utils.async_base_services_interface.build_shared_channel`)
take the same arguments (`AsyncCalls(config=config, use_secure_channel=True)` opens its own channel). Build them
inside the running event loop that uses them:

```python
import asyncio

from ondewo.utils.async_base_services_interface import build_shared_channel


async def main() -> None:
    channel = build_shared_channel(config, use_secure_channel=True, service_classes=(AsyncCalls, AsyncAgents))
    calls = AsyncCalls(config=config, use_secure_channel=True, grpc_channel=channel)
    agents = AsyncAgents(config=config, use_secure_channel=True, grpc_channel=channel)
    ...
    await channel.close()


asyncio.run(main())
```

A test PKI with openssl
-----------------------

A CA, a server certificate with SANs, and a client certificate with the `clientAuth` extended key usage. For tests
only: the keys are unencrypted.

```bash
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 365 \
  -subj "/CN=Test CA" -keyout ca.key -out ca.pem

printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' > server.ext
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -subj "/CN=localhost" -keyout server.key -out server.csr
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 365 \
  -extfile server.ext -out server.pem

printf 'extendedKeyUsage=clientAuth\n' > client.ext
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -subj "/CN=my-client" -keyout client.key -out client.csr
openssl x509 -req -in client.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 365 \
  -extfile client.ext -out client.pem

chmod 600 *.key
openssl verify -CAfile ca.pem server.pem client.pem
```

The client then uses `ca.pem` / `client.pem` / `client.key`; a server that requires client certificates uses
`server.pem` / `server.key` and trusts `ca.pem` for its clients.

TLS security notes
------------------

- `to_dict()` / `to_json()` write `grpc_client_key` **in clear text**. Treat any serialized config as a secret
  (file mode `0600`, never commit it), or better keep the key out of it and load it from a file or secret store at
  startup.
- `repr(config)` leaves out `grpc_client_key` (`field(repr=False)`), but it still shows the other fields: do not log
  configs or their serialized form.
- **SDK maintainers:** a subclass that defines its own `__repr__` overrides that protection. Every ONDEWO SDK config
  (nlu, csi, sip, s2t, t2s, vtsi) does so, redacting only a `SECRET_FIELD_NAMES` set; add `grpc_client_key` to it (or
  skip fields whose `repr` is `False`) before enabling mutual TLS through it, or the key is printed in clear text.

TLS troubleshooting
-------------------

The status code of a failed handshake is `UNAVAILABLE`; the cause is in the details (`grpc.RpcError.details()`):

- **`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`** (inside "Tls handshake failed"): `grpc_cert`
  is not the CA that issued the server certificate, or the server does not send its intermediate certificates.
- **`Hostname Verification Check failed`** (older gRPC: `Peer name <host> is not in peer certificate`): the host you
  connect to is not in the server certificate's SAN. Connect by a name in the SAN, add the SAN, or set
  `grpc.ssl_target_name_override`.
- **`Socket closed`** (or another `UNAVAILABLE`) against a server that requires client certificates: no client
  certificate was presented, or one the server's CA did not issue. The server log names the reason (e.g.
  `PEER_DID_NOT_RETURN_A_CERTIFICATE`). Set `grpc_client_cert` / `grpc_client_key`.
- **`Failed to create security handshaker`**, with `Could not load any root certificate` in the gRPC log: `grpc_cert`
  holds something that is not PEM, typically a file path. Pass `Path(...).read_text()` instead.

gRPC retry policy
-----------------

Every service interface built on `BaseServicesInterface` / `AsyncBaseServicesInterface` opens its channel with
`grpc.enable_retries` on and a per-service retry policy that **retries idempotent methods only**:

- **Idempotent** methods — the proto declares `idempotency_level = NO_SIDE_EFFECTS` or `IDEMPOTENT`, or the method name
  starts with a read verb (`Get`, `List`, `BatchGet`, `Check`, `Validate`, `Ping`) — are retried up to 5 attempts on
  `UNAVAILABLE`, `DEADLINE_EXCEEDED`, `INTERNAL`, `UNKNOWN`, `RESOURCE_EXHAUSTED`, `ABORTED` and `CANCELLED`.
- **Every other method** (`Start*`, `Create*`, `Update*`, `Delete*`, `DetectIntent`, ...) has **no**
  configured retry policy, on any status code including `UNAVAILABLE`: a failed attempt may already have acted on the
  server, and re-sending it would act twice. gRPC's own transparent retries, which only re-send a request that provably
  never reached the server application, stay on. To ride out a server that is not reachable *yet*, pass
  `wait_for_ready=True` on the call: it waits for a connection instead of re-sending a request.
- **Streaming methods** follow the same name rule: a server-streaming read such as `GetControlStream` is idempotent,
  an `Upload*` / `Stream*` call is not. gRPC never retries a stream once the first response has reached the client,
  so a retry can only re-open a stream that had not produced anything yet.
- **Get-or-create reads** whose name starts with a read verb but which act on the server are never retried:
  `ondewo.nlu.Sessions/GetSessionReview` and `GetLatestSessionReview` compute and store a review when none exists
  (`NON_IDEMPOTENT_DESPITE_NAME`).

The method list is derived from the generated `*_pb2` modules that the service class's module imports, once per class.
A caller can replace the whole policy by passing its own `("grpc.service_config", <json>)` in `options`.

Usage
-----

A service interface subclasses `BaseServicesInterface` (or `AsyncBaseServicesInterface` for `grpc.aio`) and exposes
its generated stub. Importing the stub module is also what lets the retry policy find the service's methods:

```python
from ondewo.utils.base_client_config import BaseClientConfig
from ondewo.utils.base_services_interface import BaseServicesInterface

from ondewo.vtsi import calls_pb2  # generated messages (illustrative module and names)
from ondewo.vtsi.calls_pb2_grpc import CallsStub  # generated stub


class Calls(BaseServicesInterface):
    @property
    def stub(self) -> CallsStub:
        return CallsStub(channel=self.grpc_channel)

    def start_callers(self, request: calls_pb2.StartCallersRequest) -> calls_pb2.StartCallersResponse:
        # A mutation: the channel never re-sends it. wait_for_ready waits for a connection instead,
        # and the timeout bounds the whole call.
        return self.stub.StartCallers(request, wait_for_ready=True, timeout=30)


config = BaseClientConfig(host="localhost", port="50051", grpc_cert=pem_text)  # PEM as str or bytes
calls = Calls(config=config, use_secure_channel=True)
```

Channel options are merged on top of the defaults, so one option can be overridden alone. Passing a
`("grpc.service_config", json_text)` option replaces the retry policy entirely:

```python
calls = Calls(config=config, use_secure_channel=True, options={("grpc.service_config", json_text)})
```

One connection for all services (low latency)
---------------------------------------------

By default every service interface opens its own channel, so a client with N services pays N channel set-ups, and
over TLS N TCP connections and N TLS handshakes (plaintext channels to the same target share one connection through
gRPC's subchannel pool, but each still pays its own set-up). Build one channel for all of them and hand it to each service; the
shared channel's retry policy gives every method exactly the policy it would have had on its own channel:

```python
import grpc

from ondewo.utils.base_services_interface import build_shared_channel

channel = build_shared_channel(config, use_secure_channel=True, service_classes=(Calls, Agents))
calls = Calls(config=config, use_secure_channel=True, grpc_channel=channel)
agents = Agents(config=config, use_secure_channel=True, grpc_channel=channel)

# Optional warm-up: connect (DNS, TCP, TLS) now instead of on the first RPC.
grpc.channel_ready_future(channel).result(timeout=10)
```

Measured on loopback, constructing 16 services and making one call on each took 44.1 ms with a channel per service
and 6.5 ms with one shared TLS channel. `disconnect()` closes a shared channel once.

The async twin is `ondewo.utils.async_base_services_interface.build_shared_channel`. Warm it up with
`channel.get_state(try_to_connect=True)` (starts connecting, returns at once) or `await channel.channel_ready()`.
**Construct async clients inside the running event loop that uses them**: a `grpc.aio` channel belongs to the loop
it was created in. Built outside a running loop (e.g. in sync code before `asyncio.run(...)`), the first RPC fails
with `RuntimeError: ... attached to a different loop`.

Connection defaults: recovery and dead connections
--------------------------------------------------

Every channel the library opens starts from these defaults (a caller's `options` override any of them):

| Option                                                            | Value      | Why                                                                                                   |
|-------------------------------------------------------------------|------------|-------------------------------------------------------------------------------------------------------|
| `grpc.max_reconnect_backoff_ms`                                   | 5000       | gRPC's 120 s cap meant 10-65 s until the first successful call after a 30-120 s outage; now 0.3-3.8 s |
| `grpc.http2.ping_timeout_ms`, `grpc.keepalive_timeout_ms`         | 20000      | A silently dropped connection is detected in ~40 s instead of ~85 s                                   |
| `grpc.keepalive_time_ms`                                          | 30000      | Pings only during active calls (`keepalive_permit_without_calls` off)                                 |
| `grpc.http2.max_pings_without_data`                               | 2          | More pings on a silent stream get a `too_many_pings` GOAWAY from a default server                     |
| `grpc.max_send_message_length`, `grpc.max_receive_message_length` | 2147483647 | No practical message size limit                                                                       |

`grpc.dns_enable_srv_queries` is deliberately not set: it only finds deprecated grpclb balancers and cost ~14 ms per
channel. Overriding `grpc.keepalive_time_ms` with `2**31-1` (keepalive off) also turns off dead-connection detection
on idle streams.
