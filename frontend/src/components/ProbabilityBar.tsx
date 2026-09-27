interface ProbabilityBarProps {
  value: number;
  colorClass?: string;
  showLabel?: boolean;
}

export default function ProbabilityBar({
  value,
  colorClass = 'bg-primary-500',
  showLabel = true,
}: ProbabilityBarProps) {
  // Undecided odds never round to a flat 0% or 100%
  let displayValue = (Math.round(value * 1000) / 10).toFixed(1) + '%';
  if (value > 0 && value < 0.001) displayValue = '<0.1%';
  if (value < 1 && value > 0.999) displayValue = '>99.9%';

  // Determine color based on value
  let barColor = colorClass;
  if (colorClass === 'auto') {
    if (value >= 0.9) barColor = 'bg-green-500';
    else if (value >= 0.5) barColor = 'bg-blue-500';
    else if (value >= 0.1) barColor = 'bg-yellow-500';
    else barColor = 'bg-red-500';
  }

  // Special styling for 100% and 0%
  if (value >= 0.9999) barColor = 'bg-green-600';
  if (value <= 0.0001) barColor = 'bg-gray-300';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-4 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} transition-all duration-500`}
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-sm font-medium text-gray-700 w-14 text-right">
          {displayValue}
        </span>
      )}
    </div>
  );
}
