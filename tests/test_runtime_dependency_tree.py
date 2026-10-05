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
Pin the RUNTIME dependency tree: dataclasses-json and marshmallow must not come back.

Every ONDEWO client SDK (and through them ondewo-cai, which git-pinned an unreleased commit of this
package only to get rid of both) inherits this package's runtime closure.
"""

import tomllib
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Set,
)

REPO_ROOT: Path = Path(__file__).resolve().parent.parent


def _runtime_closure() -> Set[str]:
    """
    Walk ``uv.lock`` from this project's runtime dependencies (no extras) to every transitive one.

    Returns:
        Set[str]:
            The names of every package a plain ``pip install ondewo-client-utils`` resolves.
    """
    lock: Dict[str, Any] = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages: Dict[str, Dict[str, Any]] = {package["name"]: package for package in lock["package"]}
    closure: Set[str] = set()
    pending: List[str] = [dependency["name"] for dependency in packages["ondewo-client-utils"]["dependencies"]]
    while pending:
        name: str = pending.pop()
        if name not in closure:
            closure.add(name)
            pending.extend(dependency["name"] for dependency in packages[name].get("dependencies", []))
    return closure


def test_neither_dataclasses_json_nor_marshmallow_is_a_runtime_dependency() -> None:
    """Verify the locked runtime closure holds orjson and none of the dataclasses-json chain."""
    closure: Set[str] = _runtime_closure()
    assert "orjson" in closure
    assert not closure & {"dataclasses-json", "marshmallow", "typing-inspect"}


def test_pyproject_declares_orjson_and_not_dataclasses_json() -> None:
    """Verify the declared dependencies, which downstream resolves against instead of this lock."""
    declared: str = " ".join(
        tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    )
    assert "orjson>=" in declared
    assert "dataclasses-json" not in declared and "marshmallow" not in declared
