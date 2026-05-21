# Stock Predictor

Canadian TSX signal generator. Two parallel paths:

1. **Strategy-based signals** — RSI mean-reversion and MA crossover on a curated watchlist, deterministic, backtested, with a risk gate + paper broker simulation.
2. **LLM discovery signals** — full TSX Composite universe screened across RSI/MACD/ATR/volume/SMA, news context fetched per candidate via Tavily, ranked by Claude (Anthropic API) into a top-7 with entry/stop/target and rationale. Read-only signals for manual review — does NOT go through the risk gate or broker.

Both paths deliver to Discord. Manual execution for now; designed to evolve into a full trading agent.

## Environment setup

Copy `.env.example` to `.env` and fill in values:

```powershell
copy .env.example .env
```

| Variable              | Required for         | Description                                                                                                   |
| --------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------- |
| `DISCORD_WEBHOOK_URL` | All paths            | Webhook for signal delivery. Create at **Server Settings → Integrations → Webhooks → New Webhook**, copy URL. |
| `ANTHROPIC_API_KEY`   | Discovery            | Claude API key. Get at https://console.anthropic.com/                                                         |
| `TAVILY_API_KEY`      | Discovery (optional) | Tavily API key for news. 1000 free searches/month. Get at https://app.tavily.com/                             |
| `FMP_API_KEY`         | No (Phase 2)         | Financial Modeling Prep key. Leave blank.                                                                     |
| `EODHD_API_KEY`       | No (Phase 2)         | EODHD key. Leave blank.                                                                                       |
| `ENABLE_LIVE_TRADING` | Only for live IBKR   | Set `1` only when switching to IBKR live broker. Default `0`.                                                 |

Without `DISCORD_WEBHOOK_URL` the system runs but signals are logged only (no Discord messages sent).

## Quick start

```powershell
# 1. Create venv and install
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[backtest,dev]"

# 1b. (optional) install the discovery extras for LLM + news layer
pip install -e ".[discovery]"

# 2. Configure secrets (see Environment setup above)
copy .env.example .env
# Edit .env, set DISCORD_WEBHOOK_URL (and ANTHROPIC_API_KEY + TAVILY_API_KEY if using discovery)

# 3. Init database (creates strategy tables + discovery_signals table)
python scripts/migrate_db.py

# 4. Smoke test (pulls 15 TSX tickers, prints last close)
python scripts/smoke_test.py

# 5. Discord test message
python scripts/send_test_message.py

# 6. Force-signal dispatch test (paper mode, self-cleaning)
python scripts/force_signal_test.py

# 7. One strategy-orchestrator cycle (respects TSX calendar)
python scripts/run_cycle.py

# 8. EOD reconcile (close target/stop hits, write daily summary)
python scripts/reconcile_eod.py

# 9. Unit tests
python -m pytest tests/ -v

# 10. (optional) One discovery cycle — requires discovery extras + API keys
python scripts/run_discovery.py --dry-run            # safest first run: no DB write, no Discord post
python scripts/run_discovery.py --skip-news          # rank without Tavily news (saves credits)
python scripts/run_discovery.py                      # full cycle
```

## Discovery pipeline (LLM-driven)

The discovery pipeline is a separate, opt-in path that mirrors the original Claude routine but runs locally as Python you can read, version, and tinker with.

**Flow (`python scripts/run_discovery.py`):**

1. **Universe** — fetch TSX Composite constituents from the iShares XIC holdings CSV (daily-updated, cached 24h). Falls back to a hardcoded list of ~150 large/liquid TSX names if the fetch fails.
2. **Screener** — fetch OHLCV via yfinance, compute RSI(14), MACD, ATR(14), volume vs 20d avg, and SMA50/SMA200 distance. Score each candidate; take top 50 by score.
3. **News** — Tavily search per candidate, 3 results, 7-day lookback (configurable). Skipped if `TAVILY_API_KEY` is missing or `--skip-news` is set.
4. **Rank** — single Anthropic API call (default model: `claude-sonnet-4-6`) returns a JSON list of top 7 setups with entry zone, stop, target, rationale, and catalyst summary.
5. **Persist** — each ranked signal written to `discovery_signals` table with a shared `cycle_id`.
6. **Notify** — one summary embed to Discord listing all ranked signals.

**Configure in `config/config.yaml` under the `discovery:` block:**

```yaml
discovery:
  enabled: false              # flip to true after setting API keys
  model: claude-sonnet-4-6    # or claude-opus-4-7 for higher quality
  max_universe: 225           # how many tickers to fetch
  max_candidates: 50          # top-N forwarded to ranker
  top_n: 7                    # final ranked signals
  max_tokens: 4000
  news_per_ticker: 3
  news_days_back: 7
```

**Discovery signals are read-only.** They do NOT go through the risk gate, paper broker, or reconciler. They surface candidates with rationale for manual review — you decide if and how to act. This matches the semantics of the original Claude routine and is intentionally separate from the deterministic strategy path that supports paper-tracked evaluation.

**Cost (rough):** One discovery cycle with 50 candidates and Sonnet 4.6 is ~5-15K input tokens + ~2-4K output tokens. At Sonnet 4.6 pricing, well under $0.10 per run. Tavily adds 50 search credits per cycle (free tier covers ~20 cycles/month).

**Scheduling discovery:** Add a Windows Task Scheduler entry for `scripts/run_discovery.py` at ~08:30 ET on weekdays. See `scripts/tasks/INSTALL.md` for the schtasks pattern (clone the existing PreOpen entry, swap the script path).

## Scheduling (Windows)

See `scripts/tasks/INSTALL.md` for `schtasks.exe` commands that register:
- `StockPredictor-PreOpen`     — 09:15 ET
- `StockPredictor-Midday`      — 12:00 ET
- `StockPredictor-PreClose`    — 15:45 ET
- `StockPredictor-EODReconcile` — 16:30 ET (after TSX close)
- (optional) `StockPredictor-Discovery` — 08:30 ET, runs `scripts/run_discovery.py`

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

Discovery signals are NOT counted toward the gate — they're a separate evaluation track.

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

- `src/TSXPulse/` — library code
  - `discovery/` — LLM discovery path (universe, screener, news, ranker, pipeline)
  - `strategies/` — deterministic strategies (mean_reversion, ma_crossover)
  - `risk/` — pre-dispatch risk gate
  - `execution/` — broker abstractions (manual, paper, ibkr stub)
  - `storage/` — SQLAlchemy models & repo helpers
  - `notifications/` — Discord webhook + embed templates
- `scripts/` — CLI entrypoints (run_cycle, run_discovery, backtest, migrate, smoke, test-message)
- `config/config.yaml` — all tunables (watchlist, strategy params, risk, schedule, discovery)
- `data/TSXPulse.db` — SQLite: signals, fills, positions, performance, **discovery_signals**, health
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

Applied to STRATEGY signals only. Discovery signals bypass these (read-only by design).

1. Max concurrent positions (default 3)
2. Max signals per day (default 3)
3. Position size = `floor(capital * 2% / (entry - stop))`, reject if < 1
4. Max daily implied loss 5% of capital
5. Dedup: no new signal if ticker already has open position

## ⚠️ DISCLAIMER — READ BEFORE USE

> **This software is not financial advice. It is an experimental, algorithmic signal generator built for educational and research purposes only.**

- **No guarantee of profit.** All signals are based on technical indicators, news, and LLM synthesis of historical patterns. Past performance does not predict future results. Markets can and do move against any model.
- **You can lose money.** Trading stocks involves substantial risk of loss. You may lose part or all of your invested capital.
- **We are not responsible for your losses.** The authors and contributors of this project accept no liability whatsoever for any financial losses, damages, or other consequences arising from use of this software — direct, indirect, or incidental.
- **No licensed financial advice.** Nothing in this codebase, its output, or its documentation constitutes investment advice, a solicitation to buy or sell securities, or a recommendation of any kind.
- **You are solely responsible** for all trading decisions. Always do your own research. Consult a licensed financial advisor before putting real capital at risk.
- **Paper trade first.** Run in `paper` mode for a minimum of two weeks and pass the gate check (`python scripts/stats.py --gate`) before considering real money.

By using this software you acknowledge and accept all of the above.