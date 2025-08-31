import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
from telegram import Bot
from telegram.ext import Application
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ForexRSIBot:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.twelvedata_api_key = os.getenv('TWELVEDATA_API_KEY')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        # 28 major forex pairs
        self.forex_pairs = [
            # Major pairs
            'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'USD/CAD', 'NZD/USD',
            # Minor pairs  
            'EUR/GBP', 'EUR/JPY', 'EUR/CHF', 'EUR/AUD', 'EUR/CAD', 'EUR/NZD',
            'GBP/JPY', 'GBP/CHF', 'GBP/AUD', 'GBP/CAD', 'GBP/NZD',
            'CHF/JPY', 'AUD/JPY', 'CAD/JPY', 'NZD/JPY',
            'AUD/CHF', 'AUD/CAD', 'AUD/NZD',
            'CAD/CHF', 'NZD/CHF', 'NZD/CAD'
        ]
        
        # RSI thresholds
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        
        # Track last alert times to avoid spam
        self.last_alerts = {}
        
        # API usage tracking
        self.daily_requests = 0
        self.last_reset = datetime.now().date()
        self.max_daily_requests = 780  # 28 pairs × ~28 checks/day
        
        # Timezone setup
        self.ist = pytz.timezone('Asia/Kolkata')
        self.utc = pytz.timezone('UTC')
        
        # Sleep hours in IST (2 AM - 5 AM)
        self.sleep_start_hour = 2
        self.sleep_end_hour = 5
        
        if not all([self.telegram_token, self.twelvedata_api_key, self.chat_id]):
            raise ValueError("Missing required environment variables")
        
        self.bot = Bot(token=self.telegram_token)
    
    def is_sleep_time(self) -> bool:
        """Check if it's sleep time in IST (2 AM - 5 AM)"""
        ist_now = datetime.now(self.ist)
        current_hour = ist_now.hour
        return self.sleep_start_hour <= current_hour < self.sleep_end_hour
    
    def get_next_candle_close_times(self) -> Dict[str, datetime]:
        """Calculate next candle close times for 1h and 4h timeframes"""
        utc_now = datetime.now(self.utc)
        
        # Next 1-hour candle close (every hour at :00)
        next_1h = utc_now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        # Next 4-hour candle close (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
        current_hour = utc_now.hour
        next_4h_hour = ((current_hour // 4) + 1) * 4
        if next_4h_hour >= 24:
            next_4h = utc_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            next_4h = utc_now.replace(hour=next_4h_hour, minute=0, second=0, microsecond=0)
        
        return {
            '1h': next_1h,
            '4h': next_4h
        }
    
    def should_check_timeframe(self, timeframe: str) -> bool:
        """Check if it's time to check a specific timeframe"""
        utc_now = datetime.now(self.utc)
        current_minute = utc_now.minute
        current_hour = utc_now.hour
        
        # Only check within 2 minutes of candle close
        if current_minute > 2:
            return False
        
        if timeframe == '1h':
            # Check every hour at the top of the hour
            return True
        elif timeframe == '4h':
            # Check only at 4-hour intervals (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
            return current_hour % 4 == 0
        
        return False
    
    def reset_daily_counter(self):
        """Reset daily request counter if it's a new day"""
        current_date = datetime.now().date()
        if current_date > self.last_reset:
            self.daily_requests = 0
            self.last_reset = current_date
            logger.info("Daily request counter reset")
    
    def can_make_request(self) -> bool:
        """Check if we can make another API request"""
        self.reset_daily_counter()
        return self.daily_requests < self.max_daily_requests
    
    async def calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate standard 14-period RSI (Wilder's smoothing method)"""
        if len(prices) < period + 1:
            return None
        
        # Calculate price changes
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        # Separate gains and losses
        gains = [delta if delta > 0 else 0 for delta in deltas]
        losses = [-delta if delta < 0 else 0 for delta in deltas]
        
        # Calculate initial average for first 14 periods
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # Apply Wilder's smoothing method for subsequent periods
        for i in range(period, len(gains)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        
        # Avoid division by zero
        if avg_loss == 0:
            return 100.0
        
        # Calculate RSI
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return round(rsi, 2)
    
    async def get_forex_data(self, symbol: str, interval: str) -> Optional[Dict]:
        """Fetch forex data from TwelveData API with rate limiting"""
        if not self.can_make_request():
            logger.warning(f"Daily API limit reached. Skipping {symbol} {interval}")
            return None
        
        url = "https://api.twelvedata.com/time_series"
        params = {
            'symbol': symbol,
            'interval': interval,
            'outputsize': '50',  # Enough for RSI calculation
            'apikey': self.twelvedata_api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    self.daily_requests += 1
                    logger.info(f"API request #{self.daily_requests}: {symbol} {interval}")
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        # Check for API error messages
                        if 'code' in data and data['code'] != 200:
                            logger.error(f"API error for {symbol} {interval}: {data.get('message', 'Unknown error')}")
                            return None
                        
                        return data
                    else:
                        logger.error(f"HTTP error for {symbol} {interval}: {response.status}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching data for {symbol} {interval}")
            return None
        except Exception as e:
            logger.error(f"Error fetching data for {symbol} {interval}: {e}")
            return None
    
    async def analyze_pair(self, symbol: str, interval: str) -> Optional[Dict]:
        """Analyze a forex pair for RSI signals"""
        data = await self.get_forex_data(symbol, interval)
        
        if not data or 'values' not in data:
            return None
        
        # Extract closing prices (reverse to get chronological order)
        prices = []
        try:
            for item in reversed(data['values']):
                prices.append(float(item['close']))
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing price data for {symbol}: {e}")
            return None
        
        if len(prices) < 15:  # Need at least 15 prices for 14-period RSI
            logger.warning(f"Insufficient data for {symbol} {interval}: {len(prices)} prices")
            return None
        
        # Calculate RSI
        rsi = await self.calculate_rsi(prices)
        if rsi is None:
            return None
        
        current_price = prices[-1]
        timestamp = data['values'][0]['datetime']
        
        return {
            'symbol': symbol,
            'interval': interval,
            'rsi': rsi,
            'price': current_price,
            'timestamp': timestamp
        }
    
    def should_send_alert(self, symbol: str, interval: str, rsi: float) -> bool:
        """Check if an alert should be sent based on RSI levels and timing"""
        key = f"{symbol}_{interval}"
        current_time = datetime.now()
        
        # Check if RSI is in alert zones
        is_oversold = rsi <= self.rsi_oversold
        is_overbought = rsi >= self.rsi_overbought
        
        if not (is_oversold or is_overbought):
            return False
        
        # Check cooldown period (4 hours for same pair/timeframe to avoid spam)
        if key in self.last_alerts:
            time_diff = (current_time - self.last_alerts[key]).total_seconds()
            if time_diff < 14400:  # 4 hour cooldown
                return False
        
        self.last_alerts[key] = current_time
        return True
    
    def format_alert_message(self, analysis: Dict) -> str:
        """Format the alert message for Telegram"""
        symbol = analysis['symbol']
        interval = analysis['interval']
        rsi = analysis['rsi']
        price = analysis['price']
        timestamp = analysis['timestamp']
        
        # Convert timestamp to IST for display
        utc_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        ist_time = utc_time.astimezone(self.ist)
        
        if rsi <= self.rsi_oversold:
            signal_type = "🟢 OVERSOLD SIGNAL"
            emoji = "📈"
            action = "Potential BUY opportunity"
        else:
            signal_type = "🔴 OVERBOUGHT SIGNAL"
            emoji = "📉"
            action = "Potential SELL opportunity"
        
        message = f"""
{emoji} RSI ALERT {emoji}

💱 Pair: {symbol}
⏰ Timeframe: {interval}
📊 RSI(14): {rsi}
💰 Price: {price}
🕐 IST: {ist_time.strftime('%d/%m/%Y %H:%M')}

{signal_type}
{action}

━━━━━━━━━━━━━━━
⚠️ Not financial advice
        """
        
        return message.strip()
    
    async def send_telegram_message(self, message: str):
        """Send message to Telegram with error handling"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id, 
                text=message
            )
            logger.info(f"Alert sent successfully")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
    
    async def monitor_timeframe(self, timeframe: str):
        """Monitor all pairs for a specific timeframe"""
        if not self.should_check_timeframe(timeframe):
            return
        
        logger.info(f"🔍 Checking {timeframe} timeframe for all {len(self.forex_pairs)} pairs...")
        
        alert_count = 0
        
        # Process pairs with small delays to avoid overwhelming API
        for i, symbol in enumerate(self.forex_pairs):
            try:
                analysis = await self.analyze_pair(symbol, timeframe)
                
                if analysis:
                    rsi = analysis['rsi']
                    logger.info(f"{symbol} {timeframe}: RSI = {rsi}")
                    
                    if self.should_send_alert(symbol, timeframe, rsi):
                        message = self.format_alert_message(analysis)
                        await self.send_telegram_message(message)
                        alert_count += 1
                
                # Small delay between requests (2 seconds)
                if i < len(self.forex_pairs) - 1:  # Don't delay after last pair
                    await asyncio.sleep(2)
                    
            except Exception as e:
                logger.error(f"Error analyzing {symbol} {timeframe}: {e}")
                continue
        
        if alert_count > 0:
            logger.info(f"📬 Sent {alert_count} alerts for {timeframe} timeframe")
        else:
            logger.info(f"✅ {timeframe} check complete - no alerts triggered")
    
    async def send_sleep_message(self):
        """Send sleep notification"""
        ist_now = datetime.now(self.ist)
        wake_time = ist_now.replace(hour=5, minute=0, second=0, microsecond=0)
        if wake_time <= ist_now:
            wake_time += timedelta(days=1)
        
        message = f"""
😴 Going to Sleep Mode

🕐 IST Time: {ist_now.strftime('%d/%m/%Y %H:%M')}
⏰ Wake up at: {wake_time.strftime('%d/%m/%Y %H:%M')} IST

Markets are quiet during these hours.
Will resume monitoring at 5:00 AM IST.

Sweet dreams! 🌙
        """
        await self.send_telegram_message(message.strip())
    
    async def send_wake_message(self):
        """Send wake up notification"""
        ist_now = datetime.now(self.ist)
        message = f"""
☀️ Good Morning! Bot is Awake

🕐 IST Time: {ist_now.strftime('%d/%m/%Y %H:%M')}
🔍 Resuming RSI monitoring...
📊 Watching {len(self.forex_pairs)} pairs on 1h & 4h timeframes

Ready to catch those RSI signals! 🎯
        """
        await self.send_telegram_message(message.strip())
    
    async def run_monitoring_cycle(self):
        """Run a single monitoring cycle for both timeframes"""
        # Check if it's sleep time
        if self.is_sleep_time():
            return False  # Signal that we're sleeping
        
        utc_now = datetime.now(self.utc)
        current_minute = utc_now.minute
        current_hour = utc_now.hour
        
        # Only check within first 3 minutes after candle close
        if current_minute > 3:
            return True  # Continue monitoring but skip this cycle
        
        # Check 1h timeframe (every hour)
        await self.monitor_timeframe('1h')
        
        # Check 4h timeframe (every 4 hours: 00, 04, 08, 12, 16, 20 UTC)
        if current_hour % 4 == 0:
            await self.monitor_timeframe('4h')
        
        return True  # Continue monitoring
    
    async def run_continuous_monitoring(self):
        """Run continuous monitoring with sleep schedule"""
        logger.info("🚀 Starting Forex RSI Bot with IST sleep schedule...")
        
        # Send startup message
        ist_now = datetime.now(self.ist)
        startup_msg = f"""
🚀 Forex RSI Bot Started!

📊 Monitoring: {len(self.forex_pairs)} pairs
⏰ Timeframes: 1h & 4h (synced to candle closes)
📈 RSI Oversold: ≤ {self.rsi_oversold}
📉 RSI Overbought: ≥ {self.rsi_overbought}

🕐 Current IST: {ist_now.strftime('%d/%m/%Y %H:%M')}
😴 Sleep Schedule: 2:00 AM - 5:00 AM IST

Expected daily usage: ~{len(self.forex_pairs) * 27} API requests
        """
        await self.send_telegram_message(startup_msg.strip())
        
        was_sleeping = False
        
        while True:
            try:
                current_sleep_status = self.is_sleep_time()
                
                # Handle sleep transitions
                if current_sleep_status and not was_sleeping:
                    # Going to sleep
                    await self.send_sleep_message()
                    was_sleeping = True
                    logger.info("😴 Entering sleep mode (2 AM - 5 AM IST)")
                    
                elif not current_sleep_status and was_sleeping:
                    # Waking up
                    await self.send_wake_message()
                    was_sleeping = False
                    logger.info("☀️ Exiting sleep mode - resuming monitoring")
                
                # Run monitoring if awake
                if not current_sleep_status:
                    await self.run_monitoring_cycle()
                    # Check every minute when awake to catch candle closes
                    await asyncio.sleep(60)
                else:
                    # Sleep for 10 minutes during sleep hours
                    await asyncio.sleep(600)
                
            except KeyboardInterrupt:
                logger.info("👋 Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"💥 Error in monitoring cycle: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    async def test_connection(self):
        """Test API connections and send test message"""
        try:
            # Test Telegram connection
            me = await self.bot.get_me()
            logger.info(f"✅ Telegram bot connected: @{me.username}")
            
            # Test TwelveData connection
            test_data = await self.get_forex_data('EUR/USD', '1h')
            if test_data and 'values' in test_data:
                logger.info("✅ TwelveData API connected successfully")
                
                # Test RSI calculation
                prices = [float(item['close']) for item in reversed(test_data['values'])]
                test_rsi = await self.calculate_rsi(prices)
                
                test_msg = f"""
🧪 Connection Test Successful!

✅ Telegram Bot: @{me.username}
✅ TwelveData API: Connected
✅ RSI Calculation: Working (EUR/USD RSI: {test_rsi})
✅ Chat ID: {self.chat_id}

🎯 Ready to monitor {len(self.forex_pairs)} forex pairs!
                """
                await self.send_telegram_message(test_msg.strip())
                return True
            else:
                logger.error("❌ TwelveData API connection failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
            return False

# Main execution function
async def main():
    """Main function to run the bot"""
    try:
        # Initialize bot
        bot = ForexRSIBot()
        
        # Test all connections
        if await bot.test_connection():
            logger.info("🎯 All systems ready. Starting monitoring...")
            await bot.run_continuous_monitoring()
        else:
            logger.error("❌ Connection test failed. Check environment variables.")
            
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        raise

if __name__ == "__main__":
    # Run the bot
    asyncio.run(main())
