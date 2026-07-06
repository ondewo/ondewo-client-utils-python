# Copyright 2021-2026 ONDEWO GmbH
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

"""Text manipulation helpers for converting between naming conventions."""

from typing import Pattern

from regex import regex


class TextHelper:
    """
    Provide static helpers for transforming text between naming conventions.

    Attributes:
        FROM_CAMEL_TO_SNAKE_PATTERN (Pattern[str]):
            Compiled regular expression matching the boundaries inside a
            camelCase or PascalCase string where an underscore must be
            inserted to produce snake_case.
    """

    FROM_CAMEL_TO_SNAKE_PATTERN: Pattern[str] = regex.compile(r"((?<=[a-z])[A-Z]|(?!^)[A-Z](?=[a-z]))")

    @classmethod
    def from_camel_to_snake_case(cls, text: str) -> str:
        """
        Convert a camelCase or PascalCase string to snake_case.

        Args:
            text (str):
                The camelCase or PascalCase string to convert.

        Returns:
            str:
                The lower-cased snake_case representation of ``text``.
        """
        snaked: str = cls.FROM_CAMEL_TO_SNAKE_PATTERN.sub(r"_\1", text).lower()
        return snaked
