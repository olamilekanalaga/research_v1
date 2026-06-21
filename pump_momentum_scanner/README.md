# Pump Momentum Scanner

Paper-trade scanner for fresh Pump.fun-style tokens using SolanaTracker REST data, Helius verification hooks, SQLite, and Telegram alerts.

This is paper trading only. It does not use a wallet key and cannot buy or sell real tokens.

## Setup

Create `C:\Users\alaga\OneDrive\Documents\Migration Specialist\.env` from `.env.example`.

Required values:

```env
SOLANA_TRACKER_API_KEY=...
HELIUS_API_KEY=...
HELIUS_WS_URL=...
HELIUS_RPC_URL=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Run

Check SolanaTracker subscription:

```powershell
python -m pump_momentum_scanner.scanner --subscription
```

Run one scan cycle:

```powershell
python -m pump_momentum_scanner.scanner --once
```

Run continuously:

```powershell
python -m pump_momentum_scanner.scanner
```

Summarize paper trades:

```powershell
python -m pump_momentum_scanner.analyze
```

## Current V1 Rules

- SolanaTracker is used for launches, market cap, price, trades, holders, and risk fields.
- Helius URLs are stored for verification hooks, but constant snapshots use SolanaTracker REST to protect Helius usage.
- Snapshot interval defaults to 10 seconds for Pro-plan request control.
- One paper entry per token per rule version.
- Entry requires 2 consecutive passing snapshots.
- Target: +20%.
- Stop: -20%.
- Max hold: 10 minutes.

## Database Tables

- `tokens`
- `snapshots`
- `trades`
- `paper_trades`
- `outcomes`
- `scanner_decisions`
- `api_logs`
- `missed_winners`
- `rule_versions`
