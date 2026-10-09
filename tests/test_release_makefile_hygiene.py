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
Release credentials never reach a console, an argv or a floating image.

``/proc/<pid>/cmdline`` is world-readable, so a password on twine's or docker's command line is
visible to every user on the host for the life of the process; an ``echo`` puts it in the CI log.
"""

import re
from pathlib import Path
from typing import List

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
MAKEFILE: str = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
DOCKERFILE_UTILS: str = (REPO_ROOT / "Dockerfile.utils").read_text(encoding="utf-8")

SECRET_NAMES: str = r"(?:PYPI_PASSWORD|GITHUB_GH_TOKEN)"


def test_no_recipe_echoes_a_secret() -> None:
    """Verify no recipe line prints the PyPI password or the GitHub token to the console."""
    assert re.search(rf"echo\s+\$[{{(]{SECRET_NAMES}[}})](?![ \t]*\|)", MAKEFILE) is None


def test_make_never_expands_a_secret_into_a_recipe_line() -> None:
    """
    Verify no recipe line carries ``$(PYPI_PASSWORD)`` / ``$(GITHUB_GH_TOKEN)``.

    make expands ``$(NAME)`` BEFORE the shell runs, so the value lands on the argv of ``/bin/sh -c``
    even when it is only piped into another program (``login_to_gh`` did exactly that). A recipe reads
    a secret as ``$${NAME}``, which the shell expands from the exported environment.
    """
    recipe_lines: List[str] = [line for line in MAKEFILE.splitlines() if line.startswith("\t")]
    assert [line for line in recipe_lines if re.search(rf"(?<!\$)\$[{{(]{SECRET_NAMES}[}})]", line)] == []


def test_the_devops_release_hands_the_credentials_over_the_environment() -> None:
    """Verify ``run_release_with_devops`` does not start ``make release NAME=<value>`` (make's argv)."""
    recipe: str = MAKEFILE.split("run_release_with_devops:", 1)[1].split("\n\n", 1)[0]
    assert "$(info)" not in recipe
    assert "set -a" in recipe
    assert re.search(r"\$\(MAKE\) release\s*$", recipe) is not None


def test_twine_never_gets_the_password_on_its_argv() -> None:
    """Verify twine reads the password from the environment, not from ``-p<password>``."""
    assert re.search(r"-p\s*\$[{(]PYPI_PASSWORD[})]", MAKEFILE) is None
    assert 'TWINE_PASSWORD="$${PYPI_PASSWORD}"' in MAKEFILE


def test_docker_run_never_gets_a_secret_value_on_its_argv() -> None:
    """Verify ``docker run -e`` forwards the secrets by name only, never ``-e NAME=<value>``."""
    assert re.search(rf"-e\s+{SECRET_NAMES}=", MAKEFILE) is None
    assert re.search(r"-e\s+PYPI_PASSWORD\s", MAKEFILE) is not None
    assert re.search(r"-e\s+GITHUB_GH_TOKEN\s", MAKEFILE) is not None


def test_the_release_image_pins_uv() -> None:
    """Verify the release image copies uv from a pinned tag, not the floating ``:latest``."""
    uv_copies: List[str] = re.findall(r"ghcr\.io/astral-sh/uv:(\S+)", DOCKERFILE_UTILS)
    assert uv_copies
    assert all(tag != "latest" and re.fullmatch(r"\d+\.\d+\.\d+", tag) for tag in uv_copies)


def test_the_release_guard_matches_the_branch_and_tag_exactly() -> None:
    """
    Verify ``spc`` asks git for the exact release branch and tag, not a ``grep`` substring.

    ``grep "4.1.0"`` also matches ``14.1.0``, ``4.1.0rc1`` and ``release/4.1.01``, so the guard
    would refuse a release whose version merely appears inside an older one.
    """
    recipe: str = MAKEFILE.split("\nspc:", 1)[1].split("\n\n", 1)[0]
    assert "grep" not in recipe
    assert 'git tag --list "${ONDEWO_PACKAGE_VERSION}"' in recipe
    assert (
        'git branch --all --list "release/${ONDEWO_PACKAGE_VERSION}" "origin/release/${ONDEWO_PACKAGE_VERSION}"'
        in recipe
    )


def test_the_release_guard_stops_on_an_existing_ref_and_asks_origin() -> None:
    """
    Verify ``spc`` exits with ``&& exit 1`` and also checks origin by exact ref name.

    ``echo ... & exit 1`` backgrounded the echo; local refs alone can be stale.
    """
    recipe: str = MAKEFILE.split("\nspc:", 1)[1].split("\n\n", 1)[0]
    assert "& exit" not in recipe.replace("&& exit", "")
    assert (
        'git ls-remote origin "refs/heads/release/${ONDEWO_PACKAGE_VERSION}" "refs/tags/${ONDEWO_PACKAGE_VERSION}"'
        in recipe
    )
