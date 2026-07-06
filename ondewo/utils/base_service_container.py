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
"""Base dataclass that concrete ONDEWO gRPC clients subclass to enumerate their service stubs."""

from dataclasses import dataclass


@dataclass
class BaseServicesContainer:
    """
    Provide a common base for grouping gRPC service stubs behind a consistent interface.

    Concrete ONDEWO gRPC clients subclass this dataclass and declare one typed
    attribute per gRPC service they expose (for example ``users`` or ``agents``),
    giving every client a uniform way of holding and accessing its service stubs.

    This base class intentionally declares no attributes and has an empty body;
    it exists solely to be extended by concrete containers. The ``@dataclass``
    decorator is retained so that subclasses inherit dataclass semantics.
    """

    pass
