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
Pin the declared protobuf range: downstream SDKs resolve against it, not against this repo's lock.

PYSEC-2026-1805 is fixed in 5.29.6 / 6.33.5 and PYSEC-2026-1806 in 5.29.5 / 6.31.1.
"""

import tomllib
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
)

import pytest
from packaging.requirements import Requirement


PYPROJECT: Path = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _protobuf_requirement() -> Requirement:
    """
    Return the protobuf requirement declared in ``[project].dependencies``.

    Returns:
        Requirement:
            The parsed requirement.
    """
    pyproject: Dict[str, Any] = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    requirements: List[Requirement] = [Requirement(dep) for dep in pyproject["project"]["dependencies"]]
    (protobuf,) = [requirement for requirement in requirements if requirement.name == "protobuf"]
    return protobuf


@pytest.mark.parametrize("version", ["5.27.2", "5.29.5", "6.30.2", "6.31.1", "6.32.0", "6.33.4", "8.0.0"])
def test_vulnerable_or_untested_protobuf_versions_are_rejected(version: str) -> None:
    """Verify the declared range excludes every protobuf release with PYSEC-2026-1805/1806, and 8.x."""
    assert not _protobuf_requirement().specifier.contains(version)


@pytest.mark.parametrize("version", ["5.29.6", "6.33.5", "6.33.6", "7.35.1"])
def test_fixed_protobuf_versions_are_accepted(version: str) -> None:
    """Verify the fixed releases of every supported line stay installable."""
    assert _protobuf_requirement().specifier.contains(version)
