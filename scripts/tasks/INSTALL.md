# Windows Task Scheduler Installation

Four scheduled tasks drive the routine, all weekdays (Mon-Fri). Times are **local system time** — set your Windows time zone to America/Toronto (ET) first, or adjust the `/ST` values to your local equivalent of ET times.

## Run these commands in an Administrator PowerShell / cmd

```cmd
REM 1. Pre-open cycle (09:15 ET)
schtasks /create /tn "StockPredictor-PreOpen" /tr "E:\Projects\TSXPulse\scripts\tasks\run_cycle.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:15 /rl HIGHEST /f

REM 2. Midday cycle (12:00 ET)
schtasks /create /tn "StockPredictor-Midday" /tr "E:\Projects\TSXPulse\scripts\tasks\run_cycle.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 12:00 /rl HIGHEST /f

REM 3. Pre-close cycle (15:45 ET)
schtasks /create /tn "StockPredictor-PreClose" /tr "E:\Projects\TSXPulse\scripts\tasks\run_cycle.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 15:45 /rl HIGHEST /f

REM 4. EOD reconcile (16:30 ET, after TSX close)
schtasks /create /tn "StockPredictor-EODReconcile" /tr "E:\Projects\TSXPulse\scripts\tasks\reconcile_eod.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:30 /rl HIGHEST /f
```

## Post-install hardening (one-time, per task)

Open Task Scheduler GUI → each `StockPredictor-*` task → right-click → Properties:

- **General** tab: check "Run whether user is logged on or not"
- **Conditions** tab:
  - Check "Wake the computer to run this task"
  - Uncheck "Start the task only if the computer is on AC power" (if you're on a laptop)
- **Settings** tab:
  - Check "If the task is missed, run it as soon as possible"
  - "Stop the task if it runs longer than" → 30 minutes
- **Triggers** tab → edit weekly trigger → check "Synchronize across time zones" if your system TZ is not America/Toronto

## Power plan

Open "Edit power plan" for the active Windows plan. Set:
- **Put the computer to sleep** → Never, between 09:00 and 17:00 local time
  (Windows doesn't support time-ranged sleep natively — set to "Never" during ET market hours, or use a power-toggle script at 09:00/17:00.)

## Verify

After install, run manually first:

```cmd
schtasks /run /tn "StockPredictor-PreOpen"
```

Then check `E:\Projects\TSXPulse\logs\runner.log` — you should see the cycle log entries.

## Uninstall

```cmd
schtasks /delete /tn "StockPredictor-PreOpen" /f
schtasks /delete /tn "StockPredictor-Midday" /f
schtasks /delete /tn "StockPredictor-PreClose" /f
schtasks /delete /tn "StockPredictor-EODReconcile" /f
```

## Known quirks

- **DST transition days** (March, November): Windows Task Scheduler adjusts local times automatically if system TZ is set correctly. Script also calls `is_trading_day()` which relies on `pandas_market_calendars` (TSX timezone-aware) — so even if triggers fire at a slightly off ET time during DST, the cycle still executes. Just expect one log line off by an hour on transition day.
- **Laptop in sleep**: if your machine was asleep at trigger time and "Wake the computer" was not checked, the task is missed. Script will fire late (up to 30 min) with the missed-run setting.
- **VPN / no network**: data provider call will fail, script sends a Discord health alert. Survives cleanly, does not crash the schedule.
