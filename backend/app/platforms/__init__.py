"""
Fantasy sports platform adapters.

Provides a unified interface for fetching league data from different
fantasy sports platforms.
"""

from typing import Optional

from .base import (
    PlatformAdapter,
    LeagueNotFoundError,
    LeaguePrivateError,
    PlatformError
)
from .espn import ESPNAdapter
from .yahoo import YahooAdapter
from .sleeper import SleeperAdapter
from .fantrax import FantraxAdapter
from .cbs import CBSAdapter
from ..core.sports import Sport
from ..db.models import YahooCredential, CBSCredential


def get_adapter(
    platform: str,
    sport: Optional[Sport] = None,
    yahoo_credential: Optional[YahooCredential] = None,
    cbs_credential: Optional[CBSCredential] = None
) -> PlatformAdapter:
    """
    Get the appropriate adapter for a fantasy sports platform.

    Args:
        platform: Platform name ('espn', 'yahoo', 'sleeper', 'fantrax', 'cbs')
        sport: The sport type (defaults to basketball for backwards compatibility)
        yahoo_credential: Yahoo OAuth credential (required for Yahoo platform)
        cbs_credential: CBS OAuth credential (required for CBS platform)

    Returns:
        Platform adapter instance

    Raises:
        ValueError: If the platform is not supported or Yahoo credential is missing
    """
    if sport is None:
        sport = Sport.BASKETBALL

    platform_lower = platform.lower()

    if platform_lower == "espn":
        return ESPNAdapter(sport=sport)

    if platform_lower == "yahoo":
        if yahoo_credential is None:
            raise ValueError("Yahoo credential is required to access Yahoo Fantasy leagues")
        return YahooAdapter(sport=sport, credential=yahoo_credential)

    if platform_lower == "sleeper":
        return SleeperAdapter(sport=sport)

    if platform_lower == "fantrax":
        return FantraxAdapter(sport=sport)

    if platform_lower == "cbs":
        if cbs_credential is None:
            raise ValueError("CBS credential is required to access CBS Sports Fantasy leagues")
        return CBSAdapter(sport=sport, credential=cbs_credential)

    supported = "espn, yahoo, sleeper, fantrax, cbs"
    raise ValueError(f"Unsupported platform: {platform}. Supported: {supported}")


__all__ = [
    "PlatformAdapter",
    "LeagueNotFoundError",
    "LeaguePrivateError",
    "PlatformError",
    "ESPNAdapter",
    "YahooAdapter",
    "SleeperAdapter",
    "FantraxAdapter",
    "CBSAdapter",
    "get_adapter",
    "Sport",
]
