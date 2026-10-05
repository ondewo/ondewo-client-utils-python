# Release History

*****************

## Unreleased

### Breaking Changes

* The gRPC retry policy now retries idempotent methods only. Methods declared `NO_SIDE_EFFECTS` / `IDEMPOTENT` in their proto, or whose name starts with `Get`, `List`, `BatchGet`, `Check`, `Validate` or `Ping`, are retried up to 5 attempts on transient status codes (no longer on `NOT_FOUND` / `DATA_LOSS`). Every other method is no longer retried on any status code, `UNAVAILABLE` included, because a failed attempt may already have acted on the server; gRPC's transparent retries stay on. Pass `wait_for_ready=True` to wait for a server that is not reachable yet, or your own `grpc.service_config` option to restore a different policy

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.2.0

### New Features

* Added a test suite with 100% code coverage
* Added a GitHub Actions workflow that runs the tests on every push and pull request

### Improvements

* Serialize the gRPC service config and default channel options once at import instead of on every service construction to reduce client construction latency
* Enabled gRPC keepalive to keep long-lived streaming RPCs warm and detect half-open connections
* Updated GitHub Actions to their Node 24 releases to remove the Node 20 deprecation warnings
* Documented all Makefile targets and added a CLAUDE.md with repository and development guidance

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.1.0

### Improvements

* Added async client functionality

*****************

## Release ONDEWO CLIENT UTILS PYTHON 3.0.0

### Improvements

* Automated versioning of the package

*****************

## Release ONDEWO CLIENT UTILS PYTHON 2.0.0

### Improvements

* Added functionality to pass grpc options to grpc clients

*****************

## Release ONDEWO CLIENT UTILS PYTHON 1.0.1

### Improvements

* Relaxed requirements of grpc libraries

*****************

## Release ONDEWO CLIENT UTILS PYTHON 1.0.0

### Improvements

* Upgraded pre-commit hook configurations

*****************

## Release ONDEWO CLIENT UTILS PYTHON 0.1.1

### New Features

* Use latest version of dataclasses-json and regex

## Release ONDEWO CLIENT UTILS PYTHON 0.1.0

### New Features

* First release with common interfaces on Python Clients
