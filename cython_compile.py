# Copyright 2020-2024 ONDEWO GmbH
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

"""Cythonize the pure-Python ``ondewo`` modules into native C extensions.

Every ``ondewo`` module is compiled to a C extension, except for files that cannot
(or should not) be cythonized:

* files that define a ``@dataclass`` — Cython does not support dataclasses, so
  (following the ONDEWO cythonization standard) they are left as plain ``.py`` files;
* package markers and tooling-read files (``__init__.py``, ``version.py``) — the latter
  is parsed as text by ``setup.py`` and the ``Makefile`` and therefore must stay ``.py``.

Cython's annotation-based typing is disabled (``annotation_typing=False``) so that the
PEP 484 type hints added for static analysis are treated as pure Python annotations and
do not alter the compiled behaviour.

Usage:
    python cython_compile.py build_ext --inplace
"""

import os
from typing import (
    List,
    Set,
)

from Cython.Build import cythonize
from setuptools import setup

#: File names that must never be cythonized (package markers / tooling-read files).
SKIP_FILENAMES: Set[str] = {"__init__.py", "version.py"}

#: Root package directory that is walked for cythonizable modules.
PACKAGE_ROOT: str = "ondewo"


def find_modules(root: str = PACKAGE_ROOT) -> List[str]:
    """
    Collect the pure-Python modules that are safe to cythonize.

    Walks ``root`` recursively and returns every ``.py`` file that is neither a
    skipped file name (:data:`SKIP_FILENAMES`) nor a module defining a ``@dataclass``.

    Args:
        root (str):
            Directory to search for modules. Defaults to :data:`PACKAGE_ROOT`.

    Returns:
        List[str]:
            Sorted list of module file paths to hand to Cython.
    """
    modules: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not filename.endswith(".py") or filename in SKIP_FILENAMES:
                continue
            path: str = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as handle:
                if "@dataclass" in handle.read():
                    # Cython does not support dataclasses; keep the module as pure Python.
                    continue
            modules.append(path)
    return sorted(modules)


def main() -> None:
    """
    Cythonize and build the discovered modules in place.

    Returns:
        None
    """
    modules: List[str] = find_modules()
    print("Cythonizing:\n  " + "\n  ".join(modules))
    setup(
        name="ondewo-client-utils-cython",
        ext_modules=cythonize(
            modules,
            language_level="3",
            compiler_directives={"annotation_typing": False},
        ),
        zip_safe=False,
    )


if __name__ == "__main__":
    main()
