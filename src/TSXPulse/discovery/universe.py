"""TSX Composite universe builder.

Primary path: scrape iShares XIC holdings CSV (the ETF tracks the TSX Composite).
Fallback: hardcoded ~150-ticker list embedded below.

Why XIC? BlackRock publishes daily-updated holdings at a stable URL. More reliable
than scraping Wikipedia, more accessible than TMX's JS-heavy screener.

CSV layout (skip 9 header rows of fund metadata):
    Ticker,Name,Sector,Asset Class,Market Value,Weight (%),...

The CSV uses bare TSX symbols (RY, TD, SHOP, BBD/B). We normalize to Yahoo Finance
format with .TO suffix and dot-for-slash class separators.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Direct iShares XIC holdings CSV. URL pattern is stable; the fund ID
# (239837 for Canadian iShares) and the .ajax?fileType=csv suffix have held
# for years across iShares funds. If iShares ever restructures the URL, the
# fallback list below keeps the pipeline running.
XIC_HOLDINGS_URL = (
    "https://www.blackrock.com/ca/investors/en/products/239837/"
    "ishares-sptsx-capped-composite-index-etf/"
    "1464253357814.ajax?fileType=csv&fileName=XIC_holdings&dataType=fund"
)

# Cache lives next to the data dir; refreshes once per CACHE_TTL_HOURS.
CACHE_TTL_HOURS = 24


# Hardcoded fallback. ~150 of the largest/most-liquid TSX Composite names.
# Used when the XIC CSV fetch fails. Curated for liquidity, not weighting fidelity.
FALLBACK_UNIVERSE: list[str] = [
    # Big banks
    "RY.TO",
    "TD.TO",
    "BNS.TO",
    "BMO.TO",
    "CM.TO",
    "NA.TO",
    # Energy
    "ENB.TO",
    "TRP.TO",
    "CNQ.TO",
    "SU.TO",
    "CVE.TO",
    "IMO.TO",
    "TOU.TO",
    "ARX.TO",
    "MEG.TO",
    "OVV.TO",
    "PXT.TO",
    "VET.TO",
    "WCP.TO",
    "ERF.TO",
    "BTE.TO",
    "CPG.TO",
    "PSK.TO",
    "FRU.TO",
    "KEL.TO",
    "PEY.TO",
    # Mining / materials
    "AEM.TO",
    "ABX.TO",
    "FNV.TO",
    "WPM.TO",
    "K.TO",
    "AGI.TO",
    "ELD.TO",
    "FM.TO",
    "TECK-B.TO",
    "LUN.TO",
    "HBM.TO",
    "IVN.TO",
    "NTR.TO",
    "MX.TO",
    "CCO.TO",
    "LIF.TO",
    "FR.TO",
    "PAAS.TO",
    "OR.TO",
    "SSL.TO",
    "MAG.TO",
    "GIB-A.TO",
    "NXE.TO",
    # Utilities & telecom
    "BCE.TO",
    "T.TO",
    "RCI-B.TO",
    "QBR-B.TO",
    "FTS.TO",
    "EMA.TO",
    "CU.TO",
    "AQN.TO",
    "BEP-UN.TO",
    "BIP-UN.TO",
    "BLX.TO",
    "CPX.TO",
    "INE.TO",
    "NPI.TO",
    "RNW.TO",
    "H.TO",
    # Industrials & transport
    "CNR.TO",
    "CP.TO",
    "WSP.TO",
    "STN.TO",
    "WCN.TO",
    "GFL.TO",
    "TFII.TO",
    "MG.TO",
    "CAE.TO",
    "BBD-B.TO",
    "NOA.TO",
    "AC.TO",
    "CHR.TO",
    "CJT.TO",
    # Tech
    "SHOP.TO",
    "CSU.TO",
    "OTEX.TO",
    "DSG.TO",
    "KXS.TO",
    "LSPD.TO",
    "ENGH.TO",
    "DCBO.TO",
    "TIXT.TO",
    "CLS.TO",
    "DOO.TO",
    # Consumer
    "ATD.TO",
    "L.TO",
    "MRU.TO",
    "DOL.TO",
    "QSR.TO",
    "CTC-A.TO",
    "GIL.TO",
    "WN.TO",
    "EMP-A.TO",
    "MFI.TO",
    "SAP.TO",
    "PBH.TO",
    "TOY.TO",
    "GOOS.TO",
    "ARE.TO",
    "BYD.TO",
    "CCL-B.TO",
    "PKI.TO",
    # Financials non-bank
    "BN.TO",
    "BAM.TO",
    "MFC.TO",
    "SLF.TO",
    "GWO.TO",
    "IFC.TO",
    "IAG.TO",
    "POW.TO",
    "X.TO",
    "IGM.TO",
    "ONEX.TO",
    "EFN.TO",
    "FFH.TO",
    "GSY.TO",
    "ECN.TO",
    "CIX.TO",
    "TMX.TO",
    # REITs
    "REI-UN.TO",
    "CAR-UN.TO",
    "GRT-UN.TO",
    "CHP-UN.TO",
    "SRU-UN.TO",
    "D-UN.TO",
    "AP-UN.TO",
    "HR-UN.TO",
    "DIR-UN.TO",
    "IIP-UN.TO",
    "FCR-UN.TO",
    # Healthcare
    "BHC.TO",
    "CPH.TO",
    "SIA.TO",
    # ETFs (always tradeable, useful as universe baseline)
    "XIU.TO",
    "XIC.TO",
    "ZEB.TO",
]


@dataclass
class UniverseFetchResult:
    tickers: list[str]
    source: str  # "xic_csv" | "cache" | "fallback"
    fetched_at: datetime
    fallback_reason: str | None = None


def _cache_path() -> Path:
    # Mirror existing yfinance cache layout
    root = Path(__file__).resolve().parents[3] / "data" / "cache" / "universe"
    root.mkdir(parents=True, exist_ok=True)
    return root / "tsx_composite.csv"


def _read_cache() -> list[str] | None:
    path = _cache_path()
    if not path.exists():
        return None
    age = datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if age > timedelta(hours=CACHE_TTL_HOURS):
        return None
    try:
        return path.read_text(encoding="utf-8").strip().splitlines()
    except Exception as e:
        log.warning("Universe cache read failed: %s", e)
        return None


def _write_cache(tickers: list[str]) -> None:
    try:
        _cache_path().write_text("\n".join(tickers), encoding="utf-8")
    except Exception as e:
        log.warning("Universe cache write failed: %s", e)


def _normalize_ticker(raw: str) -> str | None:
    """XIC CSV ticker -> Yahoo Finance format.

    Examples:
        RY -> RY.TO
        BBD/B -> BBD-B.TO
        CAR/UN -> CAR-UN.TO
        '-' (cash row) -> None
        '' -> None
    """
    s = raw.strip().strip('"').upper()
    if not s or s in {"-", "CAD", "USD", "CASH"}:
        return None
    # Skip obvious non-equity rows (futures, options, FX hedges)
    if any(c in s for c in {" ", "(", ")"}):
        return None
    s = s.replace("/", "-")
    return f"{s}.TO"


def _parse_xic_csv(text: str) -> list[str]:
    """Pull tickers from the XIC holdings CSV.

    iShares CSVs start with ~9 lines of fund metadata, then a blank line,
    then the constituents table. We skip to the row whose first cell is 'Ticker'.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().lower().startswith('"ticker"') or line.lstrip().lower().startswith("ticker,"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("XIC CSV: could not locate 'Ticker' header row")

    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))
    tickers: list[str] = []
    for row in reader:
        raw = row.get("Ticker") or row.get("ticker") or ""
        norm = _normalize_ticker(raw)
        if norm:
            tickers.append(norm)
    # Dedup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def fetch_xic_universe(timeout: float = 15.0) -> list[str]:
    """Download and parse the XIC holdings CSV. Raises on any failure."""
    resp = requests.get(
        XIC_HOLDINGS_URL,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; TSXPulse/0.1)"},
    )
    resp.raise_for_status()
    tickers = _parse_xic_csv(resp.text)
    if len(tickers) < 50:
        raise ValueError(f"XIC CSV parse returned only {len(tickers)} tickers; suspicious")
    return tickers


def get_universe(force_refresh: bool = False) -> UniverseFetchResult:
    """Primary entrypoint. Try cache -> live fetch -> fallback list, in order."""
    now = datetime.now(UTC)

    if not force_refresh:
        cached = _read_cache()
        if cached and len(cached) >= 50:
            log.info("Universe: using cache (%d tickers)", len(cached))
            return UniverseFetchResult(tickers=cached, source="cache", fetched_at=now)

    try:
        tickers = fetch_xic_universe()
        _write_cache(tickers)
        log.info("Universe: fetched %d tickers from XIC holdings", len(tickers))
        return UniverseFetchResult(tickers=tickers, source="xic_csv", fetched_at=now)
    except Exception as e:
        log.warning("XIC fetch failed (%s) — falling back to hardcoded list", e)
        return UniverseFetchResult(
            tickers=list(FALLBACK_UNIVERSE),
            source="fallback",
            fetched_at=now,
            fallback_reason=str(e),
        )
