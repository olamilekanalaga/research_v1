# Alert Feed Research Layer

This layer is for learning from Telegram group alerts like `BIG VOLUME ALERT`.
It is separate from the live SolanaTracker scanner.

Purpose:

```text
pasted/screenshot-transcribed alerts
-> structured features
-> transparent runner score
-> later x-outcomes matched back to the original alert
-> rule tuning before live execution
```

Current parser extracts:

```text
CA, token name, symbol, label
SOL burst and buy count
market cap, liquidity, volume, fees, age
holders, top 10 concentration
DEX paid, bundle, snipers, dev status
holder distribution
later x multiple messages
```

Run:

```powershell
python -m pump_momentum_scanner.alert_feed path\to\pasted_alerts.txt
python -m pump_momentum_scanner.alert_feed path\to\pasted_alerts.txt --jsonl
```

Important:

The score is V0 and intentionally transparent. It is not final trading logic.
Send more winners and non-winners, then tune thresholds from the data.
