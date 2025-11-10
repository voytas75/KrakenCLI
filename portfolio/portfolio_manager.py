"""
Portfolio management for Kraken trading
"""

import logging
from typing import Dict, Any, List, Optional
from api.kraken_client import KrakenAPIClient

logger = logging.getLogger(__name__)


class PortfolioManager:
    """Handles portfolio operations for Kraken exchange"""
    
    def __init__(self, api_client: KrakenAPIClient):
        self.api_client = api_client
        
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
    
    def get_open_orders(self) -> Dict[str, Any]:
        """Get all open orders"""
        try:
            result = self.api_client.get_open_orders()
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
        """Convert asset amount to USD value"""
        try:
            # For USD itself
            if asset in ['ZUSD', 'USD']:
                return amount
            
            # Try to get current price for the asset
            pairs_to_try = [f"{asset}USD", f"X{asset}USD", f"Z{asset}USD"]
            
            for pair in pairs_to_try:
                try:
                    ticker = self.api_client.get_ticker(pair)
                    if ticker and 'result' in ticker and pair in ticker['result']:
                        price_data = ticker['result'][pair]
                        if 'c' in price_data and price_data['c'][0]:
                            price = float(price_data['c'][0])
                            return amount * price
                except:
                    continue
            
            # If direct conversion failed, try using BTC as intermediate
            try:
                btc_ticker = self.api_client.get_ticker("XBTUSD")
                if btc_ticker and 'result' in btc_ticker:
                    btc_price = float(btc_ticker['result']['XXBTZUSD']['c'][0])
                    
                    # Get asset in BTC terms
                    btc_pairs = [f"{asset}XBT", f"X{asset}XBT", f"Z{asset}XBT"]
                    for pair in btc_pairs:
                        try:
                            asset_btc_ticker = self.api_client.get_ticker(pair)
                            if asset_btc_ticker and 'result' in asset_btc_ticker and pair in asset_btc_ticker['result']:
                                asset_btc_price = float(asset_btc_ticker['result'][pair]['c'][0])
                                btc_amount = amount * asset_btc_price
                                return btc_amount * btc_price
                        except:
                            continue
            except:
                pass
            
            logger.warning(f"Could not get USD value for {asset}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get USD value for {asset}: {str(e)}")
            return None
    
    def get_total_usd_value(self) -> Optional[float]:
        """Calculate total portfolio value in USD"""
        try:
            balances = self.get_balances()
            total_value = 0.0
            
            for asset, amount_str in balances.items():
                amount = float(amount_str)
                if amount > 0.001:  # Only count significant amounts
                    usd_value = self.get_usd_value(asset, amount)
                    if usd_value:
                        total_value += usd_value
            
            return total_value
        except Exception as e:
            logger.error(f"Failed to calculate total USD value: {str(e)}")
            return None
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio summary"""
        try:
            balances = self.get_balances()
            positions = self.get_open_positions()
            orders = self.get_open_orders()
            total_value = self.get_total_usd_value()
            
            # Count significant assets
            significant_assets = []
            for asset, amount_str in balances.items():
                amount = float(amount_str)
                if amount > 0.001:
                    usd_value = self.get_usd_value(asset, amount)
                    significant_assets.append({
                        'asset': asset,
                        'amount': amount,
                        'usd_value': usd_value or 0
                    })
            
            # Sort by USD value
            significant_assets.sort(key=lambda x: x['usd_value'], reverse=True)
            
            return {
                'total_usd_value': total_value,
                'significant_assets': significant_assets,
                'open_positions_count': len(positions),
                'open_orders_count': len(orders),
                'total_assets': len(balances)
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio summary: {str(e)}")
            return {
                'total_usd_value': None,
                'significant_assets': [],
                'open_positions_count': 0,
                'open_orders_count': 0,
                'total_assets': 0
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