"""
Outbound HTTP client helpers for platform APIs.
"""

import ssl
from functools import lru_cache

import certifi
import httpx


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """
    One SSL context for the whole process.

    Building a context loads the CA bundle (~0.5s). httpx does that for every
    new AsyncClient, which serialized concurrent requests: 14 parallel week
    fetches took ~10s instead of ~0.3s.
    """
    return ssl.create_default_context(cafile=certifi.where())


def async_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """A new AsyncClient that reuses the shared SSL context."""
    return httpx.AsyncClient(timeout=timeout, verify=ssl_context())
