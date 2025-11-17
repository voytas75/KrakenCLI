"""Natural-language pattern description mapper with rule-based heuristics
and optional LiteLLM fallback.

This module maps a user-provided description string to one of the existing
detector ids plus optional parameters. It does NOT introduce a generic DSL.
It stays constrained to:
- pattern_name ∈ {
    'ma_crossover', 'rsi_extreme', 'bollinger_touch',
    'macd_signal_cross', 'candle_hammer', 'candle_shooting_star'
  }
- direction ∈ {'bullish', 'bearish', 'both'} (optional)
- move_window ∈ [1, 50] (optional)
- rsi_oversold ∈ [5, 50] (optional)
- rsi_overbought ∈ [50, 95] (optional)

Flow:
- Apply rule-based heuristics first for speed and determinism.
- If no mapping or low confidence and LLM is enabled, call PatternLLMClient.
- Validate and normalise the final result.

Updates:
    v0.9.16 - 2025-11-17 - Initial NL mapper with rule-based + LLM fallback
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .pattern_llm_client import PatternLLMClient, PatternLLMError

logger = logging.getLogger(__name__)


SUPPORTED_PATTERNS: tuple[str, ...] = (
    "ma_crossover",
    "rsi_extreme",
    "bollinger_touch",
    "macd_signal_cross",
    "candle_hammer",
    "candle_shooting_star",
    "single_candle_move",
)


@dataclass(slots=True)
class PatternMappingRequest:
    """Request for mapping a natural-language description.

    Args:
        description: User-provided description text.
        pair: Normalised trading pair (e.g., 'ETHUSD').
        timeframe_minutes: Candle interval in minutes (already parsed).
        lookback_days: Historical lookback in days.
    """

    description: str
    pair: str
    timeframe_minutes: int
    lookback_days: int


@dataclass(slots=True)
class PatternMappingResult:
    """Result of mapping a description to existing detectors.

    Attributes:
        pattern_name: Chosen detector id from SUPPORTED_PATTERNS.
        direction: Optional direction filter ('bullish'/'bearish'/'both').
        move_window: Optional future window (1..50) for move percentage.
        rsi_oversold: Optional RSI oversold threshold (5..50).
        rsi_overbought: Optional RSI overbought threshold (50..95).
        threshold_pct: Optional percent threshold for single-candle move (0.1..50).
        confidence: Optional confidence score (0..1).
        source: Mapping source ('rule-based' or 'llm').
        notes: Optional notes/hints about mapping decisions.
    """

    pattern_name: str
    direction: Optional[str] = None
    move_window: Optional[int] = None
    rsi_oversold: Optional[float] = None
    rsi_overbought: Optional[float] = None
    threshold_pct: Optional[float] = None
    confidence: Optional[float] = None
    source: str = "rule-based"
    notes: Optional[str] = None


class PatternDescriptionMapper:
    """Mapper for NL descriptions to constrained detector mapping.

    Strategy:
        1) Rule-based keyword/regex matching for common phrases.
        2) If no match or low confidence, and LLM is enabled, use LiteLLM
           via PatternLLMClient.
        3) Validate results (bounds, allowed values) and return.

    The mapper never changes scanning logic; it only decides which fixed
    detector to run and optional filter/params surfaced at the CLI layer.
    """

    def __init__(self, llm_client: Optional[PatternLLMClient] = None) -> None:
        """Initialise the mapper.

        Args:
            llm_client: Optional pre-initialised PatternLLMClient. If omitted,
                a new client instance is created lazily when needed.
        """
        self._llm_client = llm_client

    def map(
        self,
        request: PatternMappingRequest,
        supported_patterns: Iterable[str] = SUPPORTED_PATTERNS,
    ) -> PatternMappingResult:
        """Map a description to a PatternMappingResult.

        Args:
            request: Mapping request containing description and context.
            supported_patterns: Optional override of supported detector ids.

        Returns:
            PatternMappingResult with validated fields.

        Raises:
            ValueError: If mapping fails or yields invalid data.
        """
        patterns = tuple(p for p in supported_patterns if p in SUPPORTED_PATTERNS)
        if not patterns:
            raise ValueError("No supported patterns provided for mapping.")

        # First pass: rule-based heuristics
        rb = self._rule_based_mapping(request.description, patterns)
        if rb is not None:
            return rb

        # LLM fallback
        client = self._llm_client or PatternLLMClient()
        if not client.is_enabled:
            raise ValueError(
                "Could not map description via rules; LLM disabled. "
                "Enable PATTERN_LLM_ENABLED=true and configure PATTERN_LLM_MODEL."
            )

        try:
            payload = client.map_description(request.description, patterns)
        except PatternLLMError as exc:
            raise ValueError(f"LLM mapping failed: {exc}") from exc

        result = PatternMappingResult(
            pattern_name=str(payload.get("pattern_name")),
            direction=_norm_direction(payload.get("direction")),
            move_window=_norm_move_window(payload.get("move_window")),
            rsi_oversold=_norm_rsi_oversold(payload.get("rsi_oversold")),
            rsi_overbought=_norm_rsi_overbought(payload.get("rsi_overbought")),
            confidence=_norm_confidence(payload.get("confidence")),
            source="llm",
            notes=str(payload.get("notes")) if payload.get("notes") else None,
        )
        _validate_result(result, patterns)
        return result

    # -----------------------------
    # Rule-based heuristics
    # -----------------------------
    def _rule_based_mapping(
        self, description: str, patterns: Iterable[str]
    ) -> Optional[PatternMappingResult]:
        """Return mapping via keyword/regex heuristics or None if inconclusive."""
        text = (description or "").lower()

        # First: explicit single-candle percent move (e.g., "up 5% in one candle")
        if "single_candle_move" in patterns:
            percent_match = re.search(r"(\d{1,3})\s*%", text)
            candle_match = re.search(r"\b(one|1)\s+(candle|bar|period)\b", text) or re.search(
                r"\b(candle|bar|period)\b", text
            )
            if percent_match and candle_match:
                try:
                    threshold = float(percent_match.group(1))
                except (TypeError, ValueError):
                    threshold = None

                if threshold is not None and 0.1 <= threshold <= 50.0:
                    dir_hint: Optional[str] = None
                    if re.search(r"\b(up|rise|increase|gain)\b", text):
                        dir_hint = "bullish"
                    elif re.search(r"\b(down|fall|decrease|drop|loss)\b", text):
                        dir_hint = "bearish"

                    result = PatternMappingResult(
                        pattern_name="single_candle_move",
                        direction=dir_hint,
                        move_window=_extract_move_window(text),
                        rsi_oversold=_extract_rsi_level(text, kind="oversold"),
                        rsi_overbought=_extract_rsi_level(text, kind="overbought"),
                        threshold_pct=threshold,
                        confidence=0.95,
                        source="rule-based",
                        notes=None,
                    )
                    _validate_result(result, patterns)
                    return result

        # Direction hints
        direction: Optional[str] = None
        if re.search(r"\b(bullish|long)\b", text):
            direction = "bullish"
        if re.search(r"\b(bearish|short)\b", text):
            # If both words appear, prefer 'both'
            direction = "bearish" if direction is None else "both"

        # Move window: e.g., "next 24 candles", "look 12 bars ahead"
        move_window = _extract_move_window(text)

        # RSI levels
        rsi_oversold = _extract_rsi_level(text, kind="oversold")
        rsi_overbought = _extract_rsi_level(text, kind="overbought")

        # Detector identification by keywords
        mapping_candidates: list[tuple[str, float]] = []

        if any(
            re.search(pat, text)
            for pat in (
                r"\b(ma|moving\s+average|ema)\b.*\b(cross|crossover)\b",
                r"\bcrossover\b.*\b(ma|moving\s+average|ema)\b",
            )
        ) and "ma_crossover" in patterns:
            mapping_candidates.append(("ma_crossover", 0.85))

        if re.search(r"\brsi\b", text) and "rsi_extreme" in patterns:
            # oversold/overbought hint increases confidence
            conf = 0.75
            if re.search(r"\b(oversold|below\s+\d{2})\b", text):
                conf = 0.85
            if re.search(r"\b(overbought|above\s+\d{2})\b", text):
                conf = max(conf, 0.85)
            mapping_candidates.append(("rsi_extreme", conf))

        if re.search(r"\bbollinger\b", text) and "bollinger_touch" in patterns:
            if re.search(r"\bband(s)?\b", text):
                mapping_candidates.append(("bollinger_touch", 0.8))

        if re.search(r"\bmacd\b", text) and "macd_signal_cross" in patterns:
            if re.search(r"\bsignal\s+line\b", text) or re.search(r"\bcross\b", text):
                mapping_candidates.append(("macd_signal_cross", 0.85))

        if re.search(r"\bhammer\b", text) and "candle_hammer" in patterns:
            mapping_candidates.append(("candle_hammer", 0.9))

        if re.search(r"\bshooting\s*star\b", text) and "candle_shooting_star" in patterns:
            mapping_candidates.append(("candle_shooting_star", 0.9))

        if not mapping_candidates:
            return None

        # Pick highest confidence candidate
        mapping_candidates.sort(key=lambda x: x[1], reverse=True)
        pattern_name, confidence = mapping_candidates[0]

        result = PatternMappingResult(
            pattern_name=pattern_name,
            direction=direction,
            move_window=move_window,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            threshold_pct=None,
            confidence=confidence,
            source="rule-based",
            notes=None,
        )
        _validate_result(result, patterns)
        return result


# -----------------------------
# Normalisation and validation
# -----------------------------
def _norm_direction(value: Any) -> Optional[str]:
    if value is None:
        return None
    v = str(value).lower().strip()
    if v in {"bullish", "bearish", "both"}:
        return v
    return None


def _norm_move_window(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 50:
        return None
    return n


def _norm_rsi_oversold(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 5.0 or x > 50.0:
        return None
    return x


def _norm_rsi_overbought(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 50.0 or x > 95.0:
        return None
    return x


def _norm_confidence(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 0.0 or x > 1.0:
        return None
    return x


def _norm_threshold_pct(value: Any) -> Optional[float]:
    """Normalise single-candle percent threshold (bounds: 0.1..50.0)."""
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x < 0.1 or x > 50.0:
        return None
    return x


def _validate_result(result: PatternMappingResult, patterns: Iterable[str]) -> None:
    """Validate final mapping result within constraints."""
    if result.pattern_name not in patterns:
        raise ValueError(f"Unsupported pattern_name: {result.pattern_name}")

    if result.direction is not None and result.direction not in {"bullish", "bearish", "both"}:
        raise ValueError(f"Invalid direction: {result.direction}")

    if result.move_window is not None:
        if result.move_window < 1 or result.move_window > 50:
            raise ValueError(f"move_window out of bounds: {result.move_window}")

    if result.rsi_oversold is not None:
        if result.rsi_oversold < 5.0 or result.rsi_oversold > 50.0:
            raise ValueError(f"rsi_oversold out of bounds: {result.rsi_oversold}")

    if result.rsi_overbought is not None:
        if result.rsi_overbought < 50.0 or result.rsi_overbought > 95.0:
            raise ValueError(f"rsi_overbought out of bounds: {result.rsi_overbought}")

    if result.threshold_pct is not None:
        if result.threshold_pct < 0.1 or result.threshold_pct > 50.0:
            raise ValueError(f"threshold_pct out of bounds: {result.threshold_pct}")

    if result.confidence is not None:
        if result.confidence < 0.0 or result.confidence > 1.0:
            raise ValueError(f"confidence out of bounds: {result.confidence}")


# -----------------------------
# Regex helpers
# -----------------------------
MOVE_WINDOW_PATTERNS = (
    # "next 24 candles", "in next 12 bars"
    re.compile(r"\bnext\s+(\d{1,3})\s+(candles|bars|periods?)\b"),
    # "look 12 bars ahead", "over the next 6 candles"
    re.compile(r"\b(?:look|over)\s+the?\s*(?:next\s*)?(\d{1,3})\s+(candles|bars|periods?)\b"),
    # "in 24 candles", "within 10 bars"
    re.compile(r"\b(?:in|within)\s+(\d{1,3})\s+(candles|bars|periods?)\b"),
    # "24 candles ahead"
    re.compile(r"\b(\d{1,3})\s+(candles|bars|periods?)\s+(ahead|forward)\b"),
)


def _extract_move_window(text: str) -> Optional[int]:
    """Extract an integer move window from description text."""
    for pat in MOVE_WINDOW_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 50:
                return n
    return None


def _extract_rsi_level(text: str, kind: str) -> Optional[float]:
    """Extract RSI threshold from text for 'oversold' or 'overbought'."""
    # Kind: oversold => look for "below X" or explicit "oversold"
    # Kind: overbought => look for "above X" or explicit "overbought"
    if kind == "oversold":
        # "RSI below 25", "RSI < 30"
        patterns = (
            re.compile(r"\brsi\b[^0-9]*\bbelow\b\s*(\d{1,2})"),
            re.compile(r"\brsi\b[^0-9]*<\s*(\d{1,2})"),
            re.compile(r"\boversold\b[^0-9]*\b(?:at|below)?\s*(\d{1,2})"),
        )
        lower, upper = 5.0, 50.0
    elif kind == "overbought":
        patterns = (
            re.compile(r"\brsi\b[^0-9]*\babove\b\s*(\d{1,2})"),
            re.compile(r"\brsi\b[^0-9]*>\s*(\d{1,2})"),
            re.compile(r"\boverbought\b[^0-9]*\b(?:at|above)?\s*(\d{1,2})"),
        )
        lower, upper = 50.0, 95.0
    else:
        return None

    for pat in patterns:
        m = pat.search(text)
        if m:
            try:
                x = float(m.group(1))
            except (TypeError, ValueError):
                continue
            if lower <= x <= upper:
                return x
    return None