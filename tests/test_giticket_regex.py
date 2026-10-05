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
Pin the giticket regex as configured in ``.pre-commit-config.yaml``.

giticket uses ONE regex twice: ``findall`` on the branch name to find the ticket, and ``search`` on
every line of the message to decide it "already has a ticket". Unanchored, an already prefixed
subject was not recognised (an amend got a double prefix) and a body that merely mentioned a ticket
branch silently dropped the prefix.
"""

import re
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Pattern,
)

import pytest
import yaml

PRE_COMMIT_CONFIG: Path = Path(__file__).resolve().parent.parent / ".pre-commit-config.yaml"


def _giticket_regex() -> Pattern[str]:
    """
    Load the ``--regex=`` argument of the giticket hook.

    Returns:
        Pattern[str]:
            The compiled regex exactly as giticket receives it.
    """
    config: Dict[str, Any] = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    args: List[str] = [
        arg
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "giticket"
        for arg in hook.get("args", [])
        if arg.startswith("--regex=")
    ]
    assert len(args) == 1
    return re.compile(args[0][len("--regex=") :])


@pytest.mark.parametrize(
    "branch, ticket",
    [
        ("feature/OND233-367-retry-only-idempotent-methods", "OND233-367"),
        ("OND211-2418-add-keycloak-for-2-fa", "OND211-2418"),
        ("bugfix/OND233-1_fix", "OND233-1"),
    ],
)
def test_the_ticket_is_found_in_a_branch_name(branch: str, ticket: str) -> None:
    """Verify ``findall`` on a ticket branch yields exactly its ticket."""
    assert _giticket_regex().findall(branch) == [ticket]


@pytest.mark.parametrize("line", ["[OND233-367] fix: x", "Merge branch develop", "Merge pull request #3 from x"])
def test_lines_that_already_carry_a_ticket_or_are_merges_match(line: str) -> None:
    """Verify a prefixed subject (no double prefix on amend) and merge subjects are recognised."""
    assert _giticket_regex().search(line) is not None


@pytest.mark.parametrize(
    "line",
    ["Port of OND211-2418-add-keycloak work", "fix(grpc): retry", "measured on feature/OND233-367-x today", "develop"],
)
def test_ordinary_lines_do_not_match(line: str) -> None:
    """Verify a body line merely MENTIONING a ticket branch does not cost the commit its prefix."""
    assert _giticket_regex().search(line) is None
