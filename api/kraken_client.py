"""
Kraken API Client
Official Kraken exchange API wrapper with authentication

Updates: v0.9.4 - 2025-11-12 - Added caching plus withdrawal and export endpoint helpers.
"""

import copy
import time
import hmac
import hashlib
import base64
import urllib.parse
import json
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional, Sequence, Tuple, Union
import requests
from config import Config


@dataclass(slots=True)
class _CacheEntry:
    """Container storing cached Kraken payloads with timestamp metadata."""

    payload: Dict[str, Any]
    timestamp: float


class KrakenAPIClient:
    """Kraken API client with proper authentication and error handling."""

    _ORDER_CACHE_TTL: float = 2.0
    _LEDGER_CACHE_TTL: float = 5.0

    def __init__(self, api_key: str, api_secret: str, sandbox: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = Config()
        self.base_url = self.config.get_api_url()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Kraken Pro CLI/1.0.0'
        })
        self._cache_lock = Lock()
        self._orders_cache: Optional[_CacheEntry] = None
        self._ledgers_cache: Dict[Tuple[Any, ...], _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_is_valid(self, entry: Optional[_CacheEntry], ttl: float) -> bool:
        """Return True when the cache entry is still within the TTL window."""

        if entry is None:
            return False
        return (time.monotonic() - entry.timestamp) < ttl

    def _get_cached_orders(self) -> Optional[Dict[str, Any]]:
        """Return a copy of cached open orders when still valid."""

        with self._cache_lock:
            if self._cache_is_valid(self._orders_cache, self._ORDER_CACHE_TTL):
                return copy.deepcopy(self._orders_cache.payload)
            self._orders_cache = None
        return None

    def _set_orders_cache(self, payload: Dict[str, Any]) -> None:
        """Persist a deep copy of the payload inside the order cache."""

        cached_payload = copy.deepcopy(payload)
        with self._cache_lock:
            self._orders_cache = _CacheEntry(payload=cached_payload, timestamp=time.monotonic())

    def _invalidate_orders_cache(self) -> None:
        """Clear any cached open orders state."""

        with self._cache_lock:
            self._orders_cache = None

    def _ledger_cache_key(
        self,
        assets: Optional[str],
        ledger_type: Optional[str],
        start: Optional[str],
        end: Optional[str],
        ofs: int,
    ) -> Tuple[Any, ...]:
        """Generate a unique cache key for ledger lookups."""

        return (assets or "", ledger_type or "", start or "", end or "", int(ofs))

    def _get_cached_ledgers(self, key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        """Return cached ledger data for the provided key when valid."""

        with self._cache_lock:
            entry = self._ledgers_cache.get(key)
            if entry and self._cache_is_valid(entry, self._LEDGER_CACHE_TTL):
                return copy.deepcopy(entry.payload)
            if entry:
                del self._ledgers_cache[key]
        return None

    def _set_ledgers_cache(self, key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
        """Persist a deep copy of the payload inside the ledger cache for the key."""

        cached_payload = copy.deepcopy(payload)
        with self._cache_lock:
            self._ledgers_cache[key] = _CacheEntry(payload=cached_payload, timestamp=time.monotonic())

    def _clear_ledgers_cache(self) -> None:
        """Remove all cached ledger records."""

        with self._cache_lock:
            self._ledgers_cache.clear()

    # ------------------------------------------------------------------
    # Cache management public helpers
    # ------------------------------------------------------------------

    def clear_open_orders_cache(self) -> None:
        """Public helper to clear cached open order payloads."""

        self._invalidate_orders_cache()

    def clear_ledgers_cache(self) -> None:
        """Public helper to clear cached ledger payloads."""

        self._clear_ledgers_cache()

    @staticmethod
    def _normalise_assets_input(assets: Optional[Union[str, Sequence[str]]]) -> Optional[str]:
        """Normalise asset filters to the comma-separated format required by Kraken."""

        if assets is None:
            return None
        if isinstance(assets, str):
            return assets

        filtered = [asset for asset in assets if asset]
        if not filtered:
            return None

        return ",".join(dict.fromkeys(filtered))
        
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
            self.rate_limit_delay()
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
        
        result = self._make_request("private/AddOrder", data, auth_required=True)

        if not validate:
            self._invalidate_orders_cache()
            self._clear_ledgers_cache()

        return result
    
    def cancel_order(self, txid: str) -> Dict[str, Any]:
        """Cancel an order"""
        data = {'txid': txid}
        result = self._make_request("private/CancelOrder", data, auth_required=True)
        self._invalidate_orders_cache()
        self._clear_ledgers_cache()
        return result
    
    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders"""
        result = self._make_request("private/CancelAll", auth_required=True)
        self._invalidate_orders_cache()
        self._clear_ledgers_cache()
        return result
    
    def get_open_orders(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get open orders with optional cached response reuse."""

        if force_refresh:
            self._invalidate_orders_cache()
        else:
            cached = self._get_cached_orders()
            if cached is not None:
                return cached

        result = self._make_request("private/OpenOrders", auth_required=True)
        self._set_orders_cache(result)
        return result
    
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

    def get_ledgers(
        self,
        assets: Optional[Union[str, Sequence[str]]] = None,
        ledger_type: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        ofs: int = 0,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Get ledger information with configurable caching and filters."""

        normalised_assets = self._normalise_assets_input(assets)
        cache_key = self._ledger_cache_key(normalised_assets, ledger_type, start, end, ofs)

        if force_refresh:
            with self._cache_lock:
                self._ledgers_cache.pop(cache_key, None)
        elif use_cache:
            cached = self._get_cached_ledgers(cache_key)
            if cached is not None:
                return cached

        data: Dict[str, Any] = {'ofs': str(ofs)}
        if normalised_assets:
            data['asset'] = normalised_assets
        if ledger_type:
            data['type'] = ledger_type
        if start:
            data['start'] = start
        if end:
            data['end'] = end

        result = self._make_request("private/Ledgers", data, auth_required=True)

        if use_cache or force_refresh:
            self._set_ledgers_cache(cache_key, result)

        return result

    def request_withdrawal(
        self,
        asset: str,
        key: str,
        amount: Union[float, str],
        address: Optional[str] = None,
        otp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a withdrawal request and clear affected caches."""

        data: Dict[str, Any] = {
            'asset': asset,
            'key': key,
            'amount': str(amount),
        }
        if address:
            data['address'] = address
        if otp:
            data['otp'] = otp

        result = self._make_request("private/Withdraw", data=data, auth_required=True)
        self._clear_ledgers_cache()
        return result

    def get_withdraw_status(
        self,
        asset: str,
        method: Optional[str] = None,
        start: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the status for recent withdrawal requests."""

        data: Dict[str, Any] = {'asset': asset}
        if method:
            data['method'] = method
        if start:
            data['start'] = start

        return self._make_request("private/WithdrawStatus", data=data, auth_required=True)

    def cancel_withdrawal(self, asset: str, refid: str) -> Dict[str, Any]:
        """Attempt to cancel a pending withdrawal and refresh ledger caches."""

        data = {'asset': asset, 'refid': refid}
        result = self._make_request("private/WithdrawCancel", data=data, auth_required=True)
        self._clear_ledgers_cache()
        return result

    def request_export(
        self,
        report: str,
        description: str,
        export_format: str = "CSV",
        fields: Optional[Sequence[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an asynchronous report export job."""

        data: Dict[str, Any] = {
            'report': report,
            'description': description,
            'format': export_format.upper(),
        }
        if fields:
            data['fields'] = ",".join(dict.fromkeys(fields))
        if start:
            data['starttm'] = start
        if end:
            data['endtm'] = end

        return self._make_request("private/AddExport", data=data, auth_required=True)

    def get_export_status(self, report: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve status for export jobs; optionally filter by report type."""

        data: Optional[Dict[str, Any]] = None
        if report:
            data = {'report': report}

        return self._make_request("private/ExportStatus", data=data, auth_required=True)

    def retrieve_export(self, report_id: str) -> Dict[str, Any]:
        """Download a completed export archive reference."""

        data = {'id': report_id}
        return self._make_request("private/RetrieveExport", data=data, auth_required=True)

    def delete_export(self, report_id: str) -> Dict[str, Any]:
        """Delete a completed export job from Kraken servers."""

        data = {'id': report_id}
        return self._make_request("private/DeleteExport", data=data, auth_required=True)
    
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
