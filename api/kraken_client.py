"""
Kraken API Client
Official Kraken exchange API wrapper with authentication
"""

import time
import hmac
import hashlib
import base64
import urllib.parse
import json
from typing import Dict, Any, Optional
import requests
from config import Config


class KrakenAPIClient:
    """Kraken API client with proper authentication and error handling"""
    
    def __init__(self, api_key: str, api_secret: str, sandbox: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = Config()
        self.base_url = self.config.get_api_url()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Kraken Pro CLI/1.0.0'
        })
        
    def _generate_signature(self, url_path: str, nonce: str, postdata: str) -> str:
        """
        Generate authentication signature for Kraken API (Updated for 2025)
        
        According to Kraken 2025 API documentation:
        - Message signature using HMAC-SHA512 of (URI path + SHA256(nonce + POST data))
        - Using base64 decoded secret API key
        """
        # Step 1: Calculate SHA256 of (nonce + POST data)
        sha256_hash = hashlib.sha256(nonce.encode() + postdata.encode()).digest()
        
        # Step 2: Concatenate URI path with SHA256 hash
        message = url_path.encode() + sha256_hash
        
        # Step 3: Calculate HMAC-SHA512 using decoded API secret
        signature = hmac.new(
            base64.b64decode(self.api_secret),
            message,
            hashlib.sha512
        ).digest()
        
        # Step 4: Encode result to base64
        return base64.b64encode(signature).decode()
    
    def _make_request(self, endpoint: str, data: Optional[Dict] = None, 
                     auth_required: bool = False, method: str = 'POST') -> Dict[str, Any]:
        """
        Make authenticated or public API request (Updated for 2025 API)
        
        Current API format:
        - URL: https://api.kraken.com/0/{endpoint}
        - Response: {"error": [], "result": {}}
        """
        url = f"{self.base_url}/0/{endpoint}"
        
        if auth_required:
            # Add authentication
            nonce = str(int(time.time() * 1000000))  # microsecond timestamp
            if data is None:
                data = {}
            data['nonce'] = nonce
            
            # Generate signature
            url_path = f"/0/{endpoint}"
            postdata = urllib.parse.urlencode(data)
            signature = self._generate_signature(url_path, nonce, postdata)
            
            # Set headers
            headers = {
                'API-Key': self.api_key,
                'API-Sign': signature
            }
        else:
            headers = {}
        
        try:
            if method == 'GET':
                # For GET requests, use query parameters
                response = self.session.get(
                    url,
                    params=data if data else None,
                    headers=headers,
                    timeout=self.config.get_timeout()
                )
            else:
                # For POST requests
                response = self.session.post(
                    url,
                    data=data if auth_required else None,
                    headers=headers,
                    timeout=self.config.get_timeout()
                )
            
            response.raise_for_status()
            result = response.json()
            
            # Check for API errors (2025 format: {"error": [], "result": {}})
            if 'error' in result and result['error']:
                error_messages = result['error']
                if error_messages:
                    raise Exception(f"Kraken API Error: {', '.join(error_messages)}")
                # If error array is empty but result is missing or null
                elif not result.get('result'):
                    raise Exception("Kraken API Error: No result data returned")
            
            return result
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response: {str(e)}")
        except Exception as e:
            raise Exception(f"API request failed: {str(e)}")
    
    def get_server_time(self) -> Dict[str, Any]:
        """Get server time"""
        return self._make_request("public/Time")
    
    def get_account_balance(self) -> Dict[str, Any]:
        """Get account balance"""
        return self._make_request("private/Balance", auth_required=True)
    
    def get_trade_balance(self, asset: str = "ZUSD") -> Dict[str, Any]:
        """Get trade balance"""
        data = {'asset': asset}
        return self._make_request("private/TradeBalance", data, auth_required=True)
    
    def get_ticker(self, pair: str) -> Dict[str, Any]:
        """Get ticker information"""
        data = {'pair': pair}
        return self._make_request("public/Ticker", data, method='GET')
    
    def get_ohlc_data(self, pair: str, interval: int = 60) -> Dict[str, Any]:
        """Get OHLC (candlestick) data"""
        data = {
            'pair': pair,
            'interval': interval
        }
        return self._make_request("public/OHLC", data, method='GET')
    
    def get_order_book(self, pair: str, count: int = 100) -> Dict[str, Any]:
        """Get order book data"""
        data = {
            'pair': pair,
            'count': count
        }
        return self._make_request("public/Depth", data, method='GET')
    
    def get_recent_trades(self, pair: str, since: Optional[str] = None) -> Dict[str, Any]:
        """Get recent trades"""
        data = {'pair': pair}
        if since:
            data['since'] = since
        return self._make_request("public/Trades", data, method='GET')
    
    def add_order(self, pair: str, type_: str, ordertype: str, 
                 volume: float, price: Optional[float] = None,
                 price2: Optional[float] = None, leverage: Optional[str] = None,
                 oflags: Optional[str] = None, starttm: Optional[str] = None,
                 expiretm: Optional[str] = None, userref: Optional[int] = None,
                 validate: bool = True) -> Dict[str, Any]:
        """Add a new order"""
        data = {
            'pair': pair,
            'type': type_,
            'ordertype': ordertype,
            'volume': str(volume),
            'validate': 'true' if validate else 'false'
        }
        
        if price:
            data['price'] = str(price)
        if price2:
            data['price2'] = str(price2)
        if leverage:
            data['leverage'] = leverage
        if oflags:
            data['oflags'] = oflags
        if starttm:
            data['starttm'] = starttm
        if expiretm:
            data['expiretm'] = expiretm
        if userref:
            data['userref'] = str(userref)
        
        return self._make_request("private/AddOrder", data, auth_required=True)
    
    def cancel_order(self, txid: str) -> Dict[str, Any]:
        """Cancel an order"""
        data = {'txid': txid}
        return self._make_request("private/CancelOrder", data, auth_required=True)
    
    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders"""
        return self._make_request("private/CancelAll", auth_required=True)
    
    def get_open_orders(self) -> Dict[str, Any]:
        """Get open orders"""
        return self._make_request("private/OpenOrders", auth_required=True)
    
    def get_closed_orders(self, trades: bool = False, 
                         start: Optional[str] = None, end: Optional[str] = None,
                         ofs: int = 0) -> Dict[str, Any]:
        """Get closed orders"""
        data = {
            'trades': 'true' if trades else 'false',
            'ofs': str(ofs)
        }
        if start:
            data['start'] = start
        if end:
            data['end'] = end
        
        return self._make_request("private/ClosedOrders", data, auth_required=True)
    
    def get_trade_history(self, trades: bool = True, 
                         start: Optional[str] = None, end: Optional[str] = None,
                         ofs: int = 0) -> Dict[str, Any]:
        """Get trade history"""
        data = {
            'trades': 'true' if trades else 'false',
            'ofs': str(ofs)
        }
        if start:
            data['start'] = start
        if end:
            data['end'] = end
        
        return self._make_request("private/TradesHistory", data, auth_required=True)
    
    def get_open_positions(self) -> Dict[str, Any]:
        """Get open positions"""
        return self._make_request("private/OpenPositions", auth_required=True)
    
    def get_trade_info_for_pair(self, pair: str) -> Dict[str, Any]:
        """Get trade information for a specific pair"""
        data = {'pair': pair}
        return self._make_request("public/TradeInfo", data, method='GET')
    
    def get_asset_info(self) -> Dict[str, Any]:
        """Get asset information"""
        return self._make_request("public/Assets", method='GET')
    
    def get_tradable_asset_pairs(self) -> Dict[str, Any]:
        """Get tradable asset pairs"""
        return self._make_request("public/AssetPairs", method='GET')
    
    def rate_limit_delay(self):
        """
        Implement rate limiting (Updated for 2025 API)
        
        Current limits:
        - Public endpoints: 1 request/second
        - Private endpoints: 15-20 requests/minute
        """
        time.sleep(1.2)  # Conservative delay for 2025 API compliance