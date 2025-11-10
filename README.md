# Kraken Pro Trading CLI

A professional-grade command-line interface for trading cryptocurrencies on the Kraken exchange. This application provides comprehensive trading capabilities, portfolio management, and real-time market data access.

## ⚠️ IMPORTANT RISK WARNINGS

**READ BEFORE USE:**

- 🚨 **Trading cryptocurrencies involves substantial risk of loss**
- 🚨 **Past performance does not guarantee future results**
- 🚨 **Only trade with money you can afford to lose completely**
- 🚨 **This tool is provided for educational and research purposes**
- 🚨 **The authors are not responsible for any trading losses**
- 🚨 **Always test strategies in sandbox mode first**
- 🚨 **Do your own research and understand the risks**

**RECOMMENDED PRACTICES:**
- Start with small amounts
- Use proper risk management
- Understand stop-loss orders
- Never invest more than you can afford to lose
- Keep your API keys secure

## Features

### Core Trading Features
- ✅ Place market, limit, stop-loss, and take-profit orders
- ✅ Cancel individual or all open orders
- ✅ Real-time ticker information
- ✅ Order book data
- ✅ Trade history tracking
- ✅ Account balance monitoring

### Portfolio Management
- ✅ Real-time balance tracking
- ✅ Portfolio value calculation (USD)
- ✅ Open positions monitoring
- ✅ Performance metrics
- ✅ Asset allocation analysis

### Technical Features
- ✅ Secure API authentication
- ✅ Rate limiting compliance
- ✅ Comprehensive error handling
- ✅ Rich console output with colors
- ✅ Comprehensive logging
- ✅ Configuration management

## API Specifications (Updated 2025)

The application follows the current Kraken API specifications:

**Base URL**: `https://api.kraken.com`  
**API Version**: `/0/`  
**Authentication**: HMAC-SHA512 with SHA256  
**Rate Limits**: 
- Public endpoints: 1 request/second
- Private endpoints: 15-20 requests/minute  
**Response Format**: JSON with `{"error": [], "result": {}}` structure

**Key API Endpoints Used**:
- Public: `/0/public/Ticker`, `/0/public/Time`, `/0/public/Depth`
- Private: `/0/private/Balance`, `/0/private/AddOrder`, `/0/private/CancelOrder`

## Installation

### Prerequisites
- Python 3.12 or higher
- pip package manager

### Setup Steps

1. **Clone or download the application**
   ```bash
   # If you have the files locally, navigate to the directory
   cd kraken-cli
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API credentials**
   ```bash
   # Copy the template file
   cp .env.template .env
   
   # Edit the .env file with your Kraken API credentials
   nano .env
   ```

4. **Set up Kraken API credentials**
   - Go to [Kraken API Settings](https://www.kraken.com/u/settings/api)

## Recent Updates (November 2025)

### ✅ **Fixed Issues**
- **Balance Data Processing**: Resolved `'str' object has no attribute 'get'` error
  - Kraken API returns balances as strings, not dictionaries
  - Code now correctly handles string-to-float conversion
  - Improved balance display and filtering

- **API Response Parsing**: Enhanced 2025 API compliance
  - Proper handling of `{"error": [], "result": {}}` response format
  - Fixed server time and balance data extraction
  - Updated HTTP methods (GET for public endpoints, POST for private)
   - Create a new API key with the following permissions:
     - **Query Funds** - to check balances
     - **Query Open Orders & Trades** - to view orders and trades
     - **Create & Modify Orders** - to place and manage orders
     - **Cancel Orders** - to cancel orders
   - Copy your API Key and API Secret to the `.env` file
   - For testing, enable "Use Kraken sandbox" in the `.env` file

5. **Test the connection**
   ```bash
   python kraken_cli.py status
   ```

## Usage

### Basic Commands

#### Check Account Status
```bash
python kraken_cli.py status
```
Shows account balance, server time, and connection status.

#### View Ticker Information
```bash
python kraken_cli.py ticker --pair XBTUSD
python kraken_cli.py ticker -p ETHUSD
```
Displays current price, 24h change, volume, and market data.

#### Place Orders

**Market Order (Buy)**
```bash
python kraken_cli.py order --pair XBTUSD --side buy --order-type market --volume 0.001
```

**Limit Order (Sell)**
```bash
python kraken_cli.py order --pair ETHUSD --side sell --order-type limit --volume 0.5 --price 2500
```

**Stop-Loss Order**
```bash
python kraken_cli.py order --pair XBTUSD --side sell --order-type stop-loss --volume 0.001 --price2 45000
```

#### Manage Orders

**View Open Orders**
```bash
python kraken_cli.py orders
```

**View Trade History**
```bash
python kraken_cli.py orders --trades
```

**Cancel Specific Order**
```bash
python kraken_cli.py cancel --txid YOUR_ORDER_ID
```

**Cancel All Orders**
```bash
python kraken_cli.py cancel --cancel-all
```

#### Portfolio Management

**View Portfolio Overview**
```bash
python kraken_cli.py portfolio
```

**Setup Configuration**
```bash
python kraken_cli.py config-setup
```

**View Application Info**
```bash
python kraken_cli.py info
```

### Command Options

#### Order Command Options
- `--pair, -p`: Trading pair (e.g., XBTUSD, ETHUSD, ADAUSD)
- `--side, -s`: Order side (buy/sell)
- `--order-type, -t`: Order type (market/limit/stop-loss/take-profit)
- `--volume, -v`: Order volume
- `--price`: Limit price (required for limit orders)
- `--price2`: Secondary price (for stop-loss/take-profit orders)

#### Ticker Command Options
- `--pair, -p`: Trading pair (default: XBTUSD)

#### Orders Command Options
- `--status, -s`: Filter by order status
- `--trades`: Show trade history instead of orders

#### Cancel Command Options
- `--cancel-all`: Cancel all open orders
- `--txid`: Cancel specific order by ID

#### Portfolio Command Options
- `--pair, -p`: Filter by trading pair

## Configuration

### Environment Variables

Create a `.env` file in the application directory:

```env
# Kraken API Configuration (2025 API Compliant)
KRAKEN_API_KEY=your_actual_api_key_here
KRAKEN_API_SECRET=your_actual_api_secret_here

# Environment Setting
# Note: Sandbox is now controlled via API key permissions
# The base URL is always https://api.kraken.com
KRAKEN_SANDBOX=false

# Rate limiting (updated for 2025 API)
# Public: 1 req/sec, Private: 15-20 req/min
KRAKEN_RATE_LIMIT=1

# Logging level
LOG_LEVEL=INFO
```

### API Setup for 2025

**Important Changes for 2025:**
- All API calls use `https://api.kraken.com` as base URL
- Sandbox access is controlled by API key permissions, not separate URLs
- Authentication uses updated HMAC-SHA512 with SHA256 method
- Rate limits are strictly enforced (1 req/sec public, 15-20 req/min private)

### API Permissions Required

Your Kraken API key needs these permissions:
- **Query Funds** - View account balances
- **Query Open Orders & Trades** - View orders and trade history
- **Create & Modify Orders** - Place new orders
- **Cancel Orders** - Cancel existing orders

### Sandbox Mode

For testing, set `KRAKEN_SANDBOX=true` in your `.env` file. This uses Kraken's test environment with fake money. Remember to:
- Create a separate API key for sandbox testing
- Switch to `KRAKEN_SANDBOX=false` for live trading

## Supported Trading Pairs

Common trading pairs supported:
- XBTUSD (Bitcoin/USD)
- ETHUSD (Ethereum/USD)
- ADAUSD (Cardano/USD)
- DOTUSD (Polkadot/USD)
- LINKUSD (Chainlink/USD)
- And many more available on Kraken

## Advanced Usage

### Custom Order Types

**Take-Profit Order**
```bash
python kraken_cli.py order --pair XBTUSD --side sell --order-type take-profit --volume 0.001 --price 50000 --price2 48000
```

**Stop-Loss with Limit**
```bash
python kraken_cli.py order --pair ETHUSD --side sell --order-type stop-loss --volume 1.0 --price 2000 --price2 1900
```

### Monitoring Market Data

**Real-time Order Book**
```bash
python kraken_cli.py ticker --pair XBTUSD
```

**Portfolio with Specific Asset**
```bash
python kraken_cli.py portfolio --pair ETHUSD
```

## Error Handling

The application includes comprehensive error handling for:
- Network connectivity issues
- API rate limiting
- Invalid API credentials
- Insufficient account balance
- Invalid order parameters
- Market data unavailable

## Security Best Practices

1. **API Key Security**
   - Never share your API keys
   - Use environment variables
   - Regularly rotate API keys
   - Use minimal required permissions

2. **Account Security**
   - Enable two-factor authentication on Kraken
   - Use strong passwords
   - Monitor account activity regularly
   - Set appropriate withdrawal limits

3. **Trading Security**
   - Start with small amounts
   - Use stop-loss orders
   - Diversify your portfolio
   - Keep detailed trading records

## Troubleshooting

### Common Issues

**"API credentials not configured"**
- Check that your `.env` file exists and contains valid API credentials
- Ensure the file path is correct

**"Connection failed"**
- Check your internet connection
- Verify API credentials are correct
- Ensure the API key has required permissions

**"Invalid trading pair"**
- Use valid Kraken trading pairs (e.g., XBTUSD, ETHUSD)
- Check the pair format matches Kraken's requirements

**"Insufficient balance"**
- Check your account balance
- Ensure you have enough funds for the order
- Account for trading fees

### Getting Help

- Kraken API Documentation: https://docs.kraken.com/rest/
- Kraken Support: https://support.kraken.com
- Check the logs directory for detailed error information

## Logging

The application creates detailed logs in the `logs/` directory:
- `kraken_cli.log` - Main application log
- Logs include all API requests, responses, and errors
- Log level can be configured in `.env`

## File Structure

```
kraken-cli/
├── kraken_cli.py           # Main CLI application
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── .env.template         # Environment template
├── .env                  # Your configuration (create this)
├── api/
│   └── kraken_client.py  # Kraken API client
├── trading/
│   └── trader.py         # Trading operations
├── portfolio/
│   └── portfolio_manager.py  # Portfolio management
├── utils/
│   ├── logger.py         # Logging configuration
│   └── helpers.py        # Utility functions
└── logs/                 # Log files (created automatically)
```

## Development

### Adding New Features

The application is designed to be easily extensible:
- Add new commands in `kraken_cli.py`
- Extend API functionality in `api/kraken_client.py`
- Add new trading features in `trading/trader.py`
- Enhance portfolio features in `portfolio/portfolio_manager.py`

### Code Quality

- Follow PEP 8 style guidelines
- Add comprehensive error handling
- Include logging for all operations
- Write clear documentation

## Troubleshooting

### Common Issues and Solutions

#### 1. Ticker Command Showing Incorrect 24h Change
**Problem**: Ticker shows impossible percentage values (e.g., 3622%)

**Solution**: This issue has been fixed in the latest version. The ticker now properly calculates percentage change using:
```
24h Change = ((Current Price - VWAP 24h) / VWAP 24h) * 100
```

**Fixed in**: v1.0.1 - Proper percentage calculation and color coding added

#### 2. Status Command Errors
**Error**: `'unixtime' KeyError`
**Solution**: Fixed API response parsing for 2025 Kraken API format

**Error**: `'str' object has no attribute 'get'`
**Solution**: Fixed balance data handling - balances are returned as strings, not dictionaries

#### 3. Ticker Command Arguments
**Error**: `Got unexpected extra arguments (BTC EUR)`
**Solution**: Updated ticker command to accept both formats:
```bash
python kraken_cli.py ticker BTC EUR     # NEW: Base Quote format
python kraken_cli.py ticker --pair XBTUSD  # Original: Kraken format
```

#### 4. API Connection Issues
- Verify your API credentials in `.env` file
- Ensure API key has necessary permissions
- Check internet connection
- Try running: `python kraken_cli.py status`

#### 5. Portfolio Balance Warnings
**Warning**: "Could not find USD value for staked/future assets"
**Explanation**: Some assets (ADA.S, DOT.S, ETH.F, XXDG) are special staked or future assets that don't have direct USD market data. This is normal and doesn't affect the balance display.

### Testing Commands
Use these commands to verify everything is working:

```bash
# Test API connection
python kraken_cli.py status

# Test ticker with multiple formats
python kraken_cli.py ticker BTC USD
python kraken_cli.py ticker --pair XBTUSD

# View portfolio
python kraken_cli.py portfolio

# Check available trading pairs
python kraken_cli.py info --pairs

# Get help
python kraken_cli.py --help
python kraken_cli.py ticker --help
```

## License

This software is provided for educational purposes. Use at your own risk. The authors are not responsible for any financial losses incurred through the use of this software.

## Disclaimer

This software is not affiliated with Kraken. It's an independent tool for interacting with the Kraken API. Always verify that you're using the official Kraken API and follow their terms of service.

**TRADING RISK WARNING: Cryptocurrency trading involves substantial risk of loss. Past performance is not indicative of future results. Only trade with money you can afford to lose completely.**