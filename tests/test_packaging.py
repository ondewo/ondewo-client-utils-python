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
"""Packaging: the wheel ships ``py.typed``; the sdist ships no half test suite."""

import tomllib
from pathlib import Path
from typing import Any, Dict

import ondewo.utils

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def test_py_typed_marker_exists_in_the_package() -> None:
    """Verify ``ondewo/utils/py.typed`` exists next to the package modules."""
    assert (Path(ondewo.utils.__file__).parent / "py.typed").is_file()


def test_package_data_ships_the_py_typed_marker() -> None:
    """Verify pyproject's setuptools package-data includes ``py.typed`` for ``ondewo.utils``."""
    pyproject: Dict[str, Any] = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "py.typed" in pyproject["tool"]["setuptools"]["package-data"]["ondewo.utils"]


def test_the_sdist_leaves_the_tests_out() -> None:
    """
    Verify MANIFEST.in prunes ``tests``.

    setuptools adds ``tests/test_*.py`` on its own but not ``conftest.py`` or the fixtures, so an
    sdist built outside the release image carried a suite that could not run, and differed from
    the one released from the image (which has no ``tests/``).
    """
    assert "prune tests" in (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
