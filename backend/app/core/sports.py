"""
Sport enum and season utilities for multi-sport support.
"""

from enum import Enum
from datetime import datetime


class Sport(str, Enum):
    """Supported fantasy sports."""
    BASKETBALL = "basketball"
    FOOTBALL = "football"
    BASEBALL = "baseball"
    HOCKEY = "hockey"


# ESPN API sport codes
ESPN_SPORT_CODES = {
    Sport.BASKETBALL: "fba",  # Fantasy Basketball
    Sport.FOOTBALL: "ffl",    # Fantasy Football
    Sport.BASEBALL: "flb",    # Fantasy Baseball
    Sport.HOCKEY: "fhl",      # Fantasy Hockey
}

# Yahoo Fantasy game keys
# These map to the game_key portion of Yahoo's league identifiers
YAHOO_GAME_KEYS = {
    Sport.BASKETBALL: "nba",
    Sport.FOOTBALL: "nfl",
    Sport.BASEBALL: "mlb",
    Sport.HOCKEY: "nhl",
}

# Sleeper API sport codes
# Note: Sleeper does not support baseball
SLEEPER_SPORT_CODES = {
    Sport.FOOTBALL: "nfl",
    Sport.BASKETBALL: "nba",
}

# Fantrax API sport codes
# Note: Fantrax also supports Soccer, Golf, Racing but we only implement these
FANTRAX_SPORT_CODES = {
    Sport.FOOTBALL: "NFL",
    Sport.BASKETBALL: "NBA",
    Sport.BASEBALL: "MLB",
    Sport.HOCKEY: "NHL",
}

# CBS Sports API sport codes
CBS_SPORT_CODES = {
    Sport.FOOTBALL: "football",
    Sport.BASKETBALL: "basketball",
    Sport.BASEBALL: "baseball",
    Sport.HOCKEY: "hockey",
}


def get_current_season(sport: Sport) -> int:
    """
    Get the current season year for a given sport.

    Season logic varies by sport:
    - Basketball: Oct-Dec = next year (e.g., Oct 2025 = "2026 season")
    - Football: Sept-Dec = current year, Jan-Feb = previous year
    - Baseball: Same calendar year

    Args:
        sport: The sport to get the current season for

    Returns:
        The current season year
    """
    now = datetime.now()

    if sport == Sport.BASKETBALL:
        # NBA season spans two years, use the later year
        # Season starts in October, so Oct-Dec uses next year
        return now.year + 1 if now.month >= 10 else now.year

    elif sport == Sport.FOOTBALL:
        # NFL season: Sept-Dec = current year, Jan-Feb = previous year
        if now.month >= 9:
            return now.year
        elif now.month <= 2:
            return now.year - 1
        return now.year

    elif sport == Sport.BASEBALL:
        # MLB season is within a single calendar year
        return now.year

    else:  # Hockey
        # NHL season spans two years, similar to NBA
        return now.year + 1 if now.month >= 10 else now.year
