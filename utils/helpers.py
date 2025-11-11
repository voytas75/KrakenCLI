"""
Helper utilities for Kraken CLI
"""

import locale
from typing import Union
from datetime import datetime
import pytz


def format_currency(value: Union[str, float, int], 
                   currency: str = "USD", 
                   decimals: int = 2) -> str:
    """Format currency value with proper locale formatting"""
    try:
        # Convert to float if string
        if isinstance(value, str):
            value = float(value)
        
        # Use locale formatting
        locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
        formatted = locale.format_string(f"%.{decimals}f", value, grouping=True)
        return f"{currency} {formatted}"
    except (ValueError, locale.Error):
        # Fallback to simple formatting
        try:
            return f"{currency} {float(value):,.{decimals}f}"
        except (ValueError, TypeError):
            return f"{currency} {value}"


def format_percentage(value: Union[str, float, int], decimals: int = 2) -> str:
    """Format percentage value"""
    try:
        if isinstance(value, str):
            value = float(value)
        return f"{float(value):.{decimals}f}%"
    except (ValueError, TypeError):
        return f"{value}%"


def format_volume(volume: Union[str, float, int], 
                 asset: str = "",
                 decimals: int = 8) -> str:
    """Format trading volume"""
    try:
        if isinstance(volume, str):
            volume = float(volume)
        
        # Use different precision for different assets
        if asset.upper() in ['BTC', 'XBT', 'ETH']:
            decimals = 8
        elif asset.upper() in ['USD', 'ZUSD', 'EUR', 'ZEUR']:
            decimals = 2
        else:
            decimals = 6
        
        return f"{float(volume):,.{decimals}f} {asset}".strip()
    except (ValueError, TypeError):
        return f"{volume} {asset}".strip()


def format_timestamp(timestamp: Union[str, float, int], 
                    timezone: str = "UTC") -> str:
    """Format timestamp to readable date/time"""
    try:
        # Handle different timestamp formats
        if isinstance(timestamp, str):
            if timestamp.isdigit():
                timestamp = int(timestamp)
            else:
                # Assume it's already a formatted string
                return timestamp
        
        # Convert to datetime
        if timestamp > 1e10:  # Milliseconds
            dt = datetime.fromtimestamp(timestamp / 1000, tz=pytz.UTC)
        else:  # Seconds
            dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
        
        # Convert to specified timezone
        if timezone != "UTC":
            tz = pytz.timezone(timezone)
            dt = dt.astimezone(tz)
        
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, OSError):
        return str(timestamp)


def validate_trading_pair(pair: str) -> bool:
    """Validate if a trading pair is valid format"""
    if not pair or len(pair) < 6:
        return False
    
    # Check for valid format (e.g., XBTUSD, ETHUSD, ADAUSD)
    valid_patterns = [
        r'^[A-Z]{6}$',  # Basic 6-char format
        r'^[XZ][A-Z]{5}$',  # Kraken format with prefix
    ]
    
    import re
    return any(re.match(pattern, pair.upper()) for pattern in valid_patterns)


def calculate_profit_loss(trade_data: dict) -> float:
    """Calculate profit/loss from trade data"""
    try:
        # This is a simplified calculation
        # Real P&L calculation would need more complex logic
        if 'cost' in trade_data and 'fee' in trade_data:
            cost = float(trade_data['cost'])
            fee = float(trade_data['fee'])
            return cost - fee
        return 0.0
    except (ValueError, KeyError, TypeError):
        return 0.0


def get_risk_level_color(risk_score: float) -> str:
    """Get color based on risk level"""
    if risk_score < 0.3:
        return "green"
    elif risk_score < 0.6:
        return "yellow"
    elif risk_score < 0.8:
        return "orange"
    else:
        return "red"


def format_order_summary(order_data: dict) -> str:
    """Format order data for display"""
    try:
        descr = order_data.get('descr', {})
        pair = descr.get('pair', 'N/A')
        type_ = descr.get('type', 'N/A').upper()
        ordertype = descr.get('ordertype', 'N/A').upper()
        volume = order_data.get('vol', 'N/A')
        price = descr.get('price', 'N/A')
        
        summary = f"{type_} {volume} {pair}"
        if ordertype == 'LIMIT' and price != 'N/A':
            summary += f" @ {price}"
        
        return summary
    except Exception:
        return "Unknown order"


def sanitize_input(text: str, max_length: int = 100) -> str:
    """Sanitize user input"""
    if not text:
        return ""
    
    # Remove potentially dangerous characters
    text = text.strip()
    text = text[:max_length]  # Limit length
    
    # Basic sanitization
    text = text.replace('<', '').replace('>', '').replace('"', '').replace("'", "")
    
    return text


def confirm_action(message: str, default: bool = False) -> bool:
    """Get user confirmation for critical actions"""
    try:
        import click
        return click.confirm(message, default=default)
    except ImportError:
        # Fallback to input if click not available
        response = input(f"{message} (y/N): ").lower().strip()
        return response in ['y', 'yes']


def safe_float_convert(value: Union[str, float, int], default: float = 0.0) -> float:
    """Safely convert value to float"""
    try:
        if isinstance(value, (int, float)):
            return float(value)
        elif isinstance(value, str):
            # Remove common currency symbols and spaces
            cleaned = value.replace('$', '').replace(',', '').replace(' ', '')
            return float(cleaned) if cleaned else default
        else:
            return default
    except (ValueError, TypeError):
        return default


def format_asset_amount(value: Union[str, float, int],
                        asset: str,
                        default_decimals: int = 8) -> str:
    """Format an asset amount without duplicating the asset code."""
    try:
        stripped = str(value).replace('$', '').replace(',', '').strip()
        amount = float(stripped)
    except (ValueError, TypeError):
        return str(value)

    asset_upper = (asset or "").upper()
    if asset_upper in {"USD", "ZUSD", "EUR", "ZEUR", "GBP", "ZGBP"}:
        decimals = 2
    else:
        decimals = default_decimals

    formatted = f"{amount:,.{decimals}f}"
    if decimals > 0:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted or "0"
