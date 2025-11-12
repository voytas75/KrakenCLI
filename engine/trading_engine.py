"""
Automated trading engine coordinating strategies, risk, and trade execution.

Updates:
    v0.9.0 - 2025-11-11 - Added polling engine with persistent status reporting.
    v0.9.2 - 2025-11-12 - Integrated risk-based protective orders and realised PnL tracking.
    v0.9.3 - 2025-11-12 - Wired alert manager notifications into engine lifecycle.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from portfolio.portfolio_manager import PortfolioManager
from risk import RiskDecision, RiskManager
from strategies.base_strategy import StrategyContext, StrategySignal
from strategies.strategy_manager import StrategyManager
from trading.trader import Trader

if TYPE_CHECKING:
    from alerts.alert_manager import AlertManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TradingEngineStatus:
    """Structured status payload for CLI display."""

    running: bool
    dry_run: bool
    last_cycle_at: Optional[datetime] = None
    last_error: Optional[str] = None
    active_pairs: List[str] = field(default_factory=list)
    active_strategies: List[str] = field(default_factory=list)
    processed_signals: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "dry_run": self.dry_run,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_error": self.last_error,
            "active_pairs": self.active_pairs,
            "active_strategies": self.active_strategies,
            "processed_signals": self.processed_signals,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "TradingEngineStatus":
        status = TradingEngineStatus(
            running=payload.get("running", False),
            dry_run=payload.get("dry_run", True),
            last_error=payload.get("last_error"),
            active_pairs=list(payload.get("active_pairs", [])),
            active_strategies=list(payload.get("active_strategies", [])),
            processed_signals=int(payload.get("processed_signals", 0)),
        )
        if payload.get("last_cycle_at"):
            status.last_cycle_at = datetime.fromisoformat(payload["last_cycle_at"])
        return status


class TradingEngine:
    """Polling trading engine coordinating strategy evaluation."""

    _KNOWN_QUOTE_SUFFIXES: Tuple[str, ...] = (
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

    TIMEFRAME_TO_INTERVAL = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }

    def __init__(
        self,
        trader: Trader,
        portfolio_manager: PortfolioManager,
        strategy_manager: StrategyManager,
        risk_manager: RiskManager,
        control_dir: Path,
        poll_interval: int = 300,
        rate_limit: float = 1.0,
        alert_manager: Optional["AlertManager"] = None,
    ):
        self.trader = trader
        self.portfolio_manager = portfolio_manager
        self.strategy_manager = strategy_manager
        self.risk_manager = risk_manager
        self.poll_interval = poll_interval
        self.rate_delay = 1.0 / max(rate_limit, 0.1)
        self.alert_manager = alert_manager

        self.control_dir = control_dir
        self.control_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.control_dir / "status.json"
        self.stop_flag_file = self.control_dir / "stop.flag"

        self._stop_event = threading.Event()
        self._status = TradingEngineStatus(running=False, dry_run=True)

    def run_forever(
        self,
        strategy_keys: Optional[Sequence[str]] = None,
        dry_run: bool = True,
        poll_interval: Optional[int] = None,
        max_cycles: Optional[int] = None,
        pairs_override: Optional[Sequence[str]] = None,
        timeframe_override: Optional[str] = None,
    ) -> None:
        """Execute trading cycles until stop requested or max_cycles reached."""
        self.strategy_manager.refresh()
        self._status.running = True
        self._status.dry_run = dry_run
        self._status.last_error = None
        self._persist_status()

        interval = poll_interval or self.poll_interval
        cycle_count = 0

        try:
            while not self._should_stop():
                cycle_count += 1
                start_time = time.perf_counter()
                logger.info(
                    "Starting trading cycle %d (dry_run=%s, poll_interval=%ss)",
                    cycle_count,
                    dry_run,
                    interval,
                )
                try:
                    processed = self.run_once(
                        strategy_keys=strategy_keys,
                        dry_run=dry_run,
                        pairs_override=pairs_override,
                        timeframe_override=timeframe_override,
                    )
                    self._status.processed_signals = processed
                    self._status.last_cycle_at = datetime.now(tz=timezone.utc)
                    self._status.last_error = None
                    logger.info(
                        "Completed trading cycle %d (processed_signals=%d)",
                        cycle_count,
                        processed,
                    )
                except Exception as exc:  # pragma: no cover - protective guard
                    logger.exception("Trading engine cycle failed: %s", exc)
                    self._status.last_error = str(exc)
                    self._send_alert(
                        event="engine.cycle_error",
                        message=f"Trading engine cycle failed: {exc}",
                        severity="ERROR",
                        details={"cycle": cycle_count},
                        cooldown=120,
                    )
                finally:
                    self._persist_status()

                if max_cycles is not None and cycle_count >= max_cycles:
                    break

                elapsed = time.perf_counter() - start_time
                sleep_time = max(0.0, interval - elapsed)
                if sleep_time > 0:
                    self._stop_event.wait(timeout=sleep_time)
        finally:
            self._status.running = False
            self._persist_status()
            self._clear_stop_flag()
            severity = "WARNING" if self._status.last_error else "INFO"
            message = "Trading engine stopped."
            if self._status.last_error:
                message = f"Trading engine stopped due to error: {self._status.last_error}"
            self._send_alert(
                event="engine.stopped",
                message=message,
                severity=severity,
                details={
                    "last_error": self._status.last_error,
                    "last_cycle_at": self._status.last_cycle_at.isoformat() if self._status.last_cycle_at else None,
                },
                cooldown=0,
            )

    def run_once(
        self,
        strategy_keys: Optional[Sequence[str]] = None,
        dry_run: bool = True,
        pairs_override: Optional[Sequence[str]] = None,
        timeframe_override: Optional[str] = None,
    ) -> int:
        """Execute a single trading evaluation cycle."""
        strategies = self._select_strategies(strategy_keys)
        self._status.active_strategies = [strategy.name for strategy in strategies]

        balances = self.portfolio_manager.get_balances()
        positions = self.portfolio_manager.get_open_positions()

        processed_signals = 0
        active_pairs: List[str] = []

        for strategy in strategies:
            pairs = list(pairs_override) if pairs_override else self._extract_pairs(strategy.config.parameters)
            timeframe = timeframe_override or strategy.config.timeframe
            interval = self.TIMEFRAME_TO_INTERVAL.get(timeframe, 60)

            for pair in pairs:
                active_pairs.append(pair)
                ohlcv = self._fetch_ohlcv(pair, interval)
                if ohlcv is None:
                    continue

                context = StrategyContext(
                    pair=pair,
                    timeframe=timeframe,
                    ohlcv=ohlcv,
                    account_balances=balances,
                    open_positions=positions,
                    config=strategy.config,
                )

                signals = strategy.generate_signals(context)
                for signal in signals:
                    processed_signals += 1
                    decision = self.risk_manager.evaluate_signal(signal, context)
                    if not decision.approved:
                        logger.info("⚠️  Signal skipped: %s (%s)", signal.reason, decision.reason)
                        self._send_alert(
                            event="risk.decision_rejected",
                            message=f"{pair}: {decision.reason}",
                            severity="WARNING",
                            details={
                                "pair": pair,
                                "strategy": strategy.name,
                                "confidence": f"{signal.confidence:.2f}",
                            },
                            cooldown=180,
                        )
                        continue

                    if dry_run:
                        logger.info(
                            "🔍 Dry-run signal approved for %s: %s %.4f (confidence %.2f)",
                            pair,
                            signal.action,
                            decision.volume or 0.0,
                            signal.confidence,
                        )
                        realised = self.risk_manager.record_execution(pair, decision, context)
                        if realised != 0.0:
                            logger.info("📈 Dry-run realised PnL for %s: %.2f", pair, realised)
                            if realised < 0:
                                self._send_alert(
                                    event="risk.dry_run_loss",
                                    message=f"Dry-run loss recorded for {pair}: {realised:.2f}",
                                    severity="INFO",
                                    details={"pair": pair, "strategy": strategy.name},
                                    cooldown=180,
                                )
                        continue

                    success = self._execute_order(pair, signal, decision)
                    if success:
                        realised = self.risk_manager.record_execution(pair, decision, context)
                        if realised != 0.0:
                            logger.info("📊 Realised PnL recorded for %s: %.2f", pair, realised)
                            if realised < 0:
                                self._send_alert(
                                    event="risk.realised_loss",
                                    message=f"Realised loss recorded for {pair}: {realised:.2f}",
                                    severity="WARNING",
                                    details={"pair": pair, "strategy": strategy.name},
                                    cooldown=120,
                                )
                    time.sleep(self.rate_delay)

                time.sleep(self.rate_delay)

        self._status.active_pairs = active_pairs
        return processed_signals

    def request_stop(self) -> None:
        """Signal the engine loop to halt."""
        self._stop_event.set()
        self._persist_stop_flag()

    def _execute_order(
        self,
        pair: str,
        signal: StrategySignal,
        decision: RiskDecision,
    ) -> bool:
        volume = decision.volume
        if volume is None or volume <= 0:
            logger.warning("Calculated order volume invalid; skipping order for %s.", pair)
            return False

        try:
            result = self.trader.place_order(
                pair=pair,
                type=signal.action,
                ordertype="market",
                volume=volume,
                validate=False,
            )
            if not result:
                logger.error("Order placement returned no result for %s.", pair)
                return False

            logger.info("✅ Order placed for %s: %s", pair, result)

            if not decision.closing_position:
                self._place_protective_orders(pair, signal, decision, volume)

            return True
        except Exception as exc:
            logger.error("Failed to place order for %s: %s", pair, exc)
            return False

    def _place_protective_orders(
        self,
        pair: str,
        signal: StrategySignal,
        decision: RiskDecision,
        volume: float,
    ) -> None:
        """Submit stop-loss and take-profit orders when configured."""
        protective_type = "sell" if signal.action == "buy" else "buy"

        if decision.stop_loss_price:
            try:
                self.trader.place_order(
                    pair=pair,
                    type=protective_type,
                    ordertype="stop-loss",
                    volume=volume,
                    price=decision.stop_loss_price,
                    validate=False,
                )
                logger.info("🛡️  Stop loss submitted for %s at %.4f", pair, decision.stop_loss_price)
            except Exception as exc:
                logger.error("Failed to place stop loss for %s: %s", pair, exc)

        if decision.take_profit_price:
            try:
                self.trader.place_order(
                    pair=pair,
                    type=protective_type,
                    ordertype="take-profit",
                    volume=volume,
                    price=decision.take_profit_price,
                    validate=False,
                )
                logger.info("🎯 Take profit submitted for %s at %.4f", pair, decision.take_profit_price)
            except Exception as exc:
                logger.error("Failed to place take profit for %s: %s", pair, exc)

    def _select_strategies(self, strategy_keys: Optional[Sequence[str]]) -> List[Any]:
        if strategy_keys:
            selected = []
            for key in strategy_keys:
                selected.append(self.strategy_manager.get_strategy(key))
            return selected
        return self.strategy_manager.get_active_strategies()

    def _extract_pairs(self, parameters: Dict[str, Any]) -> List[str]:
        pairs = parameters.get("pairs") or parameters.get("symbols") or []
        if isinstance(pairs, str):
            pairs = [item.strip() for item in pairs.split(",") if item.strip()]
        if not pairs:
            pairs = ["ETHUSD"]
        return pairs

    def _fetch_ohlcv(self, pair: str, interval: int) -> Optional[pd.DataFrame]:
        try:
            response = self.trader.api_client.get_ohlc_data(pair, interval=interval)
        except Exception as exc:
            logger.error("Failed to fetch OHLCV for %s: %s", pair, exc)
            return None

        result = response.get("result", {})
        if not result:
            logger.warning("No OHLCV result payload for %s.", pair)
            return None

        ohlc_data, resolved_key = self._resolve_ohlc_payload(pair, result)
        if ohlc_data is None:
            sample_keys = [key for key in result.keys() if key != "last"][:5]
            logger.warning(
                "No OHLCV data returned for %s. Available keys: %s",
                pair,
                sample_keys or "none",
            )
            return None

        df = pd.DataFrame(
            ohlc_data,
            columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"],
        )
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        for column in ["open", "high", "low", "close", "vwap", "volume"]:
            df[column] = df[column].astype(float)
        logger.debug("Loaded OHLCV data for %s via key %s (%d rows).", pair, resolved_key, len(df))
        return df

    def _resolve_ohlc_payload(
        self,
        requested_pair: str,
        result: Dict[str, Any],
    ) -> Tuple[Optional[Iterable[Any]], Optional[str]]:
        """Locate the OHLC payload for the requested pair within the API result."""
        sanitized = {key: value for key, value in result.items() if key != "last"}
        if not sanitized:
            return None, None

        target_normalized = self._normalize_pair_key(requested_pair)
        candidates = self._candidate_pair_keys(requested_pair)
        for candidate in candidates:
            payload = sanitized.get(candidate)
            if not payload:
                continue
            if self._normalize_pair_key(candidate) == target_normalized:
                return payload, candidate
        for key, payload in sanitized.items():
            if not payload:
                continue
            if self._normalize_pair_key(key) == target_normalized:
                return payload, key
        return None, None

    @classmethod
    def _normalize_pair_key(cls, pair_key: str) -> str:
        """Normalize Kraken pair identifiers (e.g., XETHZUSD -> ETHUSD)."""
        key = pair_key.upper()
        if len(key) < 6:
            return key
        base, quote = cls._split_pair_components(key)
        normalized_base = TradingEngine._normalize_asset_code(base)
        normalized_quote = TradingEngine._normalize_asset_code(quote)
        return f"{normalized_base}{normalized_quote}"

    @staticmethod
    def _normalize_asset_code(code: str) -> str:
        """Strip Kraken-specific leading prefixes without harming native symbols."""
        normalized = code.upper()
        while normalized.startswith(("X", "Z")) and len(normalized) > 3:
            normalized = normalized[1:]
        return normalized

    def _candidate_pair_keys(self, pair: str) -> List[str]:
        """Return likely Kraken result keys for a requested trading pair."""
        pair_upper = pair.upper()
        base, quote = self._split_pair_components(pair_upper)
        base_variants = self._expand_base_variants(base)
        quote_variants = self._expand_quote_variants(quote)

        candidates: List[str] = []
        for base_candidate in base_variants:
            for quote_candidate in quote_variants:
                candidates.append(f"{base_candidate}{quote_candidate}")

        if pair_upper not in candidates:
            candidates.insert(0, pair_upper)

        return self._dedupe_preserve_order(candidates)

    @classmethod
    def _split_pair_components(cls, pair: str) -> Tuple[str, str]:
        """Split a pair string into base and quote components, honouring Kraken prefixes."""
        upper = pair.upper()
        for suffix in sorted(cls._KNOWN_QUOTE_SUFFIXES, key=len, reverse=True):
            if upper.endswith(suffix):
                base = upper[: -len(suffix)]
                if base:
                    return base, suffix
        # Fallback: assume last 3 characters form the quote
        return upper[:-3], upper[-3:]

    @staticmethod
    def _expand_base_variants(base: str) -> List[str]:
        """Produce base asset variants including common Kraken prefixes."""
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
            variants.extend(
                [
                    trimmed,
                    f"X{trimmed}",
                    f"Z{trimmed}",
                ]
            )
        return TradingEngine._dedupe_preserve_order(variants)

    @staticmethod
    def _expand_quote_variants(quote: str) -> List[str]:
        """Produce quote asset variants including Kraken prefixes."""
        quote_upper = quote.upper()
        variants = [
            quote_upper,
            f"Z{quote_upper}",
        ]
        if quote_upper.startswith(("X", "Z")) and len(quote_upper) > 3:
            trimmed = quote_upper[1:]
            variants.extend(
                [
                    trimmed,
                    f"Z{trimmed}",
                ]
            )
        return TradingEngine._dedupe_preserve_order(variants)

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        """Remove duplicates while preserving original order."""
        seen: set[str] = set()
        result: List[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _should_stop(self) -> bool:
        if self._stop_event.is_set():
            return True
        if self.stop_flag_file.exists():
            return True
        return False

    def _persist_status(self) -> None:
        try:
            with self.status_file.open("w", encoding="utf-8") as handle:
                json.dump(self._status.to_dict(), handle, indent=2)
        except OSError as exc:
            logger.error("Unable to persist engine status: %s", exc)

    def _persist_stop_flag(self) -> None:
        try:
            self.stop_flag_file.write_text("stop", encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to create stop flag: %s", exc)

    def _clear_stop_flag(self) -> None:
        try:
            if self.stop_flag_file.exists():
                self.stop_flag_file.unlink()
        except OSError as exc:
            logger.error("Failed to remove stop flag: %s", exc)

    def status(self) -> TradingEngineStatus:
        """Return the most recent status payload, reading from disk if necessary."""
        if self.status_file.exists():
            try:
                payload = json.loads(self.status_file.read_text(encoding="utf-8"))
                self._status = TradingEngineStatus.from_dict(payload)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to read engine status: %s", exc)
        return self._status

    def _send_alert(
        self,
        event: str,
        message: str,
        *,
        severity: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
        cooldown: Optional[float] = None,
    ) -> None:
        """Helper to forward alerts to the configured manager when available."""
        if self.alert_manager is None:
            return
        self.alert_manager.send(
            event=event,
            message=message,
            severity=severity,
            details=details,
            cooldown=cooldown,
        )
