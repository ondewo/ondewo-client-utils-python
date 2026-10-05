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
"""Pin the ticket-prefix stripping of ``scripts/hooks/conventional_commit_msg.py``."""

import importlib.util
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Optional

import pytest

HOOK: Path = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "conventional_commit_msg.py"


def _load_hook() -> ModuleType:
    """
    Import the hook script by path (``scripts/`` is not a package).

    Returns:
        ModuleType:
            The loaded hook module.
    """
    spec: Optional[ModuleSpec] = importlib.util.spec_from_file_location("conventional_commit_msg", HOOK)
    assert spec is not None and spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "message, expected",
    [
        ("[OND233-367] fix: x", "fix: x"),
        ("fix: x", "fix: x"),
        ("[OND233-367] [OND233-367] fix: x", "[OND233-367] fix: x"),
        ("fix: x\n\n[OND233-367] in the body stays", "fix: x\n\n[OND233-367] in the body stays"),
    ],
)
def test_one_leading_ticket_prefix_is_stripped(message: str, expected: str) -> None:
    """Verify exactly one leading ``[<TICKET>] `` is removed and nothing else changes."""
    assert _load_hook().strip_ticket_prefix(message) == expected
