"""LLM client wrapper for natural-language pattern mapping using LiteLLM.

This module encapsulates integration with LiteLLM to translate a
user-provided natural language description into a constrained mapping
for existing detectors (no generic DSL). It reads configuration from
environment variables and enforces deterministic, validated JSON output.

Environment variables:
    PATTERN_LLM_ENABLED: "true"/"false" (default: "false")
    PATTERN_LLM_MODEL: "<provider>/<model>" (e.g., "openai/gpt-4o-mini")
    PATTERN_LLM_TIMEOUT: seconds as float (default: "10")
    PATTERN_LLM_MAX_TOKENS: integer (default: "512")
    PATTERN_LLM_TEMPERATURE: float (default: "0.0")

Provider API keys (handled by LiteLLM):
    OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.

Design notes:
- Deterministic: temperature defaults to 0.0.
- Safe parsing: strict JSON-only response is requested; we validate fields.
- Constrained output schema tailored to existing detectors.

Updates:
    v0.9.18 - 2025-11-17 - Added OHLC explanation method.
    v0.9.17 - 2025-11-17 - Added heatmap explanation method.
    v0.9.16 - 2025-11-17 - Initial LiteLLM client implementation
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)


class PatternLLMError(RuntimeError):
    """Error raised when LLM-based mapping fails."""


class PatternLLMClient:
    """LiteLLM-backed client for pattern description mapping.

    This client takes a natural language description and returns a JSON
    mapping selecting one of the known detectors and optional parameters
    such as direction and move window. It enforces validation to keep
    outputs within safe bounds.

    Example usage:
        client = PatternLLMClient()
        if client.is_enabled:
            result = client.map_description(
                description="Bullish MACD cross in next 24 candles",
                supported_patterns=[
                    "ma_crossover",
                    "rsi_extreme",
                    "bollinger_touch",
                    "macd_signal_cross",
                    "candle_hammer",
                    "candle_shooting_star",
                ],
            )
    """

    DEFAULT_TIMEOUT_SECONDS: float = 10.0
    DEFAULT_MAX_TOKENS: int = 512
    DEFAULT_TEMPERATURE: float = 0.0

    def __init__(self) -> None:
        """Initialise client by loading environment configuration."""
        self._enabled = (os.getenv("PATTERN_LLM_ENABLED", "false").lower() == "true")
        self._model = os.getenv("PATTERN_LLM_MODEL") or ""
        self._timeout = float(os.getenv("PATTERN_LLM_TIMEOUT", str(self.DEFAULT_TIMEOUT_SECONDS)))
        self._max_tokens = int(os.getenv("PATTERN_LLM_MAX_TOKENS", str(self.DEFAULT_MAX_TOKENS)))
        self._temperature = float(
            os.getenv("PATTERN_LLM_TEMPERATURE", str(self.DEFAULT_TEMPERATURE))
        )

        # Lazy import to avoid hard dependency when disabled
        self._litellm = None
        if self._enabled and self._model:
            try:
                from litellm import completion  # type: ignore
                self._litellm = completion
            except Exception as exc:
                logger.error("LiteLLM import failed: %s", exc)
                self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Return True if NL mapping via LLM is enabled and configured."""
        return self._enabled and bool(self._model) and (self._litellm is not None)

    def map_description(
        self,
        description: str,
        supported_patterns: Iterable[str],
    ) -> Dict[str, Any]:
        """Map natural language description to constrained JSON via LiteLLM.

        Args:
            description: User-provided natural language pattern description.
            supported_patterns: Iterable of allowed detector ids.

        Returns:
            A validated mapping dictionary with keys:
            - pattern_name: str (in supported_patterns)
            - direction: str | None ('bullish' | 'bearish' | 'both' | None)
            - move_window: int | None (1..50)
            - rsi_oversold: float | None (5..50)
            - rsi_overbought: float | None (50..95)
            - confidence: float | None (0..1)
            - notes: str | None

        Raises:
            PatternLLMError: on configuration issues, provider errors, or
                schema validation failures.
        """
        if not self.is_enabled:
            raise PatternLLMError(
                "LLM mapping disabled or not configured. "
                "Set PATTERN_LLM_ENABLED=true and PATTERN_LLM_MODEL=<provider>/<model>."
            )

        patterns = [str(p).strip() for p in supported_patterns if str(p).strip()]
        if not patterns:
            raise PatternLLMError("No supported patterns provided for LLM mapping.")

        system_prompt = self._build_system_prompt(patterns)
        user_prompt = self._build_user_prompt(description, patterns)

        try:
            # LiteLLM completion API: unified interface for providers
            resp = self._litellm(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise PatternLLMError(f"LLM provider error: {exc}") from exc

        content = self._extract_text_content(resp)
        if not content:
            raise PatternLLMError("LLM returned empty content.")

        # Expect strict JSON; attempt to parse
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PatternLLMError(f"Failed to parse JSON from LLM response: {exc}") from exc

        validated = self._validate_payload(payload, patterns)
        return validated

    def explain_heatmap(self, summary: Dict[str, Any]) -> str:
        """Generate a concise natural-language explanation for a heatmap.

        Args:
            summary: Structured data containing heatmap context:
                {
                    "pair": str,
                    "timeframe": str,
                    "pattern": str,
                    "group_by": str,
                    "thresholds": {"min_move_pct": float, "window": int, "lookback_days": int},
                    "total_filtered_matches": int,
                    "buckets": [{"bucket": str, "matches": int, "avg_move_pct": float}, ...],
                }

        Returns:
            Plain-text explanation string suitable for CLI display.

        Raises:
            PatternLLMError: If LLM is disabled/misconfigured or provider fails.
        """
        if not self.is_enabled:
            raise PatternLLMError(
                "LLM explanation disabled or not configured. "
                "Set PATTERN_LLM_ENABLED=true and PATTERN_LLM_MODEL=<provider>/<model>."
            )

        # Analyst-style guidance without financial advice; concise and actionable
        system_prompt = (
            "You are a quantitative trading analyst. Given structured heatmap "
            "data for historical pattern performance, produce a concise "
            "explanation (<= 150 words) highlighting:\n"
            "- Strongest and weakest buckets (by avg move and matches)\n"
            "- Reliability notes based on sample sizes\n"
            "- Practical cautions (e.g., regime changes, day/time biases)\n\n"
            "Constraints:\n"
            "- Suggest one actionable insight for deeper analysis based on the data\n"
            "- Plain text only (no JSON, no markdown)\n"
            "- Do not provide financial advice\n"
            "- Include a safety disclaimer: 'Past performance does not guarantee "
            "future results.'"
        )

        # Use JSON-encoded user content for structured input
        user_prompt = json.dumps(summary, ensure_ascii=False)

        try:
            resp = self._litellm(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise PatternLLMError(f"LLM provider error: {exc}") from exc

        content = self._extract_text_content(resp)
        if not content:
            raise PatternLLMError("LLM returned empty content.")
        return str(content).strip()

    def explain_ohlc(self, summary: Dict[str, Any]) -> str:
        """Generate a concise natural-language explanation for an OHLC sample.

        Args:
            summary: Structured data containing OHLC context:
                {
                    "pair": str,
                    "interval_minutes": int,
                    "count": int,
                    "source": "api" | "local",
                    "since": int | None,
                    "time_range": {"start": str, "end": str},
                    "stats": {"last_close": float, "avg_range_pct": float},
                }

        Returns:
            Plain-text explanation string suitable for CLI display.

        Raises:
            PatternLLMError: If LLM is disabled/misconfigured or provider fails.
        """
        if not self.is_enabled:
            raise PatternLLMError(
                "LLM explanation disabled or not configured. "
                "Set PATTERN_LLM_ENABLED=true and PATTERN_LLM_MODEL=<provider>/<model>."
            )

        system_prompt = (
            "You are a quantitative trading analyst. Given structured OHLC data "
            "summary, produce a concise explanation (<= 120 words) highlighting:\n"
            "- Recent trend direction over the sample\n"
            "- Volatility indication using avg intrabar range (% of open)\n"
            "- Notable cautionary notes (sampling bias, low count)\n\n"
            "Constraints:\n"
            "- Plain text only (no JSON, no markdown)\n"
            "- Do not provide financial advice\n"
            "- Include a safety disclaimer: 'Past performance does not guarantee "
            "future results.'"
        )

        user_prompt = json.dumps(summary, ensure_ascii=False)

        try:
            resp = self._litellm(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise PatternLLMError(f"LLM provider error: {exc}") from exc

        content = self._extract_text_content(resp)
        if not content:
            raise PatternLLMError("LLM returned empty content.")
        return str(content).strip()

    def _build_system_prompt(self, patterns: list[str]) -> str:
        """Construct system prompt with constraints and schema."""
        lines = [
            "You are a classifier and translator that maps a user's natural-language",
            "trading pattern description to one of the SUPPORTED PATTERN IDS.",
            "",
            "REQUIREMENTS:",
            "- OUTPUT STRICT JSON ONLY (no prose, no markdown).",
            "- Choose exactly one 'pattern_name' from SUPPORTED PATTERNS.",
            "- Optional fields allowed: 'direction', 'move_window',",
            "  'rsi_oversold', 'rsi_overbought', 'threshold_pct', 'confidence', 'notes'.",
            "- Enforce constraints:",
            "  * direction ∈ {'bullish','bearish','both'}",
            "  * move_window ∈ [1, 50] (integer)",
            "  * rsi_oversold ∈ [5, 50] (float)",
            "  * rsi_overbought ∈ [50, 95] (float)",
            "  * confidence ∈ [0.0, 1.0]",
            "",
            "SUPPORTED PATTERNS:",
            *[f"- {p}" for p in patterns],
            "",
            "If ambiguous, pick the closest pattern and set 'notes' briefly.",
            "Do NOT include any additional text outside JSON.",
        ]
        return "\n".join(lines)

    def _build_user_prompt(self, description: str, patterns: list[str]) -> str:
        """Construct user prompt including description and patterns."""
        return json.dumps(
            {
                "description": description,
                "supported_patterns": patterns,
                "output_schema_example": {
                    "pattern_name": "single_candle_move",
                    "direction": "bullish",
                    "move_window": 24,
                    "rsi_oversold": None,
                    "rsi_overbought": None,
                    "threshold_pct": 5.0,
                    "confidence": 0.9,
                    "notes": "Single-candle percent move threshold mapping.",
                },
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _extract_text_content(response: Any) -> str:
        """Extract the textual content from a LiteLLM response structure."""
        try:
            # OpenAI-compatible schema
            choices = response.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            return str(content).strip()
        except Exception:
            return ""

    @staticmethod
    def _validate_payload(payload: Dict[str, Any], patterns: list[str]) -> Dict[str, Any]:
        """Validate and normalise the LLM JSON payload within constraints."""
        def _get_opt_str(key: str) -> Optional[str]:
            v = payload.get(key)
            if v is None:
                return None
            return str(v).strip() or None

        def _get_opt_float(key: str) -> Optional[float]:
            v = payload.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _get_opt_int(key: str) -> Optional[int]:
            v = payload.get(key)
            if v is None or v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        result: Dict[str, Any] = {}

        # pattern_name
        pattern_name = _get_opt_str("pattern_name")
        if not pattern_name or pattern_name not in patterns:
            raise PatternLLMError(
                f"Invalid or unsupported pattern_name: {pattern_name!r}"
            )
        result["pattern_name"] = pattern_name

        # direction
        direction = _get_opt_str("direction")
        if direction is not None:
            direction_l = direction.lower()
            if direction_l not in {"bullish", "bearish", "both"}:
                raise PatternLLMError(f"Invalid direction: {direction!r}")
            result["direction"] = direction_l
        else:
            result["direction"] = None

        # move_window
        move_window = _get_opt_int("move_window")
        if move_window is not None:
            if move_window < 1 or move_window > 50:
                raise PatternLLMError(f"move_window out of bounds: {move_window}")
            result["move_window"] = move_window
        else:
            result["move_window"] = None

        # RSI thresholds
        rsi_oversold = _get_opt_float("rsi_oversold")
        if rsi_oversold is not None:
            if rsi_oversold < 5.0 or rsi_oversold > 50.0:
                raise PatternLLMError(f"rsi_oversold out of bounds: {rsi_oversold}")
            result["rsi_oversold"] = rsi_oversold
        else:
            result["rsi_oversold"] = None

        rsi_overbought = _get_opt_float("rsi_overbought")
        if rsi_overbought is not None:
            if rsi_overbought < 50.0 or rsi_overbought > 95.0:
                raise PatternLLMError(f"rsi_overbought out of bounds: {rsi_overbought}")
            result["rsi_overbought"] = rsi_overbought
        else:
            result["rsi_overbought"] = None

        # confidence
        confidence = _get_opt_float("confidence")
        if confidence is not None:
            if confidence < 0.0 or confidence > 1.0:
                raise PatternLLMError(f"confidence out of bounds: {confidence}")
            result["confidence"] = confidence
        else:
            result["confidence"] = None

        # threshold_pct
        threshold_pct = _get_opt_float("threshold_pct")
        if threshold_pct is not None:
            if threshold_pct < 0.1 or threshold_pct > 50.0:
                raise PatternLLMError(f"threshold_pct out of bounds: {threshold_pct}")
            result["threshold_pct"] = threshold_pct
        else:
            result["threshold_pct"] = None

        # notes
        result["notes"] = _get_opt_str("notes")

        return result