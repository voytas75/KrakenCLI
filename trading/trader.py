"""
Trading functionality for Kraken API.

Updates: v0.9.4 - 2025-11-12 - Added cache refresh helper for order and ledger data.
Updates: v0.9.7 - 2025-11-13 - Normalised balance validation for Kraken-prefixed asset codes.
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
from api.kraken_client import KrakenAPIClient

logger = logging.getLogger(__name__)


class Trader:
    """Handles trading operations for Kraken exchange"""

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

    def __init__(self, api_client: KrakenAPIClient):
        self.api_client = api_client

    @classmethod
    def _split_pair(cls, pair: str) -> Tuple[str, str]:
        """Return raw base/quote assets for a Kraken trading pair."""

        upper_pair = (pair or "").upper()
        for quote in cls._KNOWN_QUOTE_SUFFIXES:
            if upper_pair.endswith(quote) and len(upper_pair) > len(quote):
                base = upper_pair[: -len(quote)]
                return base, quote

        if len(upper_pair) >= 6:
            return upper_pair[:3], upper_pair[3:]

        return upper_pair, ""

    @staticmethod
    def _candidate_balance_keys(asset: str) -> List[str]:
        """Return possible balance dictionary keys for a Kraken asset code."""

        variants: List[str] = []
        if not asset:
            return variants

        normalized = asset.upper()
        variants.append(normalized)

        stripped = normalized
        while stripped.startswith(("X", "Z")) and len(stripped) > 3:
            stripped = stripped[1:]
            variants.extend([stripped, f"X{stripped}", f"Z{stripped}"])

        seen: Dict[str, None] = {}
        for candidate in variants:
            if candidate and candidate not in seen:
                seen[candidate] = None
        return list(seen.keys())

    def refresh_state(self) -> None:
        """Clear cached Kraken responses to ensure up-to-date trading state."""

        clear_orders = getattr(self.api_client, "clear_open_orders_cache", None)
        if callable(clear_orders):
            clear_orders()

        clear_ledgers = getattr(self.api_client, "clear_ledgers_cache", None)
        if callable(clear_ledgers):
            clear_ledgers()

    def place_order(
        self,
        pair: str,
        type: str,
        ordertype: str,
        volume: float,
        price: Optional[float] = None,
        price2: Optional[float] = None,
        leverage: Optional[str] = None,
        userref: Optional[int] = None,
        validate: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Place a new order
        
        Args:
            pair: Trading pair (e.g., 'XBTUSD')
            type: Order type ('buy' or 'sell')
            ordertype: Order type ('market', 'limit', 'stop-loss', 'take-profit')
            volume: Order volume
            price: Price for limit orders
            price2: Secondary price for stop-loss/take-profit orders
            leverage: Leverage (optional)
            userref: User reference ID (optional)
            validate: When True, perform a dry-run validation without execution
        
        Returns:
            Order result dictionary or None if failed
        """
        try:
            # Validate inputs
            self._validate_order_params(pair, type, ordertype, volume, price, price2)
            
            action = "Validating" if validate else "Executing"
            logger.info(f"{action} {type} order for {pair}: {volume} @ {price or 'market'}")
            
            # Place the order
            result = self.api_client.add_order(
                pair=pair,
                type_=type,
                ordertype=ordertype,
                volume=volume,
                price=price,
                price2=price2,
                leverage=leverage,
                userref=userref,
                validate=validate
            )
            
            if result and 'result' in result:
                order_id = result['result'].get('txid', ['Unknown'])[0]
                logger.info(f"Order {('validated' if validate else 'executed')} successfully: {order_id}")
                return result
            
            logger.error("Order placement failed - no result data")
            return None
            
        except Exception as e:
            logger.error(f"Failed to place order: {str(e)}")
            raise
    
    def cancel_order(self, txid: str) -> bool:
        """Cancel a specific order"""
        try:
            logger.info(f"Cancelling order: {txid}")
            result = self.api_client.cancel_order(txid)
            
            if result and 'result' in result:
                count = result['result'].get('count', 0)
                if count > 0:
                    logger.info(f"Order {txid} cancelled successfully")
                    return True
                else:
                    logger.warning(f"Order {txid} not found or already cancelled")
                    return False
            
            logger.error("Cancel order failed - no result data")
            return False
            
        except Exception as e:
            logger.error(f"Failed to cancel order {txid}: {str(e)}")
            raise
    
    def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        try:
            logger.info("Cancelling all open orders")
            result = self.api_client.cancel_all_orders()
            
            if result and 'result' in result:
                count = result['result'].get('count', 0)
                logger.info(f"Cancelled {count} orders")
                return True
            
            logger.error("Cancel all orders failed - no result data")
            return False
            
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {str(e)}")
            raise
    
    def get_market_data(self, pair: str) -> Optional[Dict[str, Any]]:
        """Get current market data for a trading pair"""
        try:
            ticker = self.api_client.get_ticker(pair)
            if ticker and 'result' in ticker:
                return ticker['result'].get(pair)
            return None
        except Exception as e:
            logger.error(f"Failed to get market data for {pair}: {str(e)}")
            return None
    
    def get_order_book(self, pair: str, count: int = 50) -> Optional[Dict[str, Any]]:
        """Get order book for a trading pair"""
        try:
            order_book = self.api_client.get_order_book(pair, count)
            if order_book and 'result' in order_book:
                return order_book['result'].get(pair)
            return None
        except Exception as e:
            logger.error(f"Failed to get order book for {pair}: {str(e)}")
            return None
    
    def calculate_order_value(self, pair: str, volume: float, 
                             price: Optional[float] = None) -> Optional[float]:
        """Calculate the estimated value of an order"""
        try:
            if price:
                return volume * price
            
            # If no price provided, get current market price
            market_data = self.get_market_data(pair)
            if market_data and 'c' in market_data:
                current_price = float(market_data['c'][0])
                return volume * current_price
            
            return None
        except Exception as e:
            logger.error(f"Failed to calculate order value: {str(e)}")
            return None
    
    def validate_sufficient_balance(self, pair: str, type: str, 
                                  volume: float, price: Optional[float] = None) -> bool:
        """Check if account has sufficient balance for the order"""
        try:
            balance = self.api_client.get_account_balance()
            if not balance or 'result' not in balance:
                return False

            balance_data = balance['result']
            base_asset, quote_asset = self._split_pair(pair)

            if type == 'buy':
                required_amount = self.calculate_order_value(pair, volume, price)
                if required_amount is None:
                    return False

                for candidate in self._candidate_balance_keys(quote_asset):
                    available = balance_data.get(candidate)
                    if available is None:
                        continue
                    try:
                        if float(available) >= required_amount:
                            return True
                    except (TypeError, ValueError):
                        continue
                return False

            if type == 'sell':
                for candidate in self._candidate_balance_keys(base_asset):
                    available = balance_data.get(candidate)
                    if available is None:
                        continue
                    try:
                        if float(available) >= volume:
                            return True
                    except (TypeError, ValueError):
                        continue
                return False

            return False

        except Exception as e:
            logger.error(f"Failed to validate balance: {str(e)}")
            return False
    
    def _validate_order_params(self, pair: str, type: str, ordertype: str,
                             volume: float, price: Optional[float], 
                             price2: Optional[float]) -> None:
        """Validate order parameters"""
        valid_types = ['buy', 'sell']
        valid_ordertypes = ['market', 'limit', 'stop-loss', 'take-profit']
        
        if type not in valid_types:
            raise ValueError(f"Invalid order type: {type}. Must be one of {valid_types}")
        
        if ordertype not in valid_ordertypes:
            raise ValueError(f"Invalid order type: {ordertype}. Must be one of {valid_ordertypes}")
        
        if volume <= 0:
            raise ValueError("Order volume must be positive")
        
        # Price validation
        if ordertype in ['limit', 'take-profit'] and (not price or price <= 0):
            raise ValueError(f"Price required and must be positive for {ordertype} orders")
        
        if ordertype in ['stop-loss', 'take-profit'] and (not price2 or price2 <= 0):
            raise ValueError(f"Secondary price required and must be positive for {ordertype} orders")
        
        # Basic pair validation
        if len(pair) < 6:
            raise ValueError(f"Invalid trading pair: {pair}")
    
    def estimate_fees(self, pair: str, volume: float, ordertype: str) -> Dict[str, float]:
        """Estimate trading fees (simplified calculation)"""
        # This is a simplified fee calculation
        # Actual fees depend on 30-day volume and account tier
        base_fee_rate = 0.0026  # 0.26% base fee for most users
        
        try:
            trade_value = self.calculate_order_value(pair, volume)
            if trade_value:
                estimated_fee = trade_value * base_fee_rate
                return {
                    'fee_rate': base_fee_rate,
                    'estimated_fee': estimated_fee,
                    'trade_value': trade_value
                }
        except Exception as e:
            logger.error(f"Failed to estimate fees: {str(e)}")
        
        return {
            'fee_rate': base_fee_rate,
            'estimated_fee': 0,
            'trade_value': 0
        }
