# Stock Screener — CLAUDE.md

## Project Overview
A Python-based stock screener with a real-time web UI that filters NSE Nifty 500 (India) or NYSE (US) listed stocks by fundamental and technical criteria.

## Tech Stack
- **Backend**: Python 3, Flask (REST API + SSE), yfinance
- **Frontend**: Plain HTML/CSS/JS (no framework), Server-Sent Events for live updates
- **Data**: yfinance (Yahoo Finance API)

## Architecture
```
stock-screener/
├── CLAUDE.md           ← this file
├── requirements.txt    ← Python dependencies
├── app.py              ← Flask backend (API + SSE stream)
├── screener.py         ← Core screening logic (fetch, filter, rank)
├── tickers.py          ← Static ticker lists for Nifty 500 & NYSE sample
├── templates/
│   └── index.html      ← Single-page UI
└── static/
    ├── css/style.css
    └── js/app.js
```

## Screening Criteria
| Filter      | Condition                        |
|-------------|----------------------------------|
| P/E Ratio   | < 20                             |
| Volume Spike| Current volume > 2× 20-day avg   |
| RSI (14)    | > 50                             |

## Ranking Logic
Stocks passing all three filters are ranked by a composite score:
  `score = (1/PE) * 0.4 + volume_ratio * 0.3 + (RSI - 50) * 0.3`
Higher score = better rank.

## API Endpoints
| Endpoint              | Method | Description                          |
|-----------------------|--------|--------------------------------------|
| `/`                   | GET    | Serves the UI                        |
| `/api/scan`           | POST   | Starts a scan; returns job_id        |
| `/api/stream/<job_id>`| GET    | SSE stream — ticker results as found |
| `/api/tickers/<mkt>`  | GET    | Returns ticker list for market       |

## Rate Limiting Strategy
- yfinance uses Yahoo Finance's unofficial API (no hard rate limit, but throttled)
- Batching: fetch up to 10 tickers at once using `yf.download()` with `group_by='ticker'`
- Delay: 1-second pause between batches to avoid 429s
- Nifty 500: ~50 batches of 10  |  NYSE sample: ~50 batches of 10
- Per-stock history: 25 days of daily OHLCV (for 20-day vol avg + RSI 14)

## Running the App
```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5050
```

## Port
**5050** — chosen to avoid conflicts with common dev servers (3000, 5000, 8000, 8080).

## Environment Notes
- No API keys required (yfinance is free / unofficial)
- Internet access required at runtime
- Python 3.8+ recommended
- Works on Linux / macOS / Windows

## Design Decisions
- Manual refresh only (user-controlled scans, no auto-polling)
- All passing stocks shown (no artificial top-N cap)
- SSE streaming so results appear as each batch completes — no waiting for full scan
- NSE tickers use `.NS` suffix (Yahoo Finance convention)
- NYSE list is a curated 500-stock sample of large/mid caps
