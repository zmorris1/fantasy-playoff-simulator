interface ProgressIndicatorProps {
  progress: number;
  status: string;
}

export default function ProgressIndicator({ progress, status }: ProgressIndicatorProps) {
  const statusMessages: Record<string, string> = {
    pending: 'Starting simulation...',
    running: 'Running Monte Carlo simulations...',
    completed: 'Complete!',
    failed: 'Simulation failed',
  };

  return (
    <div className="card max-w-lg mx-auto text-center">
      <div className="mb-4">
        <div className="animate-spin rounded-full h-16 w-16 border-4 border-primary-200 border-t-primary-600 mx-auto"></div>
      </div>

      <h3 className="text-lg font-semibold text-gray-900 mb-2">
        {statusMessages[status] || 'Processing...'}
      </h3>

      <div className="mb-4">
        <div className="h-4 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-primary-600 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-sm text-gray-600 mt-2">{progress}% complete</p>
      </div>

      <p className="text-sm text-gray-500">
        {progress < 40 && 'Fetching league data from ESPN...'}
        {progress >= 40 && progress < 50 && 'Calculating magic numbers...'}
        {progress >= 50 && progress < 95 && 'Running simulations (10,000 scenarios)...'}
        {progress >= 95 && progress < 100 && 'Finalizing results...'}
      </p>
    </div>
  );
}
