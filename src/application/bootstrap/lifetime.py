"""
Application lifetime management.
"""

from __future__ import annotations

from .bootstrap import bootstrap

from .container import ApplicationContainer

_container: ApplicationContainer | None = None

def get_container(
) -> ApplicationContainer:
    """
    Return the singleton application
    container.
    """
    global _container
    if _container is None:

        _container = bootstrap()

    return _container