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

Or, you could clone it and install the requirements:

```bash
git clone git@github.com:ondewo/ondewo-client-utils-python.git
cd ondewo-client-utils-python
pip install -e .
```

gRPC retry policy
-----------------

Every service interface built on `BaseServicesInterface` / `AsyncBaseServicesInterface` opens its channel with
`grpc.enable_retries` on and a per-service retry policy that **retries idempotent methods only**:

- **Idempotent** methods — the proto declares `idempotency_level = NO_SIDE_EFFECTS` or `IDEMPOTENT`, or the method name
  starts with a read verb (`Get`, `List`, `BatchGet`, `Check`, `Validate`, `Ping`) — are retried up to 5 attempts on
  `UNAVAILABLE`, `DEADLINE_EXCEEDED`, `INTERNAL`, `UNKNOWN`, `RESOURCE_EXHAUSTED`, `ABORTED` and `CANCELLED`.
- **Every other method** (`Start*`, `Create*`, `Update*`, `Delete*`, `DetectIntent`, streaming RPCs, ...) has **no**
  configured retry policy, on any status code including `UNAVAILABLE`: a failed attempt may already have acted on the
  server, and re-sending it would act twice. gRPC's own transparent retries, which only re-send a request that provably
  never reached the server application, stay on. To ride out a server that is not reachable *yet*, pass
  `wait_for_ready=True` on the call: it waits for a connection instead of re-sending a request.

The method list is derived from the generated `*_pb2` modules that the service class's module imports, once per class.
A caller can replace the whole policy by passing its own `("grpc.service_config", <json>)` in `options`.
