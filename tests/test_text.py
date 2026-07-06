# Copyright 2021 ONDEWO GmbH
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

import pytest

from ondewo.utils.text import TextHelper


@pytest.mark.parametrize(
    "text, expected",
    [
        ("CamelCase", "camel_case"),
        ("simpleTest", "simple_test"),
        ("already_snake", "already_snake"),
        ("HTTPResponseCode", "http_response_code"),
        ("lowercase", "lowercase"),
        ("", ""),
    ],
)
def test_from_camel_to_snake_case(text: str, expected: str) -> None:
    assert TextHelper.from_camel_to_snake_case(text) == expected
