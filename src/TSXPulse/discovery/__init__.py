"""TSX Composite discovery pipeline.

Parallel signal path to the strategy-based orchestrator. Discovers candidates
across the full TSX Composite via screener + Tavily news + Claude ranking,
posts a top-N list to Discord, and persists ranked signals to discovery_signals.

Public entrypoint:
    from TSXPulse.discovery.pipeline import run_discovery
"""

from TSXPulse.discovery.pipeline import DiscoveryReport, run_discovery

__all__ = ["DiscoveryReport", "run_discovery"]
