# Fantasy League Playoff Simulator

A web application that uses Monte Carlo simulation to calculate playoff probabilities, clinch scenarios, and magic numbers for head-to-head fantasy leagues. Live at https://fantasy-playoff-sim.com.

## Features

- **Playoff Odds**: Each team's probability of winning its division, making the playoffs, earning the #1 seed, or finishing last, from 10,000 simulations
- **Magic Numbers**: Wins needed to clinch a playoff spot, division, or #1 seed regardless of other results (division-aware: division winners qualify regardless of record)
- **Clinch/Elimination Status**: Standings-style badges (z/y/x/e) and exact status once outcomes are mathematically decided
- **Clinch/Elimination Scenarios**: Which teams clinch with a win or are eliminated with a loss this week
- **Platforms**: ESPN (public leagues), Sleeper, Fantrax (public leagues), Yahoo (via OAuth)
- **Sports & formats**: Basketball, football, baseball, hockey; points, most-categories and each-category H2H leagues (roto isn't supported)
- **User Accounts**: Save leagues to quickly run simulations throughout the season

## Tech Stack

### Backend
- **FastAPI** (Python) - REST API
- **SQLAlchemy** - Database ORM (SQLite dev / PostgreSQL prod)
- **JWT Authentication** - Secure user accounts
- **httpx** - Async HTTP client for the platform APIs

### Frontend
- **React 18** with TypeScript
- **Vite** - Build tool
- **TailwindCSS** - Styling
- **React Router** - Navigation

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run development server
uvicorn app.main:app --reload
```

The API will be available at http://localhost:8000

Run the tests (the `integration` ones hit live platform APIs):

```bash
pytest -m "not integration"
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will be available at http://localhost:5173

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Create account |
| `/api/auth/login` | POST | Login, returns JWT |
| `/api/leagues/validate` | GET | Validate league exists |
| `/api/simulations/run` | POST | Start simulation |
| `/api/simulations/{id}/status` | GET | Poll for progress |
| `/api/simulations/{id}/results` | GET | Get results |
| `/api/leagues/me` | GET | List saved leagues |
| `/api/leagues/me` | POST | Save a league |
| `/api/oauth/yahoo/authorize` | GET | Start connecting a Yahoo account |
| `/api/oauth/yahoo/callback` | GET / POST | Finish connecting (browser redirect, or code + state from the frontend) |

`/api/simulations/run` reuses results from the last 15 minutes for the same league; pass `"refresh": true` to force a new run.

## Deployment

### Railway (Backend)

1. Connect your GitHub repo to Railway
2. Set environment variables:
   - `DATABASE_URL` (PostgreSQL connection string)
   - `JWT_SECRET_KEY` (generate a secure random string). If unset, a random key is used per process and everyone is logged out on each restart
   - `CORS_ORIGINS` (your frontend URL)
   - `FRONTEND_URL` (used when redirecting back after connecting Yahoo)
   - `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, `YAHOO_REDIRECT_URI` (optional). The redirect URI can be the frontend's `/dashboard` or the API's `/api/oauth/yahoo/callback`
   - `MAX_CONCURRENT_SIMULATIONS` (optional, default 2)

### Vercel (Frontend)

1. Connect your GitHub repo to Vercel
2. Set the root directory to `frontend`
3. Set environment variable:
   - `VITE_API_URL` (your Railway backend URL + `/api`)

## How It Works

1. **Fetch Data**: Get current standings, schedule and head-to-head results from the platform
2. **Simulate**: Run 10,000 Monte Carlo simulations; every matchup is a 50/50 coin flip (in each-category leagues, every category is)
3. **Tiebreakers**: Apply ESPN tiebreaker rules (H2H, division record, coin flip)
4. **Magic Numbers**: Calculate wins needed to clinch regardless of other results
5. **Scenarios**: With 10 or fewer games left, enumerate every possible outcome (and every coin-flip ordering) for exact clinch/elimination scenarios; otherwise use conservative analytical math that never claims a clinch or elimination that isn't certain

The simulation and scenario code lives in `backend/app/simulator/`; `backend/tests/test_simulator.py` checks the analytical math against exhaustive enumeration on random leagues.

## License

MIT
