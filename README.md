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

You can install the library by installing it directly from the pypi:

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

By default every service interface opens its own channel, so a client with N services opens N TCP connections and
pays N name resolutions and N TLS handshakes. Build one channel for all of them and hand it to each service; the
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
it was created in.
