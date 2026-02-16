import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { simulationsApi, leaguesApi, SimulationResults, User } from '../api/client';
import StandingsTable from '../components/StandingsTable';
import ScenarioCard from '../components/ScenarioCard';
import ProgressIndicator from '../components/ProgressIndicator';

interface ResultsProps {
  user: User | null;
}

export default function Results({ user }: ResultsProps) {
  const { taskId } = useParams<{ taskId: string }>();
  const [results, setResults] = useState<SimulationResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('pending');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (!taskId) return;

    const fetchResults = async () => {
      try {
        // First check status
        const taskStatus = await simulationsApi.getStatus(taskId);
        setProgress(taskStatus.progress);
        setStatus(taskStatus.status);

        if (taskStatus.status === 'completed') {
          const data = await simulationsApi.getResults(taskId);
          setResults(data);
          setLoading(false);
        } else if (taskStatus.status === 'failed') {
          setError(taskStatus.error || 'Simulation failed');
          setLoading(false);
        } else {
          // Still running, poll for updates
          const interval = setInterval(async () => {
            const status = await simulationsApi.getStatus(taskId);
            setProgress(status.progress);
            setStatus(status.status);

            if (status.status === 'completed') {
              clearInterval(interval);
              const data = await simulationsApi.getResults(taskId);
              setResults(data);
              setLoading(false);
            } else if (status.status === 'failed') {
              clearInterval(interval);
              setError(status.error || 'Simulation failed');
              setLoading(false);
            }
          }, 1000);

          return () => clearInterval(interval);
        }
      } catch (err) {
        setError('Failed to fetch results');
        setLoading(false);
      }
    };

    fetchResults();
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
      interface ErrorResponse {
        response?: {
          data?: {
            detail?: string;
          };
        };
      }
      const errorResponse = err as ErrorResponse;
      const errorMessage = errorResponse.response?.data?.detail || 'Failed to save league';
      if (errorMessage.includes('already saved')) {
        setSaved(true);
      } else {
        setSaveError(errorMessage);
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <ProgressIndicator progress={progress} status={status} />;
  }

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
    return null;
  }

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              {results.league_name}
            </h1>
            <p className="text-gray-600">
              {results.sport.charAt(0).toUpperCase() + results.sport.slice(1)} | Week {results.current_week} of {results.total_weeks} | {results.sport === 'basketball' ? `${results.season - 1}-${results.season}` : results.season} Season
            </p>
            <p className="text-sm text-gray-500 mt-1">
              Based on {results.n_simulations.toLocaleString()} Monte Carlo simulations
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
      </div>

      {/* Standings Table */}
      <div className="card mb-8 overflow-hidden">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Playoff Probabilities</h2>
        <StandingsTable teams={results.teams} />
        <div className="mt-4 text-xs text-gray-500">
          <p><strong>M# Div</strong> = Wins needed to clinch division</p>
          <p><strong>M# Ply</strong> = Wins needed to clinch playoff spot</p>
          <p><strong>M# #1</strong> = Wins needed to clinch #1 seed</p>
          <p><strong>M# Last</strong> = Losses needed to secure last place</p>
        </div>
      </div>

      {/* Scenarios */}
      {(results.clinch_scenarios.length > 0 || results.elimination_scenarios.length > 0) && (
        <div className="grid md:grid-cols-2 gap-6 mb-8">
          <ScenarioCard
            title={`Paths to Clinch (Week ${results.current_week})`}
            scenarios={results.clinch_scenarios}
            type="clinch"
          />
          <ScenarioCard
            title={`Paths to Elimination (Week ${results.current_week})`}
            scenarios={results.elimination_scenarios}
            type="elimination"
          />
        </div>
      )}

      {/* No scenarios */}
      {results.clinch_scenarios.length === 0 && results.elimination_scenarios.length === 0 && (
        <div className="card bg-gray-50 text-center">
          <p className="text-gray-600">
            No clinch or elimination scenarios this week. Every team's playoff fate is still undetermined.
          </p>
        </div>
      )}
    </div>
  );
}
