import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { simulationsApi, leaguesApi, getErrorMessage, SimulationResults, User } from '../api/client';
import StandingsTable from '../components/StandingsTable';
import ScenarioCard from '../components/ScenarioCard';
import ProgressIndicator from '../components/ProgressIndicator';

interface ResultsProps {
  user: User | null;
}

const POLL_INTERVAL_MS = 1000;
// Consecutive failed status checks tolerated before giving up (network blips)
const MAX_POLL_ERRORS = 5;

function formatSeason(season: number, sport: string): string {
  return sport === 'basketball' || sport === 'hockey' ? `${season - 1}-${season}` : `${season}`;
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'just now';
  return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
}

function isNotFound(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 404;
}

export default function Results({ user }: ResultsProps) {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [results, setResults] = useState<SimulationResults | null>(null);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('pending');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [rerunning, setRerunning] = useState(false);

  useEffect(() => {
    if (!taskId) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let consecutiveErrors = 0;

    setResults(null);
    setError('');
    setProgress(0);
    setStatus('pending');

    const poll = async () => {
      try {
        const taskStatus = await simulationsApi.getStatus(taskId);
        if (cancelled) return;
        consecutiveErrors = 0;
        setProgress(taskStatus.progress);
        setStatus(taskStatus.status);

        if (taskStatus.status === 'completed') {
          const data = await simulationsApi.getResults(taskId);
          if (!cancelled) setResults(data);
        } else if (taskStatus.status === 'failed') {
          setError(taskStatus.error || 'Simulation failed');
        } else {
          timer = setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        consecutiveErrors += 1;
        if (isNotFound(err)) {
          setError('These results are no longer available. Simulations are kept for 24 hours — run it again for fresh odds.');
        } else if (consecutiveErrors < MAX_POLL_ERRORS) {
          timer = setTimeout(poll, POLL_INTERVAL_MS * 2);
        } else {
          setError(getErrorMessage(err, 'Failed to fetch results'));
        }
      }
    };

    poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);

  const handleSaveLeague = async () => {
    if (!results || !user) return;

    setSaving(true);
    setSaveError('');

    try {
      await leaguesApi.saveLeague(
        results.platform,
        results.league_id,
        results.season,
        results.sport,
        results.league_name
      );
      setSaved(true);
    } catch (err: unknown) {
      const errorMessage = getErrorMessage(err, 'Failed to save league');
      if (errorMessage.includes('already saved')) {
        setSaved(true);
      } else {
        setSaveError(errorMessage);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleRerun = async () => {
    if (!results) return;

    setRerunning(true);
    setSaveError('');

    try {
      const task = await simulationsApi.run(
        results.platform,
        results.league_id,
        results.season,
        results.sport,
        { refresh: true }
      );
      navigate(`/results/${task.task_id}`);
    } catch (err: unknown) {
      setSaveError(getErrorMessage(err, 'Failed to start simulation'));
    } finally {
      setRerunning(false);
    }
  };

  if (error) {
    return (
      <div className="max-w-lg mx-auto text-center">
        <div className="card bg-red-50 border border-red-200">
          <h2 className="text-xl font-bold text-red-700 mb-2">Error</h2>
          <p className="text-red-600 mb-4">{error}</p>
          <Link to="/" className="btn btn-primary">
            Try Again
          </Link>
        </div>
      </div>
    );
  }

  if (!results) {
    return <ProgressIndicator progress={progress} status={status} />;
  }

  const unit = results.categories_per_matchup > 1 ? 'category wins' : 'wins';
  const scenarioWeek = results.scenario_week ?? results.current_week;
  const allDecided = results.teams.every((t) => t.clinched_playoffs || t.eliminated_playoffs);

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:justify-between sm:items-start">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              {results.league_name}
            </h1>
            <p className="text-gray-600">
              {results.sport.charAt(0).toUpperCase() + results.sport.slice(1)} | Week {results.current_week} of {results.total_weeks} | {formatSeason(results.season, results.sport)} Season
            </p>
            <p className="text-sm text-gray-500 mt-1">
              Based on {results.n_simulations.toLocaleString()} Monte Carlo simulations
              {results.cached && results.cached_at && (
                <>
                  {' '}run {timeAgo(results.cached_at)}.{' '}
                  <button
                    onClick={handleRerun}
                    disabled={rerunning}
                    className="text-primary-600 hover:text-primary-700 underline"
                  >
                    {rerunning ? 'Starting...' : 'Re-run now'}
                  </button>
                </>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            {user && (
              <button
                onClick={handleSaveLeague}
                disabled={saving || saved}
                className={`btn ${saved ? 'btn-secondary bg-green-100 text-green-700' : 'btn-primary'}`}
              >
                {saving ? (
                  <span className="flex items-center gap-2">
                    <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
                    Saving...
                  </span>
                ) : saved ? (
                  'Saved to My Leagues'
                ) : (
                  'Save to My Leagues'
                )}
              </button>
            )}
            <Link to="/" className="btn btn-secondary">
              New Simulation
            </Link>
          </div>
        </div>
        {saveError && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {saveError}
          </div>
        )}
        {results.notes.length > 0 && (
          <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-800 text-sm space-y-1">
            {results.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </div>
        )}
      </div>

      {/* Standings Table */}
      <div className="card mb-8 overflow-hidden">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Playoff Probabilities</h2>
        <StandingsTable teams={results.teams} />
        <div className="mt-4 text-xs text-gray-500 space-y-1">
          <p>
            <strong>M#</strong> = magic number: {unit} that guarantee the goal no matter what else happens
            (<strong>Div</strong> division, <strong>Ply</strong> playoff spot, <strong>#1</strong> top seed).
            <strong> M# Last</strong> = losses that guarantee last place.
          </p>
          <p>
            <span className="text-green-700 font-semibold">&#10003;</span> clinched,{' '}
            <span className="text-red-600 font-semibold">&#10007;</span> eliminated,{' '}
            &ndash; can&apos;t be guaranteed without help from other results.
            {' '}Badges: <strong>z</strong> #1 seed, <strong>y</strong> division, <strong>x</strong> playoff spot, <strong>e</strong> eliminated.
          </p>
        </div>
      </div>

      {/* Scenarios */}
      {(results.clinch_scenarios.length > 0 || results.elimination_scenarios.length > 0) && (
        <div className="grid md:grid-cols-2 gap-6 mb-8">
          <ScenarioCard
            title={`Paths to Clinch (Week ${scenarioWeek})`}
            scenarios={results.clinch_scenarios}
            type="clinch"
          />
          <ScenarioCard
            title={`Paths to Elimination (Week ${scenarioWeek})`}
            scenarios={results.elimination_scenarios}
            type="elimination"
          />
        </div>
      )}

      {/* No scenarios */}
      {results.clinch_scenarios.length === 0 && results.elimination_scenarios.length === 0 && (
        <div className="card bg-gray-50 text-center">
          <p className="text-gray-600">
            {allDecided
              ? 'Every playoff spot has been decided.'
              : 'No team can clinch or be eliminated by its own result this week.'}
          </p>
        </div>
      )}
    </div>
  );
}
