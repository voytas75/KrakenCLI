"""Market data helpers for KrakenCLI.

Updates: v0.9.10 - 2025-11-15 - Added reusable OHLC payload helpers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


KNOWN_QUOTE_SUFFIXES: Tuple[str, ...] = (
    "ZUSDT",
    "USDT",
    "ZUSDC",
    "USDC",
    "ZUSD",
    "USD",
    "ZEUR",
    "EUR",
    "ZGBP",
    "GBP",
    "ZJPY",
    "JPY",
    "ZCAD",
    "CAD",
    "ZCHF",
    "CHF",
    "ZETH",
    "ETH",
    "ZBTC",
    "BTC",
    "XXBT",
    "XBT",
)


def normalize_asset_code(code: str) -> str:
    """Return a Kraken asset code without optional X/Z prefixes.

    Args:
        code: Raw Kraken asset identifier (e.g., ``XXBT``).

    Returns:
        Normalized asset code without double prefixes while preserving ticker length.
    """

    normalized = code.upper()
    while normalized.startswith(("X", "Z")) and len(normalized) > 3:
        normalized = normalized[1:]
    return normalized


def normalize_pair_key(pair_key: str) -> str:
    """Normalize Kraken pair identifiers (e.g., ``XETHZUSD`` -> ``ETHUSD``).

    Args:
        pair_key: Kraken pair identifier as returned by API payloads.

    Returns:
        Normalized pair string concatenating base and quote tickers.
    """

    key = pair_key.upper()
    if len(key) < 6:
        return key
    base, quote = split_pair_components(key)
    normalized_base = normalize_asset_code(base)
    normalized_quote = normalize_asset_code(quote)
    return f"{normalized_base}{normalized_quote}"


def split_pair_components(pair: str) -> Tuple[str, str]:
    """Split a Kraken pair string into base and quote components.

    Args:
        pair: Kraken trading pair (e.g., ``XETHZUSD``).

    Returns:
        Tuple of base and quote symbols preserving Kraken prefixes when present.
    """

    upper = pair.upper()
    for suffix in sorted(KNOWN_QUOTE_SUFFIXES, key=len, reverse=True):
        if upper.endswith(suffix):
            base = upper[: -len(suffix)]
            if base:
                return base, suffix
    return upper[:-3], upper[-3:]


def expand_base_variants(base: str) -> List[str]:
    """Return base asset variants including Kraken prefixes.

    Args:
        base: Base component of a trading pair.

    Returns:
        Unique list of candidate base codes.
    """

    base_upper = base.upper()
    core = base_upper.split(".")[0]
    variants = [
        core,
        f"X{core}",
        f"Z{core}",
        f"XX{core}",
        base_upper,
        f"X{base_upper}",
        f"Z{base_upper}",
    ]
    if base_upper.startswith(("X", "Z")) and len(base_upper) > 3:
        trimmed = base_upper[1:]
        variants.extend([trimmed, f"X{trimmed}", f"Z{trimmed}"])
    return dedupe_preserve_order(variants)


def expand_quote_variants(quote: str) -> List[str]:
    """Return quote asset variants including Kraken prefixes.

    Args:
        quote: Quote component of a trading pair.

    Returns:
        Unique list of candidate quote codes.
    """

    quote_upper = quote.upper()
    variants = [quote_upper, f"Z{quote_upper}"]
    if quote_upper.startswith(("X", "Z")) and len(quote_upper) > 3:
        trimmed = quote_upper[1:]
        variants.extend([trimmed, f"Z{trimmed}"])
    return dedupe_preserve_order(variants)


def dedupe_preserve_order(values: List[str]) -> List[str]:
    """Remove duplicates while preserving input order."""

    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def candidate_pair_keys(pair: str) -> List[str]:
    """Return most likely Kraken OHLC keys for a requested pair.

    Args:
        pair: User supplied trading pair (e.g., ``ETHUSD``).

    Returns:
        Candidate keys ordered by likelihood.
    """

    pair_upper = pair.upper()
    base, quote = split_pair_components(pair_upper)
    base_variants = expand_base_variants(base)
    quote_variants = expand_quote_variants(quote)

    candidates: List[str] = []
    for base_candidate in base_variants:
        for quote_candidate in quote_variants:
            candidates.append(f"{base_candidate}{quote_candidate}")

    if pair_upper not in candidates:
        candidates.insert(0, pair_upper)

    return dedupe_preserve_order(candidates)


def resolve_ohlc_payload(
    requested_pair: str,
    result: Dict[str, Any],
) -> Tuple[Optional[Iterable[Any]], Optional[str]]:
    """Locate the OHLC payload for a requested pair within a Kraken response.

    Args:
        requested_pair: Trading pair requested by the caller.
        result: Kraken ``public/OHLC`` response ``result`` payload.

    Returns:
        Tuple of the matching OHLC iterable and the key it was resolved from.
    """

    sanitized = {key: value for key, value in result.items() if key != "last"}
    if not sanitized:
        return None, None

    target_normalized = normalize_pair_key(requested_pair)
    candidates = candidate_pair_keys(requested_pair)
    for candidate in candidates:
        payload = sanitized.get(candidate)
        if not payload:
            continue
        if normalize_pair_key(candidate) == target_normalized:
            return payload, candidate
    for key, payload in sanitized.items():
        if not payload:
            continue
        if normalize_pair_key(key) == target_normalized:
            return payload, key
    return None, None
