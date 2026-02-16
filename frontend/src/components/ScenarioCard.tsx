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
  const icon = type === 'clinch' ? '&#10003;' : '&#10006;';

  return (
    <div className={`card ${bgColor} border ${borderColor}`}>
      <h3 className="font-bold text-lg text-gray-900 mb-4 flex items-center gap-2">
        <span className={`${iconColor}`} dangerouslySetInnerHTML={{ __html: icon }} />
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

function formatScenario(scenario: string): React.ReactNode {
  // Bold team names and highlight key words
  const parts = scenario.split(/(WIN|LOSS|AND|OR|clinches|eliminated)/gi);

  return parts.map((part, idx) => {
    const upper = part.toUpperCase();
    if (upper === 'WIN') {
      return <span key={idx} className="text-green-600 font-bold">{part}</span>;
    }
    if (upper === 'LOSS') {
      return <span key={idx} className="text-red-600 font-bold">{part}</span>;
    }
    if (upper === 'AND' || upper === 'OR') {
      return <span key={idx} className="text-gray-500 font-medium"> {part} </span>;
    }
    if (upper === 'CLINCHES') {
      return <span key={idx} className="text-green-700 font-semibold">{part}</span>;
    }
    if (upper === 'ELIMINATED') {
      return <span key={idx} className="text-red-700 font-semibold">{part}</span>;
    }
    return part;
  });
}
