# Trading Bot Platform

This repository has evolved from a single-market trading bot into a FastAPI-based trading platform foundation with authentication, portfolio features, risk controls, broker adapters, analytics, subscriptions, automation, and a lightweight dashboard.

## What was added and improved

### Backend platform foundation
- FastAPI application entrypoint in api/main.py
- SQLite-backed persistence and schema initialization in api/database.py
- Shared request/response models in api/schemas.py
- Authentication and user identity handling in api/core/auth.py

### Feature modules
- Auth and account flows in api/routers/auth.py
- Trading, orders, portfolio, and market endpoints in api/routers/
- Watchlist, alerts, journal, notifications, and webhooks
- Team/workspace, subscription, strategy, analytics, assistant, automation, and audit endpoints
- Billing, broker execution, risk-limit, and Alpaca adapter support

### Supporting services
- Email, notification, streaming, broker, billing, and Alpaca adapter services under api/services/
- A simple dashboard shell at api/dashboard.html
- Regression and feature tests under tests/

## Project layout

```text
api/
  core/
  routers/
  services/
  data/
  analysis/
  backtest/
  execution/
  risk/
  strategies/
  utils/
main1.py
requirements.txt
README.md
```

## Quick start

### 1. Install dependencies

```bash
cd /media/sf_Documents/trading_bot_complete/trading_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the backend

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The app will be available at:
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/dashboard

### 3. API examples

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/dashboard
```

## Authentication

The platform includes basic auth endpoints such as:
- POST /auth/signup
- POST /auth/login
- GET /auth/me

Protected routes use bearer-style authentication with token validation.

## Broker and execution support

The backend includes a broker abstraction layer and an initial Alpaca adapter for paper-trading readiness.

## Testing

Run the test suite with:

```bash
pytest -q
```

## Notes

- The current backend is intended as a production-ready foundation rather than a finished live-trading deployment.
- Real broker connectivity, live market data streaming, and advanced analytics can be layered on top of this foundation.
- Sensitive credentials should be stored in environment variables rather than committed to source control.

## License

MIT
