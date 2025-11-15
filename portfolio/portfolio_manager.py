"""
Portfolio management for Kraken trading.

Updates: v0.9.4 - 2025-11-12 - Added cache refresh helpers for order and ledger data.
"""

import logging
from typing import Dict, Any, List, Optional, Sequence, Set
from api.kraken_client import KrakenAPIClient

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Handles portfolio operations for Kraken exchange"""
    
    def __init__(self, api_client: KrakenAPIClient):
        self.api_client = api_client
        self._asset_info_loaded: bool = False
        self._asset_altname_map: Dict[str, str] = {}
        self._asset_price_by_symbol: Dict[str, Optional[float]] = {}
        self._price_cache: Dict[str, Optional[float]] = {}
        self._failed_price_assets: Set[str] = set()

    def _load_asset_metadata(self) -> None:
        """Load asset metadata and cache alt names for price lookups."""
        if self._asset_info_loaded:
            return
        try:
            response = self.api_client.get_asset_info()
            assets = response.get('result', {}) if isinstance(response, dict) else {}
            for asset_code, info in assets.items():
                altname = info.get('altname') if isinstance(info, dict) else None
                if altname:
                    self._asset_altname_map[asset_code.upper()] = altname.upper()
        except Exception as exc:
            logger.debug("Failed to load asset metadata: %s", exc)
        finally:
            self._asset_info_loaded = True

    def refresh_portfolio(self) -> None:
        """Invalidate cached Kraken responses and local price caches."""

        clear_orders = getattr(self.api_client, "clear_open_orders_cache", None)
        if callable(clear_orders):
            clear_orders()

        clear_ledgers = getattr(self.api_client, "clear_ledgers_cache", None)
        if callable(clear_ledgers):
            clear_ledgers()

        self._asset_price_by_symbol.clear()
        self._price_cache.clear()
        self._failed_price_assets.clear()

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _strip_suffixes(asset: str) -> str:
        """Remove common Kraken suffixes such as .S or .F."""
        normalized = asset.split('.')[0]
        return normalized

    def _normalize_asset_symbol(self, asset: str) -> str:
        """Normalize Kraken asset codes to their spot trading symbol."""
        asset_upper = (asset or "").upper()
        self._load_asset_metadata()

        # Prefer metadata altname if available
        if asset_upper in self._asset_altname_map:
            normalized = self._asset_altname_map[asset_upper]
        else:
            normalized = asset_upper

        normalized = self._strip_suffixes(normalized)

        # Manual overrides for common staked/future asset codes
        overrides = {
            "ADA.S": "ADA",
            "ADA.F": "ADA",
            "DOT.S": "DOT",
            "DOT.F": "DOT",
            "ETH.F": "ETH",
            "ETH.S": "ETH",
            "ETHW": "ETHW",
            "XXDG": "XDG",
        }
        if asset_upper in overrides:
            normalized = overrides[asset_upper]

        # Remove Kraken-specific leading prefixes (X/Z) for spot assets
        while normalized.startswith(('X', 'Z')) and len(normalized) > 3:
            normalized = normalized[1:]

        return normalized

    @staticmethod
    def _dedupe_preserve_order(values: List[str]) -> List[str]:
        """Remove duplicates while preserving order."""
        seen: Set[str] = set()
        result: List[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result

    def _build_price_pairs(self, base: str, quote: str = "USD") -> List[str]:
        """Generate candidate Kraken pair identifiers for price lookups."""
        base_upper = (base or "").upper()
        quote_upper = (quote or "").upper()

        core_base = self._strip_suffixes(base_upper)
        base_variants = [
            core_base,
            f"X{core_base}",
            f"Z{core_base}",
            f"XX{core_base}",
            base_upper,
            f"X{base_upper}",
            f"Z{base_upper}",
        ]

        # Include trimmed prefix variations (e.g., XXDG -> XDG)
        if base_upper.startswith(('X', 'Z')) and len(base_upper) > 3:
            trimmed = base_upper[1:]
            base_variants.extend([
                trimmed,
                f"X{trimmed}",
                f"Z{trimmed}",
            ])

        quote_variants = [
            quote_upper,
            f"Z{quote_upper}",
        ]

        pairs = []
        for base_candidate in base_variants:
            for quote_candidate in quote_variants:
                pairs.append(f"{base_candidate}{quote_candidate}")

        return self._dedupe_preserve_order(pairs)

    def _get_price_for_pairs(self, candidate_pairs: List[str]) -> Optional[float]:
        """Attempt to find a USD price for the provided pair candidates."""
        for pair in candidate_pairs:
            if pair in self._price_cache:
                cached_price = self._price_cache[pair]
                if cached_price is not None:
                    return cached_price
                continue

            try:
                ticker = self.api_client.get_ticker(pair)
            except Exception as exc:
                logger.debug("Ticker lookup failed for %s: %s", pair, exc)
                self._price_cache[pair] = None
                continue

            result = ticker.get('result', {}) if isinstance(ticker, dict) else {}
            if not result:
                self._price_cache[pair] = None
                continue

            for key, payload in result.items():
                close_values = payload.get('c') if isinstance(payload, dict) else None
                if close_values and close_values[0]:
                    try:
                        close_price = float(close_values[0])
                    except (ValueError, TypeError):
                        continue
                    self._price_cache[key] = close_price
                    self._price_cache[pair] = close_price
                    return close_price

            self._price_cache[pair] = None

        return None
        
    def get_balances(self) -> Dict[str, str]:
        """Get all account balances"""
        try:
            result = self.api_client.get_account_balance()
            if result and 'result' in result:
                return result['result']
            return {}
        except Exception as e:
            logger.error(f"Failed to get balances: {str(e)}")
            return {}
    
    def get_trade_balance(self, asset: str = "ZUSD") -> Optional[Dict[str, Any]]:
        """Get trade balance in specified asset"""
        try:
            result = self.api_client.get_trade_balance(asset)
            if result and 'result' in result:
                return result['result']
            return None
        except Exception as e:
            logger.error(f"Failed to get trade balance: {str(e)}")
            return None
    
    def get_open_orders(self, refresh: bool = False) -> Dict[str, Any]:
        """Get all open orders, optionally forcing an API refresh."""
        try:
            result = self.api_client.get_open_orders(force_refresh=refresh)
            if result and 'result' in result:
                return result['result']
            return {}
        except Exception as e:
            logger.error(f"Failed to get open orders: {str(e)}")
            return {}
    
    def get_open_positions(self) -> Dict[str, Any]:
        """Get all open positions"""
        try:
            result = self.api_client.get_open_positions()
            if result and 'result' in result:
                return result['result']
            return {}
        except Exception as e:
            logger.error(f"Failed to get open positions: {str(e)}")
            return {}
    
    def get_trade_history(self, limit: int = 50, start: Optional[str] = None, 
                         end: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get trade history"""
        try:
            result = self.api_client.get_trade_history(trades=True, start=start, end=end)
            if result and 'result' in result:
                trades = result['result'].get('trades', {})
                # Convert dict to list and limit results
                trade_list = list(trades.values())
                return trade_list[:limit]
            return []
        except Exception as e:
            logger.error(f"Failed to get trade history: {str(e)}")
            return []
    
    def get_closed_orders(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get closed orders"""
        try:
            result = self.api_client.get_closed_orders(trades=True)
            if result and 'result' in result:
                orders = result['result'].get('closed', {})
                # Convert dict to list and limit results
                order_list = list(orders.values())
                return order_list[:limit]
            return []
        except Exception as e:
            logger.error(f"Failed to get closed orders: {str(e)}")
            return []
    
    def get_usd_value(self, asset: str, amount: float) -> Optional[float]:
        """Convert asset amount to USD value."""
        try:
            amount_float = float(amount)
        except (ValueError, TypeError):
            logger.debug("Invalid amount for %s: %s", asset, amount)
            return None

        if amount_float == 0:
            return 0.0

        asset_upper = (asset or "").upper()
        if asset_upper in {"USD", "ZUSD"}:
            return amount_float

        normalized_symbol = self._normalize_asset_symbol(asset_upper)

        if normalized_symbol in self._asset_price_by_symbol:
            price = self._asset_price_by_symbol[normalized_symbol]
        else:
            candidate_pairs = self._build_price_pairs(normalized_symbol)
            price = self._get_price_for_pairs(candidate_pairs)
            self._asset_price_by_symbol[normalized_symbol] = price

        if price is None:
            if asset_upper not in self._failed_price_assets:
                logger.warning("Could not get USD value for %s", asset_upper)
                self._failed_price_assets.add(asset_upper)
            return None

        return amount_float * price
    
    def get_total_usd_value(self) -> Optional[float]:
        """Calculate total portfolio value in USD"""
        try:
            balances = self.get_balances()
            total_value = 0.0
            
            for asset, amount_str in balances.items():
                try:
                    amount = float(amount_str)
                except (ValueError, TypeError):
                    continue
                if amount <= 0:
                    continue
                usd_value = self.get_usd_value(asset, amount)
                if usd_value is not None:
                    total_value += usd_value
            
            return total_value
        except Exception as e:
            logger.error(f"Failed to calculate total USD value: {str(e)}")
            return None
    
    def get_portfolio_summary(self, refresh: bool = False) -> Dict[str, Any]:
        """Get comprehensive portfolio summary."""

        if refresh:
            self.refresh_portfolio()
        try:
            balances = self.get_balances()
            positions = self.get_open_positions()
            orders = self.get_open_orders(refresh=refresh)
            total_value = 0.0
            pair_candidates: List[str] = []
            
            # Count significant assets
            significant_assets = []
            missing_valuations: List[str] = []
            for asset, amount_str in balances.items():
                try:
                    amount = float(amount_str)
                except (ValueError, TypeError):
                    continue
                if amount <= 0:
                    continue

                usd_value = self.get_usd_value(asset, amount)
                if usd_value is None:
                    missing_valuations.append(asset)
                else:
                    total_value += usd_value

                normalized_asset = self._normalize_asset_symbol(asset)
                candidate_pairs = self._build_price_pairs(normalized_asset)
                if candidate_pairs:
                    pair_candidates.extend(candidate_pairs[:3])

                significant_assets.append({
                    'asset': asset,
                    'amount': amount,
                    'usd_value': usd_value,
                })
            
            # Sort by USD value
            significant_assets.sort(
                key=lambda x: x['usd_value'] if x['usd_value'] is not None else 0.0,
                reverse=True
            )
            
            total_usd_value = total_value if significant_assets else None

            unique_pairs = self._dedupe_preserve_order(pair_candidates)[:10]
            if not unique_pairs:
                unique_pairs = ["XXBTZUSD"]
            fee_status = self.get_fee_status(unique_pairs)

            return {
                'total_usd_value': total_usd_value,
                'significant_assets': significant_assets,
                'open_positions_count': len(positions),
                'open_orders_count': len(orders),
                'total_assets': len(balances),
                'missing_assets': missing_valuations,
                'fee_status': fee_status,
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio summary: {str(e)}")
            return {
                'total_usd_value': None,
                'significant_assets': [],
                'open_positions_count': 0,
                'open_orders_count': 0,
                'total_assets': 0,
                'missing_assets': [],
                'fee_status': {},
            }

    def get_fee_status(self, candidate_pairs: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Return parsed 30-day volume and fee tier information."""

        try:
            response = self.api_client.get_trade_volume(pair=candidate_pairs, include_fee_info=True)
        except Exception as exc:
            logger.debug("Failed to fetch trade volume for fee status: %s", exc)
            return {}

        if not isinstance(response, dict):
            return {}

        result = response.get('result', {}) if isinstance(response.get('result'), dict) else {}

        currency = result.get('currency')
        volume = self._to_float(result.get('volume'))

        fees = result.get('fees') if isinstance(result.get('fees'), dict) else {}
        fees_maker = result.get('fees_maker') if isinstance(result.get('fees_maker'), dict) else {}

        def _first_fee_entry(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            for entry in payload.values():
                if isinstance(entry, dict):
                    return entry
            return None

        taker_entry = _first_fee_entry(fees)
        maker_entry = _first_fee_entry(fees_maker) or taker_entry

        maker_fee = self._to_float(maker_entry.get('fee')) if maker_entry else None
        taker_fee = self._to_float(taker_entry.get('fee')) if taker_entry else None
        next_fee = self._to_float(taker_entry.get('nextfee')) if taker_entry else None
        next_volume = self._to_float(taker_entry.get('nextvolume')) if taker_entry else None

        return {
            'currency': currency,
            'thirty_day_volume': volume,
            'maker_fee': maker_fee,
            'taker_fee': taker_fee,
            'next_fee': next_fee,
            'next_volume': next_volume,
        }
    
    def get_performance_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Calculate basic performance metrics"""
        try:
            # Get recent trade history
            trades = self.get_trade_history(limit=100)
            
            if not trades:
                return {
                    'total_trades': 0,
                    'profitable_trades': 0,
                    'win_rate': 0,
                    'total_volume': 0
                }
            
            profitable_trades = 0
            total_volume = 0.0
            
            for trade in trades:
                # Count as profitable if cost is positive (simplified)
                if trade.get('cost') and float(trade['cost']) > 0:
                    profitable_trades += 1
                
                # Add to volume
                if trade.get('vol'):
                    total_volume += float(trade['vol'])
            
            win_rate = (profitable_trades / len(trades)) * 100 if trades else 0
            
            return {
                'total_trades': len(trades),
                'profitable_trades': profitable_trades,
                'win_rate': win_rate,
                'total_volume': total_volume
            }
        except Exception as e:
            logger.error(f"Failed to calculate performance metrics: {str(e)}")
            return {
                'total_trades': 0,
                'profitable_trades': 0,
                'win_rate': 0,
                'total_volume': 0
            }
