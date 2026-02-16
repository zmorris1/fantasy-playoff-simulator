# Fantasy Basketball Playoff Simulator

A web application that uses Monte Carlo simulation to calculate playoff probabilities, clinch scenarios, and magic numbers for fantasy basketball leagues.

## Features

- **Playoff Odds**: See each team's probability of making the playoffs based on 10,000 simulations
- **Magic Numbers**: Know exactly how many wins needed to clinch a playoff spot or division title
- **Clinch/Elimination Scenarios**: See all the ways teams can clinch or be eliminated each week
- **User Accounts**: Save leagues to quickly run simulations throughout the season
- **ESPN Integration**: Works with public ESPN Fantasy Basketball leagues

## Tech Stack

### Backend
- **FastAPI** (Python) - REST API
- **SQLAlchemy** - Database ORM (SQLite dev / PostgreSQL prod)
- **JWT Authentication** - Secure user accounts
- **httpx** - Async HTTP client for ESPN API

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

## Deployment

### Railway (Backend)

1. Connect your GitHub repo to Railway
2. Set environment variables:
   - `DATABASE_URL` (PostgreSQL connection string)
   - `JWT_SECRET_KEY` (generate a secure random string)
   - `CORS_ORIGINS` (your frontend URL)

### Vercel (Frontend)

1. Connect your GitHub repo to Vercel
2. Set the root directory to `frontend`
3. Set environment variable:
   - `VITE_API_URL` (your Railway backend URL + `/api`)

## How It Works

1. **Fetch Data**: Get current standings and schedule from ESPN API
2. **Simulate**: Run 10,000 Monte Carlo simulations with 50/50 win probability
3. **Tiebreakers**: Apply ESPN tiebreaker rules (H2H, division record, coin flip)
4. **Magic Numbers**: Calculate wins needed to clinch various scenarios
5. **Scenarios**: Generate narrative clinch/elimination paths for current week

## License

MIT
