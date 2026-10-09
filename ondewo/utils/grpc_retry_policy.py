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
"""The gRPC retry policy shared by the synchronous and the async ONDEWO service interfaces.

Only IDEMPOTENT methods get a configured retry policy. A configured retry re-sends a request
that the server may already be executing: a non-idempotent RPC (``StartCallers``, ``Create*``,
``Delete*``, ``DetectIntent``, ...) that loses its connection mid-flight, or answers
``DEADLINE_EXCEEDED`` / ``INTERNAL`` / ``UNKNOWN``, may well have acted, and a retry then acts
a second time. That is how ondewo-vtsi deployed one ``StartCallers`` batch twice: the server
sent a GOAWAY mid-deploy, the call failed with ``UNAVAILABLE`` and the old blanket policy
re-sent it. ``UNAVAILABLE`` is therefore NOT safe to retry for a non-idempotent method either.

Non-idempotent methods carry no retry policy at all. gRPC's own TRANSPARENT retries stay on
regardless of the service config: a request that provably never reached the server application
(e.g. a stream the server refused, or one above a GOAWAY's last-stream-id) is still re-sent once,
which is always safe. A caller that wants a non-idempotent RPC to survive a server that is not
reachable YET should pass ``wait_for_ready=True`` on the call, which waits for a connection
instead of re-sending a request.

A method counts as idempotent when its proto ``MethodOptions.idempotency_level`` is
``NO_SIDE_EFFECTS`` or ``IDEMPOTENT``, or, since no ONDEWO proto sets that option, when its name
starts with a read verb (:data:`READ_ONLY_METHOD_NAME_PATTERN`) and it is not one of the
get-or-create reads in :data:`NON_IDEMPOTENT_DESPITE_NAME`.

Public names: :func:`is_idempotent_method`, :func:`build_service_config_json`,
:func:`service_config_json_for`, :func:`service_config_json_for_classes`,
:data:`READ_ONLY_METHOD_NAME_PATTERN`, :data:`NON_IDEMPOTENT_DESPITE_NAME` and
:data:`IDEMPOTENT_RETRY_POLICY`.
"""

import json
import re
import sys
from functools import lru_cache
from types import ModuleType
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Optional,
    Pattern,
    Set,
    Tuple,
)

import grpc
from google.protobuf.descriptor import (
    MethodDescriptor,
    ServiceDescriptor,
)
from google.protobuf.descriptor_pb2 import MethodOptions

# The leading verb of every read-only RPC in the published ONDEWO client protos (nlu, qa, vtsi,
# sip, csi, s2t, t2s; 469 methods, none of which sets ``idempotency_level``). Matched as a whole
# word, so ``GetAgent`` and ``ListCallers`` match and a name such as ``Getaway`` does not. Verbs
# that merely LOOK side-effect free are deliberately absent: ``DetectIntent`` advances a session,
# ``Export*`` starts a long-running operation, ``Synthesize`` / ``Transcribe`` / ``Classify`` may
# persist results. Names that put a namespace before the verb (``SipGetSipStatus``,
# ``RagListDatasets``, ``LlmEvaluationGetReport``) do not match and fall back to the
# non-idempotent default, which only ever costs a retry, never a duplicate side effect.
READ_ONLY_METHOD_NAME_PATTERN: Pattern[str] = re.compile(r"^(?:BatchGet|Get|List|Check|Validate|Ping)(?=[A-Z0-9_]|$)")

# Methods whose name starts with a read verb but which act on the server, so they must never be
# retried (``MethodDescriptor.full_name`` form). ondewo-nlu-api ``session.proto``: both "return a
# session-review from ondewo-kb or compute the first review if none exists", i.e. a re-sent
# request after a server-side DEADLINE_EXCEEDED / INTERNAL could compute and store a second review.
# A proto that declares ``idempotency_level`` explicitly still wins over this list.
NON_IDEMPOTENT_DESPITE_NAME: FrozenSet[str] = frozenset(
    {
        "ondewo.nlu.Sessions.GetSessionReview",
        "ondewo.nlu.Sessions.GetLatestSessionReview",
    }
)

# gRPC clamps ``maxAttempts`` to the channel argument ``grpc.max_retry_attempts`` (default 5)
# and logs an error for anything above it, so 5 is the honest maximum.
IDEMPOTENT_RETRY_POLICY: Dict[str, Any] = {
    "maxAttempts": 5,
    "initialBackoff": "0.1s",
    "maxBackoff": "3s",
    "backoffMultiplier": 2,
    # NOT_FOUND and DATA_LOSS are omitted: both are definitive answers that a retry of the same
    # request cannot change. A deadline the CLIENT set is never retried by gRPC (the overall
    # deadline spans every attempt), so DEADLINE_EXCEEDED only retries a server-side one.
    "retryableStatusCodes": [
        grpc.StatusCode.CANCELLED.name,
        grpc.StatusCode.UNKNOWN.name,
        grpc.StatusCode.DEADLINE_EXCEEDED.name,
        grpc.StatusCode.RESOURCE_EXHAUSTED.name,
        grpc.StatusCode.ABORTED.name,
        grpc.StatusCode.INTERNAL.name,
        grpc.StatusCode.UNAVAILABLE.name,
    ],
}

# The default entry (``{}`` matches every method no other entry names) carries no retry policy,
# so a non-idempotent method is only ever retried transparently by gRPC itself.
_NON_IDEMPOTENT_METHOD_CONFIG: Dict[str, Any] = {"name": [{}]}

_IDEMPOTENCY_LEVELS: Set[int] = {MethodOptions.NO_SIDE_EFFECTS, MethodOptions.IDEMPOTENT}


def is_idempotent_method(method: MethodDescriptor) -> bool:
    """
    Decide whether a gRPC method may safely be re-sent after a failed attempt.

    Args:
        method (MethodDescriptor):
            The protobuf descriptor of the RPC method.

    Returns:
        bool:
            ``True`` if the proto declares the method ``NO_SIDE_EFFECTS`` or ``IDEMPOTENT``, or if
            its name starts with a read verb and it is not in :data:`NON_IDEMPOTENT_DESPITE_NAME`;
            ``False`` otherwise.
    """
    if method.GetOptions().idempotency_level in _IDEMPOTENCY_LEVELS:
        return True
    if method.full_name in NON_IDEMPOTENT_DESPITE_NAME:
        return False
    return READ_ONLY_METHOD_NAME_PATTERN.match(method.name) is not None


def build_service_config_json(services: List[ServiceDescriptor]) -> str:
    """
    Build the gRPC service config that retries the idempotent methods of the given services only.

    https://github.com/grpc/grpc-proto/blob/master/grpc/service_config/service_config.proto

    Args:
        services (List[ServiceDescriptor]):
            The services whose idempotent methods get :data:`IDEMPOTENT_RETRY_POLICY`. A service
            listed more than once (by ``full_name``) is named once: grpc-core rejects a config that
            names a method path twice, and then fails every RPC on the channel.

    Returns:
        str:
            The JSON service config; every method it does not name has no retry policy.
    """
    unique_services: Dict[str, ServiceDescriptor] = {}
    for service in services:
        unique_services.setdefault(service.full_name, service)
    idempotent_method_names: List[Dict[str, str]] = [
        {"service": service.full_name, "method": method.name}
        for service in unique_services.values()
        for method in service.methods
        if is_idempotent_method(method)
    ]
    method_config: List[Dict[str, Any]] = []
    if idempotent_method_names:
        method_config.append({"name": idempotent_method_names, "retryPolicy": IDEMPOTENT_RETRY_POLICY})
    method_config.append(_NON_IDEMPOTENT_METHOD_CONFIG)
    return json.dumps({"methodConfig": method_config})


def _pb2_module_name(value: Any) -> Optional[str]:
    """
    Return the name of the ``*_pb2`` module a module-level value belongs to, if any.

    Args:
        value (Any):
            A module-level value: an imported module (``calls_pb2``) or class (``CallsStub``).

    Returns:
        Optional[str]:
            The ``*_pb2`` module name (a ``*_pb2_grpc`` module maps to its ``*_pb2`` sibling), or
            ``None`` if the value is not tied to a generated protobuf module.
    """
    if isinstance(value, ModuleType):
        name: Any = value.__name__
    elif isinstance(value, type):
        name = value.__module__
    else:
        return None
    # Some extension types (e.g. Cython's shared ``coroutine``) expose a descriptor, not a str.
    if not isinstance(name, str):
        return None
    if name.endswith("_pb2_grpc"):
        name = name[: -len("_grpc")]
    return name if name.endswith("_pb2") else None


def _services_for(service_class: type) -> Dict[str, ServiceDescriptor]:
    """
    Find the gRPC services a service-interface class uses, keyed by full name.

    A concrete ONDEWO service interface (e.g. ``ondewo.vtsi.client.services.calls.Calls``) lives in
    a module that imports its stub (``from ondewo.vtsi.calls_pb2_grpc import CallsStub``) and
    usually its messages (``from ondewo.vtsi import calls_pb2``). Those generated ``*_pb2`` modules
    carry the ``FileDescriptor`` whose ``services_by_name`` lists every RPC. They are imported by
    the time the class is instantiated, so the modules of the class and its bases are scanned for
    them.

    Args:
        service_class (type):
            The concrete service-interface class.

    Returns:
        Dict[str, ServiceDescriptor]:
            Every service of every ``*_pb2`` module found, keyed by ``full_name``; empty if none.
    """
    pb2_module_names: Set[str] = set()
    for klass in service_class.__mro__:
        module: Optional[ModuleType] = sys.modules.get(klass.__module__)
        if module is None:
            continue
        for value in vars(module).values():
            pb2_module_name: Optional[str] = _pb2_module_name(value)
            if pb2_module_name is not None:
                pb2_module_names.add(pb2_module_name)

    services: Dict[str, ServiceDescriptor] = {}
    for pb2_module_name in pb2_module_names:
        file_descriptor: Any = getattr(sys.modules.get(pb2_module_name), "DESCRIPTOR", None)
        for service in getattr(file_descriptor, "services_by_name", {}).values():
            services[service.full_name] = service
    return services


@lru_cache(maxsize=None)
def service_config_json_for(service_class: type) -> str:
    """
    Build, once per class, the service config for the stubs a service-interface class uses.

    The services are found as described in :func:`_services_for`. A service that cannot be found
    simply gets the non-idempotent default: fewer retries, never a duplicated side effect.

    Args:
        service_class (type):
            The concrete service-interface class being instantiated.

    Returns:
        str:
            The JSON service config for that class (see :func:`build_service_config_json`).
    """
    services: Dict[str, ServiceDescriptor] = _services_for(service_class)
    return build_service_config_json([services[name] for name in sorted(services)])


@lru_cache(maxsize=None)
def service_config_json_for_classes(service_classes: Tuple[type, ...]) -> str:
    """
    Build, once per tuple of classes, ONE service config for a channel shared by several services.

    ``methodConfig`` names each method by fully qualified service and method, so the union gives
    every method exactly the policy :func:`service_config_json_for` gives it for its own class: a
    shared channel changes no method's retry behaviour.

    Args:
        service_classes (Tuple[type, ...]):
            The service-interface classes that will share one channel (a tuple, so it is hashable).

    Returns:
        str:
            The JSON service config covering the services of every class.
    """
    services: Dict[str, ServiceDescriptor] = {}
    for service_class in service_classes:
        services.update(_services_for(service_class))
    return build_service_config_json([services[name] for name in sorted(services)])
