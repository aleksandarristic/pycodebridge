"""Backward-compatible router module shim."""

from .routing.router import *  # noqa: F401,F403
from .routing.router import _ThreadContextSink  # noqa: F401
