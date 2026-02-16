import { TeamResult } from '../api/client';
import ProbabilityBar from './ProbabilityBar';

interface StandingsTableProps {
  teams: TeamResult[];
}

export default function StandingsTable({ teams }: StandingsTableProps) {
  // Sort by playoff probability
  const sortedTeams = [...teams].sort((a, b) => b.playoff_pct - a.playoff_pct);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-100 text-gray-700">
            <th className="px-4 py-3 text-left font-semibold">Team</th>
            <th className="px-4 py-3 text-center font-semibold">Record</th>
            <th className="px-4 py-3 text-left font-semibold min-w-[140px]">Division %</th>
            <th className="px-4 py-3 text-left font-semibold min-w-[140px]">Playoff %</th>
            <th className="px-4 py-3 text-left font-semibold min-w-[140px]">#1 Seed %</th>
            <th className="px-4 py-3 text-left font-semibold min-w-[140px]">Last Place %</th>
            <th className="px-4 py-3 text-center font-semibold" title="Wins needed to clinch division">
              M# Div
            </th>
            <th className="px-4 py-3 text-center font-semibold" title="Wins needed to clinch playoffs">
              M# Ply
            </th>
            <th className="px-4 py-3 text-center font-semibold" title="Wins needed to clinch #1 seed">
              M# #1
            </th>
            <th className="px-4 py-3 text-center font-semibold" title="Losses needed for last place">
              M# Last
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedTeams.map((team, idx) => (
            <tr
              key={team.id}
              className={`border-b border-gray-200 ${
                idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'
              } hover:bg-blue-50 transition-colors`}
            >
              <td className="px-4 py-3">
                <div>
                  <div className="font-medium text-gray-900">{team.name}</div>
                  <div className="text-xs text-gray-500">{team.division_name}</div>
                </div>
              </td>
              <td className="px-4 py-3 text-center">
                <div className="font-medium">{team.record}</div>
                <div className="text-xs text-gray-500">({team.division_record})</div>
              </td>
              <td className="px-4 py-3">
                <ProbabilityBar value={team.division_pct} colorClass="auto" />
              </td>
              <td className="px-4 py-3">
                <ProbabilityBar value={team.playoff_pct} colorClass="auto" />
              </td>
              <td className="px-4 py-3">
                <ProbabilityBar value={team.first_seed_pct} colorClass="auto" />
              </td>
              <td className="px-4 py-3">
                <ProbabilityBar
                  value={team.last_place_pct}
                  colorClass={team.last_place_pct > 0.5 ? 'bg-red-500' : team.last_place_pct > 0.1 ? 'bg-orange-500' : 'bg-gray-400'}
                />
              </td>
              <td className="px-4 py-3 text-center">
                <MagicNumberCell value={team.magic_division} type="clinch" />
              </td>
              <td className="px-4 py-3 text-center">
                <MagicNumberCell value={team.magic_playoffs} type="clinch" />
              </td>
              <td className="px-4 py-3 text-center">
                <MagicNumberCell value={team.magic_first_seed} type="clinch" />
              </td>
              <td className="px-4 py-3 text-center">
                <MagicNumberCell value={team.magic_last} type="avoid" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MagicNumberCell({ value, type }: { value: number | null; type: 'clinch' | 'avoid' }) {
  if (value === null) {
    return <span className="text-gray-400">-</span>;
  }

  const bgColor = type === 'clinch'
    ? value <= 2 ? 'bg-green-100 text-green-800' : value <= 5 ? 'bg-yellow-100 text-yellow-800' : 'bg-gray-100 text-gray-800'
    : value <= 2 ? 'bg-red-100 text-red-800' : value <= 5 ? 'bg-orange-100 text-orange-800' : 'bg-gray-100 text-gray-800';

  return (
    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold ${bgColor}`}>
      {value}
    </span>
  );
}
