# Forex RSI Alert Bot

A Telegram bot that monitors 28 forex pairs for RSI(14) signals on 1-hour and 4-hour timeframes, synced to actual candle closes.

## Features

- 📊 **28 Forex Pairs**: All major and minor pairs
- ⏰ **Dual Timeframes**: 1h and 4h RSI monitoring
- 🕐 **Candle Close Sync**: Checks exactly when candles close
- 😴 **Smart Sleep Mode**: Inactive during 2-5 AM IST
- 📱 **Telegram Alerts**: Instant notifications for oversold/overbought signals
- 🔄 **Free Hosting**: Runs 24/7 on Render.com
- 📈 **API Efficient**: ~728 requests/day (within 800 free limit)

## Quick Setup

### 1. Get API Keys
- **Telegram Bot**: Message @BotFather → /newbot
- **TwelveData API**: Sign up at https://twelvedata.com/
- **Chat ID**: Message your bot, then visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 2. Deploy to Render.com
1. Fork this repository
2. Create new Web Service on Render.com
3. Connect your GitHub repo
4. Set environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TWELVEDATA_API_KEY`
   - `TELEGRAM_CHAT_ID`
5. Deploy!

## Environment Variables

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TWELVEDATA_API_KEY=your_api_key_here
TELEGRAM_CHAT_ID=your_numeric_chat_id
```

## Monitored Pairs

**Major Pairs (7):**
EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, USD/CAD, NZD/USD

**Minor Pairs (21):**
All cross-pairs between EUR, GBP, JPY, CHF, AUD, CAD, NZD

## Alert Example

```
📈 RSI ALERT 📈

💱 Pair: EUR/USD
⏰ Timeframe: 4h
📊 RSI(14): 28.5
💰 Price: 1.0845
🕐 IST: 15/12/2024 14:30

🟢 OVERSOLD SIGNAL
Potential BUY opportunity
```

## Customization

### RSI Thresholds
```python
self.rsi_oversold = 30    # Default: 30
self.rsi_overbought = 70  # Default: 70
```

### Sleep Schedule
```python
self.sleep_start_hour = 2  # 2 AM IST
self.sleep_end_hour = 5    # 5 AM IST
```

### Alert Cooldown
```python
if time_diff < 14400:  # 4 hours (default)
```

## Technical Details

- **RSI Calculation**: Standard 14-period with Wilder's smoothing
- **Candle Close Times**: 1h every hour, 4h every 4 hours (UTC)
- **API Usage**: ~728 requests/day (within 800 free limit)
- **Sleep Hours**: 2-5 AM IST (saves ~112 API calls)
- **Alert Frequency**: Max 1 per pair per timeframe every 4 hours

## Requirements

- Python 3.11+
- Free TwelveData API account (800 requests/day)
- Telegram Bot Token
- Free Render.com account

## License

MIT License - Feel free to modify and use!

## Disclaimer

This bot is for educational purposes only. Not financial advice. Trade at your own risk.