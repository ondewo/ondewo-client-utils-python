"""Namespace package root for the ``ondewo`` distribution family.

Extends ``__path__`` via :func:`pkgutil.extend_path` so that sibling ``ondewo.*``
distributions installed in separate locations share the single ``ondewo`` namespace.
"""

__path__ = __import__("pkgutil").extend_path(__path__, __name__)  # type: ignore
