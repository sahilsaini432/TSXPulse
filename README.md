# Stock Predictor

Canadian TSX stock prediction routine. Generates buy signals using technical strategies, delivers to Discord, tracks performance in SQLite. Manual execution for now; designed to evolve into a full trading agent.

## Quick start

```powershell
# 1. Create venv and install
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[backtest,dev]"

# 2. Configure secrets
copy .env.example .env
# Edit .env, set DISCORD_WEBHOOK_URL

# 3. Init database
python scripts/migrate_db.py

# 4. Smoke test (pulls 15 TSX tickers, prints last close)
python scripts/smoke_test.py

# 5. Discord test message
python scripts/send_test_message.py

# 6. Force-signal dispatch test (paper mode, self-cleaning)
python scripts/force_signal_test.py

# 7. One orchestrator cycle (respects TSX calendar)
python scripts/run_cycle.py

# 8. EOD reconcile (close target/stop hits, write daily summary)
python scripts/reconcile_eod.py

# 9. Unit tests
python -m pytest tests/ -v
```

## Scheduling (Windows)

See `scripts/tasks/INSTALL.md` for `schtasks.exe` commands that register:
- `StockPredictor-PreOpen`     — 09:15 ET
- `StockPredictor-Midday`      — 12:00 ET
- `StockPredictor-PreClose`    — 15:45 ET
- `StockPredictor-EODReconcile` — 16:30 ET (after TSX close)

## Stats + Dashboard

```powershell
# CLI stats (good for cron/gate checks)
python scripts/stats.py
python scripts/stats.py --json
python scripts/stats.py --gate        # exit 1 if gate fails

# Streamlit dashboard
pip install -e ".[dashboard]"
streamlit run dashboard.py
```

## Paper → Live Gate

Before switching `broker.mode` from `paper` to `manual` (real capital):

| Criterion     | Threshold              |
| ------------- | ---------------------- |
| Closed trades | ≥ 10                   |
| Win rate      | ≥ 45%                  |
| Max drawdown  | > -10% (less negative) |
| Expectancy    | > 0% per trade         |

Check with `python scripts/stats.py --gate`. Run paper mode 2+ weeks minimum before gate eval.

## Go-Live Checklist

1. `.env` populated with `DISCORD_WEBHOOK_URL`
2. `config.yaml` → `broker.mode: paper`
3. `python scripts/migrate_db.py` (fresh DB)
4. `python scripts/send_test_message.py` — verify Discord
5. Install scheduler per `scripts/tasks/INSTALL.md`
6. Observe ≥ 10 trading days
7. `python scripts/stats.py --gate` → PASS
8. Flip `broker.mode: manual`
9. Execute Discord signals manually in Wealthsimple/Questrade

## Layout

See `C:\Users\saini\.claude\plans\you-are-an-excellent-zippy-meteor.md` for full plan.

- `src/TSXPulse/` — library code
- `scripts/` — CLI entrypoints (run_cycle, backtest, migrate, smoke, test-message)
- `config/config.yaml` — all tunables (watchlist, strategy params, risk, schedule)
- `data/TSXPulse.db` — SQLite: signals, fills, positions, performance
- `logs/runner.log` — rolling log

## Strategies (Phase 1)

- `mean_reversion` — RSI<30 buy / RSI>70 exit on blue-chip banks, energy, telecom
- `ma_crossover` — 50/200 SMA on ETFs (XIU, XIC, ZEB)

## Baseline backtest (2023-01-01 → 2025-12-31)

Run via `python scripts/backtest.py --strategy <name> --all-watchlist --from 2023-01-01 --to 2025-12-31`.

**mean_reversion** on full 15-ticker watchlist:
- Total trades: **94** | Weighted win rate: **47.9%** | Avg total return: **+7.71%**
- Strong: TD (+30.5%, 80% WR), CNQ (+26.9%, 67% WR), SU (+25.3%, 57% WR), XIU (+20.2%, 80% WR)
- Weak: CM (-10.5%), CNR (-7.0%), BCE (-5.6%)
- Win rate near 50% is expected and sanity-checks the engine (>55% would suggest lookahead bug).

**ma_crossover** on ETF subset (XIU, XIC, ZEB):
- Total trades: **4** | Weighted win rate: **100%** | Avg total return: **+13.6%**
- Low trade count; bull-market sample. Not statistically meaningful on its own. Re-test across 2020–2022 drawdown before drawing conclusions.

Raw trade logs in `data/backtest_results/`.

## Broker mode

`config.yaml` → `broker.mode`:
- `manual` (default) — records signals only; you execute in Wealthsimple/Questrade
- `paper` — simulates fills at next-open price with slippage
- `ibkr` — FUTURE, requires `ENABLE_LIVE_TRADING=1` env var + `ib_insync` installed

## Risk rules (hardcoded filters before Discord dispatch)

1. Max concurrent positions (default 3)
2. Max signals per day (default 3)
3. Position size = `floor(capital * 2% / (entry - stop))`, reject if < 1
4. Max daily implied loss 5% of capital
5. Dedup: no new signal if ticker already has open position

## Disclaimer

Not financial advice. Historical backtest performance does not predict future results. Losses are real. Use paper mode for at least two weeks before real capital.
