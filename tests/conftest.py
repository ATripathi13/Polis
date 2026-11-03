"""
Pytest configuration for POLIS tests.
Exposes shared fixtures including the centralized staging safety gate.
"""

from __future__ import annotations

import pytest

from tests.staging_safety_gate import staging_safety_gate

__all__ = ["staging_safety_gate"]
