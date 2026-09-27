import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  leaguesApi,
  SavedLeague,
  User,
  simulationsApi,
  getErrorMessage,
  completeOAuthConnection,
  oauthProviderFromState,
} from '../api/client';
import YahooConnect from '../components/YahooConnect';

const PROVIDER_NAMES: Record<string, string> = { yahoo: 'Yahoo', cbs: 'CBS Sports' };

function formatSeason(season: number, sport: string): string {
  return sport === 'basketball' || sport === 'hockey' ? `${season - 1}-${season}` : `${season}`;
}

interface DashboardProps {
  user: User | null;
}

export default function Dashboard({ user }: DashboardProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [leagues, setLeagues] = useState<SavedLeague[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [runningSimulation, setRunningSimulation] = useState<string | null>(null);
  // Bumped after connecting an account so the connection card re-checks
  const [connectionVersion, setConnectionVersion] = useState(0);
  // An authorization code can only be exchanged once (StrictMode runs effects twice)
  const handledCode = useRef<string | null>(null);

  // Handle the OAuth redirect back from Yahoo
  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const providerError = searchParams.get('error_description') || searchParams.get('error');

    // Redirected straight here by the provider: forward code + state to the API
    if (state && (code || providerError)) {
      const provider = oauthProviderFromState(state);
      const name = provider ? PROVIDER_NAMES[provider] : 'Account';
      setSearchParams({}, { replace: true });

      if (providerError || !provider || !code) {
        setError(`${name} connection error: ${providerError || 'unrecognized response. Please try again.'}`);
        return;
      }
      if (handledCode.current === code) return;
      handledCode.current = code;

      completeOAuthConnection(provider, code, state)
        .then(() => {
          setSuccess(`${name} account connected successfully!`);
          setConnectionVersion((v) => v + 1);
        })
        .catch((err: unknown) => setError(getErrorMessage(err, `Failed to connect your ${name} account`)));
      return;
    }

    // Redirected here by the API's own callback
    for (const [provider, name] of Object.entries(PROVIDER_NAMES)) {
      const connected = searchParams.get(`${provider}_connected`);
      const failure = searchParams.get(`${provider}_error`);
      if (connected === 'true') {
        setSuccess(`${name} account connected successfully!`);
        setSearchParams({}, { replace: true });
      } else if (failure) {
        setError(`${name} connection error: ${failure}`);
        setSearchParams({}, { replace: true });
      }
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    leaguesApi.getMyLeagues()
      .then(setLeagues)
      .catch((err: unknown) => setError(getErrorMessage(err, 'Failed to load saved leagues')))
      .finally(() => setLoading(false));
  }, [user, navigate]);

  const handleDelete = async (id: number) => {
    if (!confirm('Are you sure you want to remove this league?')) return;

    try {
      await leaguesApi.deleteLeague(id);
      setLeagues(leagues.filter((l) => l.id !== id));
    } catch {
      setError('Failed to delete league');
    }
  };

  const handleSimulate = async (league: SavedLeague) => {
    setRunningSimulation(league.league_id);
    setError('');

    try {
      const task = await simulationsApi.run(league.platform, league.league_id, league.season, league.sport);
      navigate(`/results/${task.task_id}`);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to start simulation'));
      setRunningSimulation(null);
    }
  };

  if (!user) {
    return null;
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">My Leagues</h1>
          <p className="text-gray-600">Manage your saved fantasy leagues</p>
        </div>
        <Link to="/" className="btn btn-primary">
          Add League
        </Link>
      </div>

      {/* Yahoo Connect Section */}
      <div className="mb-8">
        <YahooConnect key={connectionVersion} />
      </div>

      {success && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg text-green-700 flex justify-between items-center">
          <span>{success}</span>
          <button
            onClick={() => setSuccess('')}
            className="text-green-700 hover:text-green-900"
          >
            &times;
          </button>
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 flex justify-between items-center">
          <span>{error}</span>
          <button
            onClick={() => setError('')}
            className="text-red-700 hover:text-red-900"
          >
            &times;
          </button>
        </div>
      )}

      {loading ? (
        <div className="card text-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading your leagues...</p>
        </div>
      ) : leagues.length === 0 ? (
        <div className="card text-center py-12">
          <div className="text-6xl mb-4">&#127936;</div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">No saved leagues yet</h2>
          <p className="text-gray-600 mb-4">
            Run a simulation and save it to your account to quickly access it later.
          </p>
          <Link to="/" className="btn btn-primary">
            Add Your First League
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {leagues.map((league) => (
            <div key={league.id} className="card flex justify-between items-center">
              <div>
                <h3 className="font-semibold text-lg text-gray-900">
                  {league.nickname || `League ${league.league_id}`}
                </h3>
                <p className="text-sm text-gray-600">
                  {league.platform.toUpperCase()} {league.sport.charAt(0).toUpperCase() + league.sport.slice(1)} | {formatSeason(league.season, league.sport)} Season
                </p>
                <p className="text-xs text-gray-500">
                  League ID: {league.league_id}
                </p>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => handleSimulate(league)}
                  disabled={runningSimulation === league.league_id}
                  className="btn btn-primary"
                >
                  {runningSimulation === league.league_id ? (
                    <span className="flex items-center gap-2">
                      <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
                      Running...
                    </span>
                  ) : (
                    'Simulate'
                  )}
                </button>
                <button
                  onClick={() => handleDelete(league.id)}
                  className="btn btn-secondary text-red-600 hover:bg-red-100"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
