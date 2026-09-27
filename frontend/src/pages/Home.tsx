import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import LeagueInput from '../components/LeagueInput';
import { simulationsApi, getErrorMessage, User } from '../api/client';

interface HomeProps {
  user: User | null;
}

export default function Home({ user }: HomeProps) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (platform: string, leagueId: string, season: number, sport: string) => {
    setLoading(true);
    setError('');

    try {
      // The results page shows progress while the simulation runs
      const task = await simulationsApi.run(platform, leagueId, season, sport);
      navigate(`/results/${task.task_id}`);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to start simulation'));
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          Fantasy League Playoff Simulator
        </h1>
        <p className="text-lg text-gray-600">
          Calculate playoff odds, clinch scenarios, and magic numbers for your fantasy league
        </p>
      </div>

      {error && (
        <div className="max-w-lg mx-auto mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
          {error}
        </div>
      )}

      <LeagueInput onSubmit={handleSubmit} loading={loading} isLoggedIn={!!user} />

      <div className="mt-12 grid md:grid-cols-3 gap-6">
        <div className="card text-center">
          <div className="text-4xl mb-4">&#127919;</div>
          <h3 className="font-semibold text-lg mb-2">Playoff Odds</h3>
          <p className="text-gray-600 text-sm">
            See each team's probability of making the playoffs based on 10,000 simulations
          </p>
        </div>

        <div className="card text-center">
          <div className="text-4xl mb-4">&#128290;</div>
          <h3 className="font-semibold text-lg mb-2">Magic Numbers</h3>
          <p className="text-gray-600 text-sm">
            Know exactly how many wins you need to clinch a playoff spot or division title
          </p>
        </div>

        <div className="card text-center">
          <div className="text-4xl mb-4">&#128161;</div>
          <h3 className="font-semibold text-lg mb-2">Clinch Scenarios</h3>
          <p className="text-gray-600 text-sm">
            See all the ways teams can clinch or be eliminated this week
          </p>
        </div>
      </div>
    </div>
  );
}
