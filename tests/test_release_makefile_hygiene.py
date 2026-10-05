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
    # Piping into another program's stdin (login_to_gh: `echo $(GITHUB_GH_TOKEN) | gh auth login
    # --with-token`) prints nothing and puts nothing on an argv (echo is a shell builtin).
    assert re.search(rf"echo\s+\$[{{(]{SECRET_NAMES}[}})](?![ \t]*\|)", MAKEFILE) is None


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
