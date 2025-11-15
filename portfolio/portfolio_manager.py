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
        self._asset_pairs_loaded: bool = False
        self._asset_pairs_by_key: Dict[Tuple[str, str], List[str]] = {}
        self._known_pair_identifiers: Set[str] = set()
        self._pair_display_cache: Dict[Tuple[str, str], str] = {}

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

    def _load_asset_pairs(self) -> None:
        """Fetch tradable asset pairs and index by normalised base/quote."""
        if self._asset_pairs_loaded:
            return

        try:
            response = self.api_client.get_asset_pairs()
        except Exception as exc:
            logger.debug("Failed to load asset pairs: %s", exc)
            self._asset_pairs_loaded = True
            return

        pairs = response.get('result', {}) if isinstance(response, dict) else {}
        for pair_name, payload in pairs.items():
            if not isinstance(payload, dict):
                continue

            base_code = str(payload.get('base', '')).upper()
            quote_code = str(payload.get('quote', '')).upper()
            if not base_code or not quote_code:
                continue

            base_norm = self._normalize_asset_symbol(base_code)
            quote_norm = self._normalize_asset_symbol(quote_code)
            key = (base_norm, quote_norm)
            bucket = self._asset_pairs_by_key.setdefault(key, [])

            names: List[str] = []
            altname = payload.get('altname')
            wsname = payload.get('wsname')

            if pair_name:
                names.append(str(pair_name).upper())
            if altname:
                names.append(str(altname).upper())
            if wsname:
                names.append(str(wsname).upper())
            names.append(f"{base_code}/{quote_code}")

            deduped = self._dedupe_preserve_order(names)
            bucket[:] = deduped
            self._known_pair_identifiers.update(deduped)

            display_value = wsname or altname or pair_name
            if display_value:
                self._pair_display_cache[key] = str(display_value)

        self._asset_pairs_loaded = True

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
        self._asset_pairs_loaded = False
        self._asset_pairs_by_key.clear()
        self._known_pair_identifiers.clear()
        self._pair_display_cache.clear()

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
        """Generate candidate Kraken pair identifiers for price lookups and fee calls."""
        base_upper = (base or "").upper()
        quote_upper = (quote or "").upper()

        self._load_asset_pairs()
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

        norm_key = (
            self._normalize_asset_symbol(base_upper),
            self._normalize_asset_symbol(quote_upper),
        )
        mapped = list(self._asset_pairs_by_key.get(norm_key, []))
        pairs = mapped[:]
        for base_candidate in base_variants:
            for quote_candidate in quote_variants:
                slash = f"{base_candidate}/{quote_candidate}"
                compact = f"{base_candidate}{quote_candidate}"
                pairs.append(slash)
                pairs.append(compact)

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

    def get_pair_display(self, asset: str, quote: str = "USD") -> Optional[str]:
        """Return a human readable pair name for the asset/quote combination."""

        self._load_asset_pairs()
        key = (
            self._normalize_asset_symbol(asset.upper()),
            self._normalize_asset_symbol(quote.upper()),
        )
        display = self._pair_display_cache.get(key)
        if display:
            return display

        pairs = self._asset_pairs_by_key.get(key, [])
        if pairs:
            return pairs[0]

        normalized_asset = self._normalize_asset_symbol(asset)
        normalized_quote = self._normalize_asset_symbol(quote)
        return f"{normalized_asset}/{normalized_quote}"
        
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
            payload_pairs: Optional[Sequence[str]]
            if candidate_pairs:
                compact: List[str] = []
                for item in candidate_pairs:
                    if not item:
                        continue
                    compact.append(item.replace('/', ''))
                payload_pairs = compact or candidate_pairs
            else:
                payload_pairs = None

            response = self.api_client.get_trade_volume(pair=payload_pairs, include_fee_info=True)
        except Exception as exc:
            logger.debug("Failed to fetch trade volume for fee status: %s", exc)
            return {}

        if not isinstance(response, dict):
            return {}

        result = response.get('result', {}) if isinstance(response.get('result'), dict) else {}

        currency = result.get('currency')
        volume = self._to_float(result.get('volume'))

        fees_dict = result.get('fees') if isinstance(result.get('fees'), dict) else {}
        maker_dict = result.get('fees_maker') if isinstance(result.get('fees_maker'), dict) else {}

        pair_key: Optional[str] = None
        taker_entry: Optional[Dict[str, Any]] = None
        for key, entry in fees_dict.items():
            if isinstance(entry, dict):
                pair_key = key
                taker_entry = entry
                break

        maker_entry: Optional[Dict[str, Any]] = None
        if pair_key and isinstance(maker_dict.get(pair_key), dict):
            maker_entry = maker_dict[pair_key]
        else:
            for entry in maker_dict.values():
                if isinstance(entry, dict):
                    maker_entry = entry
                    break
        if maker_entry is None:
            maker_entry = taker_entry

        maker_fee = self._to_float(maker_entry.get('fee')) if maker_entry else None
        taker_fee = self._to_float(taker_entry.get('fee')) if taker_entry else None
        next_fee = self._to_float(taker_entry.get('nextfee')) if taker_entry else None
        next_volume = self._to_float(taker_entry.get('nextvolume')) if taker_entry else None
        tier_volume = self._to_float(taker_entry.get('tiervolume')) if taker_entry else None

        if pair_key and '/' not in pair_key and len(pair_key) >= 6:
            pair_key = f"{pair_key[:-4]}/{pair_key[-4:]}"

        return {
            'currency': currency,
            'thirty_day_volume': volume,
            'pair': pair_key or ','.join(candidate_pairs) if candidate_pairs else None,
            'maker_fee': maker_fee,
            'taker_fee': taker_fee,
            'next_fee': next_fee,
            'next_volume': next_volume,
            'tier_volume': tier_volume,
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
