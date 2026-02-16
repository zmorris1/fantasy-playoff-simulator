import { useState, useMemo, useEffect } from 'react';
import { leaguesApi, yahooApi, cbsApi, LeagueValidation } from '../api/client';
import YahooConnect from './YahooConnect';
import CBSConnect from './CBSConnect';

interface LeagueInputProps {
  onSubmit: (platform: string, leagueId: string, season: number, sport: string) => void;
  loading?: boolean;
  isLoggedIn?: boolean;
}

type Sport = 'basketball' | 'football' | 'baseball' | 'hockey';

// Calculate default season based on sport
function getDefaultSeason(sport: Sport): number {
  const currentYear = new Date().getFullYear();
  const currentMonth = new Date().getMonth(); // 0-indexed

  if (sport === 'basketball') {
    // NBA: Oct-Dec = next year (e.g., Oct 2025 = "2026 season")
    return currentMonth >= 9 ? currentYear + 1 : currentYear;
  } else if (sport === 'football') {
    // NFL: Sept-Dec = current year, Jan-Feb = previous year
    if (currentMonth >= 8) {
      return currentYear;
    } else if (currentMonth <= 1) {
      return currentYear - 1;
    }
    return currentYear;
  } else if (sport === 'hockey') {
    // NHL: Oct-Dec = next year (e.g., Oct 2025 = "2026 season"), similar to NBA
    return currentMonth >= 9 ? currentYear + 1 : currentYear;
  } else {
    // Baseball: Same calendar year
    return currentYear;
  }
}

// Get season options based on sport
function getSeasonOptions(sport: Sport): number[] {
  const currentYear = new Date().getFullYear();
  const defaultSeason = getDefaultSeason(sport);
  const options = [defaultSeason, defaultSeason - 1, defaultSeason - 2];
  // Always include current year if not already present (for pre-draft leagues)
  if (!options.includes(currentYear)) {
    options.unshift(currentYear);
  }
  return options;
}

// Format season display based on sport
function formatSeason(season: number, sport: Sport): string {
  if (sport === 'basketball' || sport === 'hockey') {
    return `${season - 1}-${season}`;
  }
  return `${season}`;
}

// Get URL hint based on sport and platform
function getUrlHint(sport: Sport, platform: string): string {
  if (platform === 'yahoo') {
    const sportPath = sport === 'basketball' ? 'nba' : sport === 'football' ? 'nfl' : sport === 'hockey' ? 'nhl' : 'mlb';
    return `baseball.fantasysports.yahoo.com/${sportPath}/`;
  }
  if (platform === 'sleeper') {
    return `sleeper.com/leagues/`;
  }
  if (platform === 'fantrax') {
    return `fantrax.com/fantasy/league/`;
  }
  if (platform === 'cbs') {
    return `cbssports.com/fantasy/league/`;
  }
  const sportPath = sport === 'basketball' ? 'basketball' : sport === 'football' ? 'football' : sport === 'hockey' ? 'hockey' : 'baseball';
  return `espn.com/fantasy/${sportPath}/league?leagueId=`;
}

export default function LeagueInput({ onSubmit, loading, isLoggedIn = false }: LeagueInputProps) {
  const [sport, setSport] = useState<Sport>('basketball');
  const [platform, setPlatform] = useState('espn');
  const [leagueId, setLeagueId] = useState('');
  const [season, setSeason] = useState(() => getDefaultSeason('basketball'));
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState<LeagueValidation | null>(null);
  const [error, setError] = useState('');
  const [yahooConnected, setYahooConnected] = useState(false);
  const [checkingYahoo, setCheckingYahoo] = useState(false);
  const [cbsConnected, setCbsConnected] = useState(false);
  const [checkingCbs, setCheckingCbs] = useState(false);

  // Check Yahoo connection status when user is logged in
  useEffect(() => {
    if (isLoggedIn) {
      setCheckingYahoo(true);
      yahooApi.getConnectionStatus()
        .then(status => setYahooConnected(status.connected))
        .catch(() => setYahooConnected(false))
        .finally(() => setCheckingYahoo(false));
    }
  }, [isLoggedIn]);

  // Check CBS connection status when user is logged in
  useEffect(() => {
    if (isLoggedIn) {
      setCheckingCbs(true);
      cbsApi.getConnectionStatus()
        .then(status => setCbsConnected(status.connected))
        .catch(() => setCbsConnected(false))
        .finally(() => setCheckingCbs(false));
    }
  }, [isLoggedIn]);

  const seasonOptions = useMemo(() => getSeasonOptions(sport), [sport]);

  const handleSportChange = (newSport: Sport) => {
    setSport(newSport);
    setSeason(getDefaultSeason(newSport));
    setValidation(null);
    setError('');
    // Reset platform to ESPN if switching to baseball while on Sleeper (not supported)
    if (newSport === 'baseball' && platform === 'sleeper') {
      setPlatform('espn');
    }
    // Reset platform to ESPN if switching to hockey while on unsupported platform
    if (newSport === 'hockey' && !['cbs', 'espn', 'yahoo', 'fantrax'].includes(platform)) {
      setPlatform('espn');
    }
  };

  const handleValidate = async () => {
    if (!leagueId.trim()) {
      setError('Please enter a league ID');
      return;
    }

    setValidating(true);
    setError('');
    setValidation(null);

    try {
      const result = await leaguesApi.validate(platform, leagueId.trim(), season, sport);
      setValidation(result);
      if (!result.valid) {
        setError(result.error || 'Invalid league');
      }
    } catch (err: any) {
      const message =
        err?.response?.data?.error ||
        err?.response?.data?.detail ||
        err?.message ||
        'Failed to validate league';
      setError(message);
    } finally {
      setValidating(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validation?.valid) {
      onSubmit(platform, leagueId.trim(), season, sport);
    } else {
      handleValidate();
    }
  };

  return (
    <form onSubmit={handleSubmit} className="card max-w-lg mx-auto">
      <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
        Enter Your League
      </h2>

      <div className="space-y-4">
        {/* Sport selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Sport
          </label>
          <select
            value={sport}
            onChange={(e) => handleSportChange(e.target.value as Sport)}
            className="input"
            disabled={loading}
          >
            <option value="basketball">Basketball</option>
            <option value="football">Football</option>
            <option value="baseball">Baseball</option>
            <option value="hockey" disabled={!['cbs', 'espn', 'yahoo', 'fantrax'].includes(platform)}>
              Hockey {!['cbs', 'espn', 'yahoo', 'fantrax'].includes(platform) ? '(Sleeper N/A)' : ''}
            </option>
          </select>
        </div>

        {/* Platform selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Platform
          </label>
          <select
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              setValidation(null);
              setError('');
            }}
            className="input"
            disabled={loading}
          >
            <option value="espn" disabled={false}>
              ESPN
            </option>
            <option value="yahoo" disabled={!isLoggedIn}>
              Yahoo {!isLoggedIn ? '(Login Required)' : ''}
            </option>
            <option value="sleeper" disabled={sport === 'baseball' || sport === 'hockey'}>
              Sleeper {sport === 'baseball' ? '(No Baseball)' : sport === 'hockey' ? '(No Hockey)' : ''}
            </option>
            <option value="fantrax" disabled={false}>
              Fantrax
            </option>
            <option value="cbs" disabled={!isLoggedIn}>
              CBS Sports {!isLoggedIn ? '(Login Required)' : ''}
            </option>
          </select>
        </div>

        {/* Yahoo connection prompt */}
        {platform === 'yahoo' && isLoggedIn && !yahooConnected && !checkingYahoo && (
          <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800 mb-3">
              Connect your Yahoo account to access your private leagues.
            </p>
            <YahooConnect
              compact
              onStatusChange={(connected) => setYahooConnected(connected)}
            />
          </div>
        )}

        {/* CBS connection prompt */}
        {platform === 'cbs' && isLoggedIn && !cbsConnected && !checkingCbs && (
          <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800 mb-3">
              Connect your CBS account to access your private leagues.
            </p>
            <CBSConnect
              compact
              onStatusChange={(connected) => setCbsConnected(connected)}
            />
          </div>
        )}

        {/* League ID input */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            League ID
          </label>
          <input
            type="text"
            value={leagueId}
            onChange={(e) => {
              setLeagueId(e.target.value);
              setValidation(null);
              setError('');
            }}
            placeholder=""
            className="input"
            disabled={loading}
          />
          <p className="text-xs text-gray-500 mt-1">
            {platform === 'yahoo' ? (
              <>Find this in your Yahoo league URL: {getUrlHint(sport, platform)}<strong>XXXXXX</strong></>
            ) : platform === 'sleeper' ? (
              <>Find this in your Sleeper league URL: {getUrlHint(sport, platform)}<strong>XXXXXXXXXXXXXXXXXX</strong></>
            ) : platform === 'fantrax' ? (
              <>Find this in your Fantrax league URL: {getUrlHint(sport, platform)}<strong>XXXXXXXXXXXX</strong></>
            ) : platform === 'cbs' ? (
              <>Find this in your CBS league URL: {getUrlHint(sport, platform)}<strong>XXXXXXXXX</strong></>
            ) : (
              <>Find this in your ESPN league URL: {getUrlHint(sport, platform)}<strong>XXXXXXXXX</strong></>
            )}
          </p>
        </div>

        {/* Season selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Season
          </label>
          <select
            value={season}
            onChange={(e) => {
              setSeason(Number(e.target.value));
              setValidation(null);
            }}
            className="input"
            disabled={loading}
          >
            {seasonOptions.map((yr) => (
              <option key={yr} value={yr}>
                {formatSeason(yr, sport)}
              </option>
            ))}
          </select>
        </div>

        {/* Error message */}
        {error && (
          <div className="p-3 bg-danger-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* Validation success */}
        {validation?.valid && (
          <div className="p-3 bg-success-50 border border-green-200 rounded-lg text-green-700">
            <p className="font-medium">{validation.league_name}</p>
            <p className="text-sm">
              {validation.num_divisions} divisions, {validation.playoff_spots} playoff spots
            </p>
          </div>
        )}

        {/* Submit buttons */}
        <div className="flex gap-3">
          {!validation?.valid && (
            <button
              type="button"
              onClick={handleValidate}
              disabled={validating || loading || (platform === 'yahoo' && !yahooConnected) || (platform === 'cbs' && !cbsConnected)}
              className="flex-1 btn btn-secondary"
            >
              {validating ? 'Validating...' : 'Validate League'}
            </button>
          )}

          <button
            type="submit"
            disabled={loading || validating || (!validation?.valid && !leagueId) || (platform === 'yahoo' && !yahooConnected) || (platform === 'cbs' && !cbsConnected)}
            className="flex-1 btn btn-primary"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
                Running...
              </span>
            ) : (
              'Run Simulation'
            )}
          </button>
        </div>
      </div>
    </form>
  );
}
