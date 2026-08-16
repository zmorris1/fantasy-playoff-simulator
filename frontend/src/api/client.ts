import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

// Without a timeout, a hung backend leaves requests spinning forever.
const REQUEST_TIMEOUT_MS = 45000;

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Translate a request failure into a message that distinguishes
 * "the backend is unreachable/broken" from a real API error, so the UI
 * never blames the user's input for a server outage.
 */
export function getErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    if (err.code === 'ECONNABORTED') {
      return 'The server took too long to respond. It may be down or overloaded — please try again in a few minutes.';
    }
    if (!err.response) {
      return "Can't reach the server. The site's backend appears to be down — this is not a problem with what you entered.";
    }

    const { status, data } = err.response;

    // HTML instead of JSON means the request hit a web server, not the API
    // (e.g. a misconfigured VITE_API_URL serving index.html with a 200).
    if (typeof data === 'string' && /^\s*(<!doctype|<html)/i.test(data)) {
      return 'The server returned a web page instead of data — the backend API is misconfigured or down.';
    }

    if (status >= 500) {
      return `The server hit an internal error (HTTP ${status}). This is a problem on our end — please try again shortly.`;
    }

    const body = data as { detail?: unknown; error?: unknown } | undefined;
    if (typeof body?.detail === 'string') return body.detail;
    if (typeof body?.error === 'string') return body.error;
  }
  return fallback;
}

// Health API
export const healthApi = {
  /**
   * True only if /api/health returns the expected JSON shape. A bare 200
   * is not enough: a misconfigured API URL can return index.html with 200.
   */
  check: async (): Promise<boolean> => {
    try {
      const response = await api.get('/health', { timeout: 10000 });
      const data = response.data as { status?: string } | null;
      return typeof data === 'object' && data !== null && data.status === 'healthy';
    } catch {
      return false;
    }
  },
};

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle auth errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      // Optionally redirect to login
      // window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  register: async (email: string, password: string) => {
    const response = await api.post('/auth/register', { email, password });
    return response.data;
  },

  login: async (email: string, password: string) => {
    const response = await api.post('/auth/login', { email, password });
    return response.data;
  },

  getMe: async () => {
    const response = await api.get('/auth/me');
    return response.data;
  },

  logout: async () => {
    localStorage.removeItem('token');
  },
};

// Leagues API
export const leaguesApi = {
  validate: async (platform: string, leagueId: string, season?: number, sport: string = 'basketball') => {
    const params = new URLSearchParams({ platform, league_id: leagueId, sport });
    if (season) params.append('season', season.toString());
    const response = await api.get(`/leagues/validate?${params}`);
    return response.data;
  },

  getMyLeagues: async () => {
    const response = await api.get('/leagues/me');
    return response.data;
  },

  saveLeague: async (platform: string, leagueId: string, season: number, sport: string = 'basketball', nickname?: string) => {
    const response = await api.post('/leagues/me', {
      platform,
      league_id: leagueId,
      season,
      sport,
      nickname,
    });
    return response.data;
  },

  deleteLeague: async (id: number) => {
    await api.delete(`/leagues/me/${id}`);
  },
};

// Yahoo OAuth API
export const yahooApi = {
  getAuthorizationUrl: async () => {
    const response = await api.get('/oauth/yahoo/authorize');
    return response.data as { url: string; state: string };
  },

  getConnectionStatus: async () => {
    const response = await api.get('/oauth/yahoo/status');
    return response.data as { connected: boolean; yahoo_guid?: string };
  },

  disconnect: async () => {
    await api.delete('/oauth/yahoo/disconnect');
  },
};

// CBS OAuth API
export const cbsApi = {
  getAuthorizationUrl: async () => {
    const response = await api.get('/oauth/cbs/authorize');
    return response.data as { url: string; state: string };
  },

  getConnectionStatus: async () => {
    const response = await api.get('/oauth/cbs/status');
    return response.data as { connected: boolean; cbs_user_id?: string };
  },

  disconnect: async () => {
    await api.delete('/oauth/cbs/disconnect');
  },
};

// Simulations API
export const simulationsApi = {
  run: async (platform: string, leagueId: string, season?: number, sport: string = 'basketball', quickMode = false) => {
    const response = await api.post('/simulations/run', {
      platform,
      league_id: leagueId,
      season,
      sport,
      quick_mode: quickMode,
    });
    return response.data;
  },

  getStatus: async (taskId: string) => {
    const response = await api.get(`/simulations/${taskId}/status`);
    return response.data;
  },

  getResults: async (taskId: string) => {
    const response = await api.get(`/simulations/${taskId}/results`);
    return response.data;
  },

  streamProgress: (taskId: string, onProgress: (data: ProgressData) => void) => {
    const eventSource = new EventSource(`${API_BASE_URL}/simulations/${taskId}/stream`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      onProgress(data);

      if (data.status === 'completed' || data.status === 'failed') {
        eventSource.close();
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return eventSource;
  },
};

// Types
export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface SavedLeague {
  id: number;
  platform: string;
  league_id: string;
  season: number;
  sport: string;
  nickname?: string;
  created_at: string;
}

export interface LeagueValidation {
  valid: boolean;
  league_name?: string;
  playoff_spots?: number;
  num_divisions?: number;
  sport?: string;
  season?: number;
  error?: string;
}

export interface TeamResult {
  id: number;
  name: string;
  division_id: number;
  division_name: string;
  wins: number;
  losses: number;
  ties: number;
  record: string;
  division_record: string;
  win_pct: number;
  division_pct: number;
  playoff_pct: number;
  first_seed_pct: number;
  last_place_pct: number;
  magic_division: number | null;
  magic_playoffs: number | null;
  magic_first_seed: number | null;
  magic_last: number | null;
}

export interface SimulationResults {
  league_name: string;
  platform: string;
  league_id: string;
  season: number;
  sport: string;
  current_week: number;
  total_weeks: number;
  n_simulations: number;
  teams: TeamResult[];
  clinch_scenarios: string[];
  elimination_scenarios: string[];
  cached: boolean;
  cached_at?: string;
}

export interface ProgressData {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  error?: string;
}

export interface SimulationTask {
  task_id: string;
  status: string;
  progress: number;
  error?: string;
}
