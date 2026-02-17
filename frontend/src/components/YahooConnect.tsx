import { useState, useEffect } from 'react';
import { yahooApi } from '../api/client';

interface YahooConnectProps {
  onStatusChange?: (connected: boolean) => void;
  compact?: boolean;
}

export default function YahooConnect({ onStatusChange, compact = false }: YahooConnectProps) {
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    checkStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const checkStatus = async () => {
    try {
      const status = await yahooApi.getConnectionStatus();
      setConnected(status.connected);
      onStatusChange?.(status.connected);
    } catch {
      // User might not be logged in
      setConnected(false);
      onStatusChange?.(false);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async () => {
    setActionLoading(true);
    setError('');

    try {
      const { url } = await yahooApi.getAuthorizationUrl();
      // Redirect to Yahoo OAuth
      window.location.href = url;
    } catch (err: unknown) {
      interface ErrorResponse {
        response?: {
          data?: {
            detail?: string;
          };
        };
      }
      const errorResponse = err as ErrorResponse;
      setError(errorResponse.response?.data?.detail || 'Failed to start Yahoo connection');
      setActionLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm('Are you sure you want to disconnect your Yahoo account?')) {
      return;
    }

    setActionLoading(true);
    setError('');

    try {
      await yahooApi.disconnect();
      setConnected(false);
      onStatusChange?.(false);
    } catch (err: unknown) {
      interface ErrorResponse {
        response?: {
          data?: {
            detail?: string;
          };
        };
      }
      const errorResponse = err as ErrorResponse;
      setError(errorResponse.response?.data?.detail || 'Failed to disconnect Yahoo account');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className={compact ? 'text-sm text-gray-500' : 'card'}>
        <div className="flex items-center gap-2">
          <div className="animate-spin h-4 w-4 border-2 border-primary-600 border-t-transparent rounded-full"></div>
          <span>Checking Yahoo connection...</span>
        </div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="space-y-2">
        {error && (
          <div className="text-sm text-red-600">{error}</div>
        )}
        {connected ? (
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-sm text-green-600">
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              Yahoo Connected
            </span>
            <button
              onClick={handleDisconnect}
              disabled={actionLoading}
              className="text-sm text-red-600 hover:text-red-700 underline"
            >
              {actionLoading ? 'Disconnecting...' : 'Disconnect'}
            </button>
          </div>
        ) : (
          <button
            onClick={handleConnect}
            disabled={actionLoading}
            className="btn btn-secondary text-sm"
          >
            {actionLoading ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 border-gray-500 border-t-transparent rounded-full"></span>
                Connecting...
              </span>
            ) : (
              'Connect Yahoo Account'
            )}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">Yahoo Fantasy</h3>
          <p className="text-sm text-gray-600">
            {connected
              ? 'Your Yahoo account is connected. You can access your private Yahoo leagues.'
              : 'Connect your Yahoo account to access your private Yahoo Fantasy leagues.'}
          </p>
        </div>

        <div className="flex items-center gap-4">
          {connected ? (
            <>
              <span className="inline-flex items-center gap-1 px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm">
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                Connected
              </span>
              <button
                onClick={handleDisconnect}
                disabled={actionLoading}
                className="btn btn-secondary text-red-600 hover:bg-red-100"
              >
                {actionLoading ? 'Disconnecting...' : 'Disconnect'}
              </button>
            </>
          ) : (
            <button
              onClick={handleConnect}
              disabled={actionLoading}
              className="btn btn-primary"
            >
              {actionLoading ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full"></span>
                  Connecting...
                </span>
              ) : (
                'Connect Yahoo Account'
              )}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
