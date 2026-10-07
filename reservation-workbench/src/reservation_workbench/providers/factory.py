"""Choose the provider from configuration. Missing credentials never crash startup."""

from __future__ import annotations

import os

from .anthropic_live import AnthropicLiveProvider, LiveSettings
from .offline import OfflineRulesProvider


def make_provider(mode: str | None = None):
    """``mode``: offline | live. Default from RW_PROVIDER, else offline.

    Live mode without a key still returns the live provider so the UI can show
    the problem explicitly; its calls fail with a recoverable error.
    """
    m = (mode or os.getenv("RW_PROVIDER", "offline")).strip().lower()
    if m == "live":
        return AnthropicLiveProvider(LiveSettings.from_env())
    return OfflineRulesProvider()
