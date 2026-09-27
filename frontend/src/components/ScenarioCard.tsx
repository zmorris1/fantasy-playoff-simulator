interface ScenarioCardProps {
  title: string;
  scenarios: string[];
  type: 'clinch' | 'elimination';
}

export default function ScenarioCard({ title, scenarios, type }: ScenarioCardProps) {
  if (scenarios.length === 0) {
    return null;
  }

  const borderColor = type === 'clinch' ? 'border-green-200' : 'border-red-200';
  const bgColor = type === 'clinch' ? 'bg-green-50' : 'bg-red-50';
  const iconColor = type === 'clinch' ? 'text-green-600' : 'text-red-600';
  const icon = type === 'clinch' ? '✓' : '✖';

  return (
    <div className={`card ${bgColor} border ${borderColor}`}>
      <h3 className="font-bold text-lg text-gray-900 mb-4 flex items-center gap-2">
        <span className={iconColor}>{icon}</span>
        {title}
      </h3>
      <ul className="space-y-2">
        {scenarios.map((scenario, idx) => (
          <li key={idx} className="text-gray-700 text-sm">
            <span className="font-medium">{formatScenario(scenario)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const HIGHLIGHTS: Record<string, string> = {
  WIN: 'text-green-600 font-bold',
  LOSS: 'text-red-600 font-bold',
  clinches: 'text-green-700 font-semibold',
  eliminated: 'text-red-700 font-semibold',
};

function formatScenario(scenario: string): React.ReactNode {
  // Highlight key words. Whole words and exact case only, so team names
  // like "Warriors" or "Win-Now Crew" are left alone.
  const parts = scenario.split(/\b(WIN|LOSS|clinches|eliminated)\b/);

  return parts.map((part, idx) =>
    // Odd indexes are the captured key words
    idx % 2 === 1 ? (
      <span key={idx} className={HIGHLIGHTS[part]}>{part}</span>
    ) : (
      part
    )
  );
}
