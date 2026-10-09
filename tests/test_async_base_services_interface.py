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

"""
Async unit tests for :class:`ondewo.utils.async_base_services_interface.AsyncBaseServicesInterface`.

Covers the async-only parts: a real ``grpc.aio`` channel, the insecure-channel warning, and the parity
of the hand-maintained default options with the sync module. Everything both interfaces share is pinned
for both in ``test_channel_option_contract.py``.
"""

import logging
from typing import (
    Any,
    Dict,
    List,
    Tuple,
)

import grpc
import pytest

from ondewo.utils import async_base_services_interface as absi
from ondewo.utils import base_services_interface as bsi
from ondewo.utils.async_base_services_interface import AsyncBaseServicesInterface
from tests.conftest import (
    CALL_TIMEOUT_IN_S,
    local_config,
)


class _ConcreteAsyncService(AsyncBaseServicesInterface):
    """
    Minimal concrete :class:`AsyncBaseServicesInterface` used for testing.

    The abstract base class cannot be instantiated directly, so this subclass
    provides a trivial :pyattr:`stub` implementation to exercise the asynchronous
    channel construction performed in ``AsyncBaseServicesInterface.__init__``.
    """

    @property
    def stub(self) -> Any:
        """
        Return a placeholder stub identifying this concrete test service.

        Returns:
            Any:
                The constant sentinel string ``"the-async-stub"``.
        """
        return "the-async-stub"


async def test_insecure_channel_without_options(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify a real ``grpc.aio`` channel with every default option, the service config included, can call."""
    service: _ConcreteAsyncService = _ConcreteAsyncService(
        config=local_config(host="127.0.0.1", port=edge_server[0]), use_secure_channel=False
    )
    try:
        assert service.stub == "the-async-stub"
        with pytest.raises(grpc.aio.AioRpcError) as raised:
            await service.grpc_channel.unary_unary("/e.S/Nope")(b"", timeout=CALL_TIMEOUT_IN_S)
        # gRPC parses the options on the first call: a rejected one answers INVALID_ARGUMENT instead.
        assert raised.value.code() is grpc.StatusCode.UNIMPLEMENTED
    finally:
        await service.grpc_channel.close(grace=None)


async def test_insecure_warning_uses_a_module_logger_and_names_the_target(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the insecure warning leaves the root logger alone and names the plaintext target."""
    root: logging.Logger = logging.getLogger()
    # A host application that configured no logging: module-level logging.warning() would run
    # basicConfig() here and leave a stderr handler on the root logger.
    monkeypatch.setattr(root, "handlers", [])
    unconfigured: _ConcreteAsyncService = _ConcreteAsyncService(config=local_config(), use_secure_channel=False)
    assert root.handlers == []
    await unconfigured.grpc_channel.close(grace=None)

    monkeypatch.setattr(root, "handlers", [caplog.handler])
    with caplog.at_level(logging.WARNING, logger="ondewo.utils.async_base_services_interface"):
        service: _ConcreteAsyncService = _ConcreteAsyncService(config=local_config(), use_secure_channel=False)
    records: List[logging.LogRecord] = [
        r for r in caplog.records if r.name == "ondewo.utils.async_base_services_interface"
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "localhost:50051" in records[0].getMessage()
    await service.grpc_channel.close(grace=None)


def test_sync_and_async_default_options_are_identical() -> None:
    """Verify the two hand-maintained copies of the default channel options cannot drift."""
    assert absi.MAX_MESSAGE_LENGTH == bsi.MAX_MESSAGE_LENGTH
    assert dict(bsi._DEFAULT_GRPC_OPTIONS) == absi._DEFAULT_GRPC_OPTIONS
