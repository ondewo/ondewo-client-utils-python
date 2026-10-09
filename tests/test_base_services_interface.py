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
Unit tests for :mod:`ondewo.utils.base_services_interface`.

Covers the sync-only parts: the message-size constant, a real insecure channel, and the insecure-channel
warning. Everything both interfaces share is pinned for both in ``test_channel_option_contract.py``.
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

from ondewo.utils import base_services_interface as bsi
from ondewo.utils.base_services_interface import (
    MAX_MESSAGE_LENGTH,
    BaseServicesInterface,
)
from tests.conftest import (
    CALL_TIMEOUT_IN_S,
    local_config,
)


class _ConcreteService(BaseServicesInterface):
    """
    Minimal concrete :class:`BaseServicesInterface` used to exercise the base class.

    The abstract ``stub`` property is implemented with a sentinel string so the
    otherwise-abstract base class can be instantiated within the tests.
    """

    @property
    def stub(self) -> Any:
        """
        Return the service stub sentinel.

        Returns:
            Any:
                A placeholder stub value used by the tests.
        """
        return "the-stub"


def test_max_message_length_is_int32_max() -> None:
    """Verify ``MAX_MESSAGE_LENGTH`` equals the signed 32-bit integer maximum."""
    assert MAX_MESSAGE_LENGTH == 2**31 - 1


def test_insecure_channel_without_options(
    edge_server: Tuple[str, Dict[str, int], Dict[str, List[grpc.StatusCode]]],
) -> None:
    """Verify a real insecure channel with every default option, the service config included, can call."""
    service: _ConcreteService = _ConcreteService(
        config=local_config(host="127.0.0.1", port=edge_server[0]), use_secure_channel=False
    )
    try:
        assert service.stub == "the-stub"
        with pytest.raises(grpc.RpcError) as raised:
            service.grpc_channel.unary_unary("/e.S/Nope")(b"", timeout=CALL_TIMEOUT_IN_S)
        # gRPC parses the options on the first call: a rejected one answers INVALID_ARGUMENT instead.
        assert raised.value.code() is grpc.StatusCode.UNIMPLEMENTED  # type: ignore[attr-defined]
    finally:
        service.grpc_channel.close()


def test_insecure_warning_uses_a_module_logger_and_names_the_target(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the insecure warning leaves the root logger alone and names the plaintext target."""
    root: logging.Logger = logging.getLogger()
    # A host application that configured no logging: module-level logging.warning() would run
    # basicConfig() here and leave a stderr handler on the root logger.
    monkeypatch.setattr(root, "handlers", [])
    _ConcreteService(config=local_config(), use_secure_channel=False).grpc_channel.close()
    assert root.handlers == []

    monkeypatch.setattr(root, "handlers", [caplog.handler])
    with caplog.at_level(logging.WARNING, logger="ondewo.utils.base_services_interface"):
        _ConcreteService(config=local_config(), use_secure_channel=False).grpc_channel.close()
    records: List[logging.LogRecord] = [r for r in caplog.records if r.name == "ondewo.utils.base_services_interface"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "localhost:50051" in records[0].getMessage()


def test_srv_queries_are_not_enabled_by_default() -> None:
    """Verify the grpclb-only SRV lookup is off (15.9 ms vs 1.4 ms per channel to 127.0.0.1)."""
    assert "grpc.dns_enable_srv_queries" not in bsi._DEFAULT_GRPC_OPTIONS
