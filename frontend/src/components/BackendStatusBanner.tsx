import { useEffect, useState } from 'react';
import { healthApi } from '../api/client';

const RECHECK_INTERVAL_MS = 60000;

/**
 * Site-wide banner shown when the backend API is unreachable, so outages
 * read as outages instead of as bad credentials or missing leagues.
 */
export default function BackendStatusBanner() {
  // Assume up until a check says otherwise, so the banner never flashes
  const [backendUp, setBackendUp] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      const up = await healthApi.check();
      if (!cancelled) setBackendUp(up);
    };

    check();
    const interval = setInterval(check, RECHECK_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (backendUp) return null;

  return (
    <div className="bg-red-600 text-white text-sm text-center px-4 py-2">
      The server is currently unreachable. Logins and simulations won't work
      until it's back — this is a problem with the site, not with your account
      or credentials.
    </div>
  );
}
