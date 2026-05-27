from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from discord_webhook import DiscordEmbed

from TSXPulse.strategies.base import Signal

if TYPE_CHECKING:
    from TSXPulse.discovery.news import TickerNews
from TSXPulse.timeutil import utcnow

COLOR_BUY = "00C853"  # green
COLOR_TARGET = "2979FF"  # blue
COLOR_STOP = "D32F2F"  # red
COLOR_SUMMARY = "FFFFFF"  # white
COLOR_HEALTH = "FF9100"  # orange
COLOR_DISCOVERY = "9C27B0"  # purple — visually distinct from strategy signals


def _now_utc() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _format_news_field(news: TickerNews, max_items: int = 3, max_snippet: int = 120) -> str:
    if news.error or not news.items:
        return ""
    lines = []
    for item in news.items[:max_items]:
        domain = urlparse(item.url).netloc.removeprefix("www.")
        snippet = (item.snippet or "").replace("\n", " ")[:max_snippet]
        lines.append(f"**[{item.title.strip()}]({item.url})**\n{snippet}… _{domain}_")
    return "\n\n".join(lines)


def buy_embed(signal: Signal, broker_mode: str, news: TickerNews | None = None) -> DiscordEmbed:
    target_pct = (signal.target_price / signal.entry_price - 1) * 100
    stop_pct = (signal.stop_loss / signal.entry_price - 1) * 100
    embed = DiscordEmbed(
        title=f"BUY {signal.ticker}",
        description=signal.reasoning or "New buy signal.",
        color=COLOR_BUY,
    )
    embed.add_embed_field(name="Entry", value=f"${signal.entry_price:,.2f}", inline=True)
    embed.add_embed_field(
        name="Target", value=f"${signal.target_price:,.2f} ({target_pct:+.1f}%)", inline=True
    )
    embed.add_embed_field(name="Stop", value=f"${signal.stop_loss:,.2f} ({stop_pct:+.1f}%)", inline=True)
    embed.add_embed_field(name="Strategy", value=signal.strategy_name, inline=True)
    embed.add_embed_field(name="Confidence", value=f"{signal.confidence:.0%}", inline=True)
    if news:
        news_text = _format_news_field(news)
        if news_text:
            embed.add_embed_field(name="Recent News", value=news_text[:1024], inline=False)
    footer = (
        f"Execute manually in your broker. [{broker_mode}] {_now_utc()}"
        if broker_mode == "manual"
        else f"Simulated fill. [{broker_mode}] {_now_utc()}"
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
    embed.add_embed_field(
        name="P&L",
        value=f"${realized_pnl:+,.2f} realized / ${unrealized_pnl:+,.2f} unrealized",
        inline=False,
    )
    embed.add_embed_field(name="Open Positions", value=str(open_positions), inline=True)
    embed.add_embed_field(
        name="Signals", value=f"{signals_filled}/{signals_generated} filled", inline=True
    )
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


def _format_sources_line(news: TickerNews, max_items: int = 3) -> str:
    if news.error or not news.items:
        return ""
    parts = [f"[{item.title.strip()}]({item.url})" for item in news.items[:max_items]]
    return "Sources: " + " · ".join(parts)


def discovery_summary_embed(
    signals: list,
    model: str,
    universe_size: int,
    screened: int,
    news_by_ticker: dict | None = None,
) -> DiscordEmbed:
    """One compact embed listing all ranked discovery signals.

    `signals` is a list[RankedSignal] but is typed as list to avoid a circular
    import (discovery -> notifications -> discovery).
    """
    embed = DiscordEmbed(
        title=f"TSX Discovery — Top {len(signals)} Setups",
        description=(
            f"Screened {screened} of {universe_size} TSX Composite names. "
            f"Ranked by {model}. **For manual review only — not trade instructions.**"
        ),
        color=COLOR_DISCOVERY,
    )

    for sig in signals:
        entry_range = f"${sig.entry_low:.2f} – ${sig.entry_high:.2f}"
        r_to_target = sig.target - ((sig.entry_low + sig.entry_high) / 2)
        r_to_stop = ((sig.entry_low + sig.entry_high) / 2) - sig.stop
        rr = r_to_target / r_to_stop if r_to_stop > 0 else 0.0
        catalyst = f" | Catalyst: {sig.catalyst_summary}" if sig.catalyst_summary else ""
        sources = ""
        if news_by_ticker:
            ticker_news = news_by_ticker.get(sig.ticker)
            if ticker_news:
                sources_line = _format_sources_line(ticker_news)
                if sources_line:
                    sources = f"\n{sources_line}"
        # Discord limits: each field value max 1024 chars; description 4096; embed total 6000
        value = (
            f"Entry **{entry_range}** | Stop **${sig.stop:.2f}** | "
            f"Target **${sig.target:.2f}** (R:R {rr:.1f})\n"
            f"Confidence **{sig.confidence:.0%}**{catalyst}\n"
            f"_{sig.rationale}_{sources}"
        )[:1024]
        embed.add_embed_field(name=f"#{sig.rank}  {sig.ticker}", value=value, inline=False)

    embed.set_footer(text=f"Discovery • {_now_utc()}")
    return embed
