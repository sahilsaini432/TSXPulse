from __future__ import annotations

from discord_webhook import DiscordEmbed

from TSXPulse.strategies.base import Signal
from TSXPulse.timeutil import utcnow


COLOR_BUY = "00C853"          # green
COLOR_TARGET = "2979FF"       # blue
COLOR_STOP = "D32F2F"         # red
COLOR_SUMMARY = "FFFFFF"      # white
COLOR_HEALTH = "FF9100"       # orange


def _now_utc() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M UTC")


def buy_embed(signal: Signal, qty: int, broker_mode: str) -> DiscordEmbed:
    target_pct = (signal.target_price / signal.entry_price - 1) * 100
    stop_pct = (signal.stop_loss / signal.entry_price - 1) * 100
    est_cost = signal.entry_price * qty
    embed = DiscordEmbed(
        title=f"BUY {signal.ticker}",
        description=signal.reasoning or "New buy signal.",
        color=COLOR_BUY,
    )
    embed.add_embed_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
    embed.add_embed_field(name="Target", value=f"${signal.target_price:,.2f} ({target_pct:+.1f}%)", inline=True)
    embed.add_embed_field(name="Stop", value=f"${signal.stop_loss:,.2f} ({stop_pct:+.1f}%)", inline=True)
    embed.add_embed_field(name="Qty", value=f"{qty}", inline=True)
    embed.add_embed_field(name="Est. Cost", value=f"${est_cost:,.0f}", inline=True)
    embed.add_embed_field(name="Strategy", value=signal.strategy_name, inline=True)
    embed.add_embed_field(name="Confidence", value=f"{signal.confidence:.0%}", inline=True)
    embed.add_embed_field(name="Session (UTC)", value=_now_utc(), inline=True)
    embed.add_embed_field(name="Mode", value=broker_mode, inline=True)
    footer = (
        "Execute manually in your broker."
        if broker_mode == "manual"
        else f"Simulated fill ({broker_mode})."
    )
    embed.set_footer(text=footer)
    return embed


def exit_target_embed(ticker: str, entry: float, exit_price: float, qty: int, pnl: float) -> DiscordEmbed:
    pct = (exit_price / entry - 1) * 100
    embed = DiscordEmbed(
        title=f"TARGET HIT — {ticker}",
        description=f"Take-profit filled.",
        color=COLOR_TARGET,
    )
    embed.add_embed_field(name="Entry", value=f"${entry:,.2f}", inline=True)
    embed.add_embed_field(name="Exit", value=f"${exit_price:,.2f} ({pct:+.1f}%)", inline=True)
    embed.add_embed_field(name="Qty", value=f"{qty}", inline=True)
    embed.add_embed_field(name="P&L", value=f"${pnl:+,.2f}", inline=True)
    embed.set_footer(text=_now_utc())
    return embed


def stop_loss_embed(ticker: str, entry: float, exit_price: float, qty: int, pnl: float) -> DiscordEmbed:
    pct = (exit_price / entry - 1) * 100
    embed = DiscordEmbed(
        title=f"STOP HIT — {ticker}",
        description="Stop-loss filled. Review strategy edge.",
        color=COLOR_STOP,
    )
    embed.add_embed_field(name="Entry", value=f"${entry:,.2f}", inline=True)
    embed.add_embed_field(name="Exit", value=f"${exit_price:,.2f} ({pct:+.1f}%)", inline=True)
    embed.add_embed_field(name="Qty", value=f"{qty}", inline=True)
    embed.add_embed_field(name="P&L", value=f"${pnl:+,.2f}", inline=True)
    embed.set_footer(text=_now_utc())
    return embed


def daily_summary_embed(
    realized_pnl: float,
    unrealized_pnl: float,
    open_positions: int,
    signals_generated: int,
    signals_filled: int,
    win_rate_30d: float | None,
) -> DiscordEmbed:
    embed = DiscordEmbed(
        title="Daily Summary",
        description=utcnow().strftime("%A, %Y-%m-%d"),
        color=COLOR_SUMMARY,
    )
    embed.add_embed_field(name="Realized P&L", value=f"${realized_pnl:+,.2f}", inline=True)
    embed.add_embed_field(name="Unrealized P&L", value=f"${unrealized_pnl:+,.2f}", inline=True)
    embed.add_embed_field(name="Open Positions", value=str(open_positions), inline=True)
    embed.add_embed_field(name="Signals Generated", value=str(signals_generated), inline=True)
    embed.add_embed_field(name="Signals Filled", value=str(signals_filled), inline=True)
    wr = f"{win_rate_30d:.0%}" if win_rate_30d is not None else "n/a"
    embed.add_embed_field(name="30d Win Rate", value=wr, inline=True)
    embed.set_footer(text=_now_utc())
    return embed


def health_alert_embed(component: str, status: str, message: str) -> DiscordEmbed:
    embed = DiscordEmbed(
        title=f"Health Alert — {status.upper()}",
        description=f"**{component}**: {message}",
        color=COLOR_HEALTH,
    )
    embed.set_footer(text=_now_utc())
    return embed
