import requests
import time
import pandas as pd
from datetime import datetime
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION - Use Environment Variables
# ============================================
TELEGRAM_BOT_TOKEN = '8566686741:AAFnctYOIRD27PBxCZd28VKhRWrn-BOVnFA'
TELEGRAM_CHAT_ID = '777442408'

# Trading parameters
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
RSI_PERIOD = 14
RSI_UPPER_THRESHOLD = 60
RSI_LOWER_THRESHOLD = 40

# ============================================
# BINANCE API FUNCTIONS
# ============================================
def get_klines(symbol, interval, limit=100):
    """Fetch historical kline/candlestick data from Binance"""
    endpoints = [
        "https://api.binance.com/api/v3/klines",
        "https://api1.binance.com/api/v3/klines",
        "https://api2.binance.com/api/v3/klines",
        "https://api3.binance.com/api/v3/klines",
    ]
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    for url in endpoints:
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"✅ Connected to {url.split('//')[1].split('/')[0]}")
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 451:
                logger.warning(f"⚠️ Region blocked on {url.split('//')[1].split('/')[0]}, trying next...")
                continue
            else:
                logger.error(f"HTTP Error on {url}: {e}")
        except Exception as e:
            logger.error(f"Error on {url}: {e}")
            continue
    
    logger.warning("⚠️ All Binance endpoints blocked, trying alternative...")
    return get_klines_alternative(symbol, interval, limit)

def get_klines_alternative(symbol, interval, limit=100):
    """Alternative data source using Binance US"""
    try:
        url = "https://api.binance.us/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info("✅ Connected to Binance US")
        return response.json()
    except Exception as e:
        logger.error(f"Alternative source failed: {e}")
        return None

# ============================================
# RSI CALCULATION
# ============================================
def calculate_rsi(prices, period=14):
    """Calculate RSI using closing prices"""
    if len(prices) < period + 1:
        return None
    
    df = pd.DataFrame(prices, columns=['close'])
    df['close'] = df['close'].astype(float)
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.iloc[-1]

# ============================================
# TELEGRAM FUNCTIONS
# ============================================
def send_telegram_message(message):
    """Send message to Telegram chat"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("✅ Telegram alert sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending Telegram message: {e}")
        return False

# ============================================
# MAIN MONITORING LOGIC
# ============================================
def monitor_btc_rsi():
    """Main function to monitor BTC RSI and send alerts"""
    logger.info(f"🚀 Starting BTC/USDT RSI monitor (RSI period: {RSI_PERIOD})")
    logger.info(f"📢 Alerts: RSI > {RSI_UPPER_THRESHOLD} or RSI < {RSI_LOWER_THRESHOLD}")
    
    last_candle_close_time = None
    alert_sent_for_candle = False
    alerts_count = 0
    start_time = time.time()
    
    while True:
        try:
            # Fetch latest klines
            klines = get_klines(SYMBOL, INTERVAL, limit=RSI_PERIOD + 50)
            
            if not klines:
                logger.warning("⚠️ Failed to fetch klines, retrying in 60 seconds...")
                time.sleep(60)
                continue
            
            # Get current candle close time
            current_candle = klines[-1]
            current_close_time = current_candle[6]
            current_price = float(current_candle[4])
            
            # Calculate RSI from completed candles
            completed_klines = klines[:-1]
            closing_prices = [float(k[4]) for k in completed_klines]
            rsi = calculate_rsi(closing_prices, RSI_PERIOD)
            
            # Initialize tracking
            if last_candle_close_time is None:
                last_candle_close_time = current_close_time
                alert_sent_for_candle = False
                logger.info("✅ Monitoring initialized")
            
            # Check for new candle close
            if current_close_time > last_candle_close_time:
                logger.info("🕐 New candle closed - calculating RSI...")
                
                if rsi is not None:
                    logger.info(f"💰 BTC/USDT Price: ${current_price:,.2f} | 📊 RSI(14): {rsi:.2f}")
                    
                    # Check for RSI signals
                    if rsi > RSI_UPPER_THRESHOLD and not alert_sent_for_candle:
                        message = (
                            f"🔴 BTC RSI ALERT - OVERBOUGHT\n\n"
                            f"Symbol: {SYMBOL}\n"
                            f"Price: ${current_price:,.2f}\n"
                            f"RSI(14): {rsi:.2f}\n"
                            f"Threshold: > {RSI_UPPER_THRESHOLD}\n\n"
                            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        if send_telegram_message(message):
                            alerts_count += 1
                        alert_sent_for_candle = True
                    
                    elif rsi < RSI_LOWER_THRESHOLD and not alert_sent_for_candle:
                        message = (
                            f"🟢 BTC RSI ALERT - OVERSOLD\n\n"
                            f"Symbol: {SYMBOL}\n"
                            f"Price: ${current_price:,.2f}\n"
                            f"RSI(14): {rsi:.2f}\n"
                            f"Threshold: < {RSI_LOWER_THRESHOLD}\n\n"
                            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        if send_telegram_message(message):
                            alerts_count += 1
                        alert_sent_for_candle = True
                    
                    else:
                        logger.info(f"📊 RSI in neutral zone ({RSI_LOWER_THRESHOLD}-{RSI_UPPER_THRESHOLD})")
                
                # Update tracking
                last_candle_close_time = current_close_time
                alert_sent_for_candle = False
            
            # Calculate time until next candle close
            time_until_close = (current_close_time - int(time.time() * 1000)) / 1000
            minutes_left = max(0, int(time_until_close / 60))
            
            runtime_seconds = int(time.time() - start_time)
            runtime_str = f"{runtime_seconds // 3600}h {(runtime_seconds % 3600) // 60}m"
            
            rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
            logger.info(f"📊 Status: Active | Price: ${current_price:,.2f} | RSI: {rsi_str} | "
                       f"Next candle: ~{minutes_left}min | Runtime: {runtime_str} | Alerts: {alerts_count}")
            
            # Check every 5 minutes
            time.sleep(300)
            
        except KeyboardInterrupt:
            logger.info("⛔ Monitoring stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            time.sleep(60)

# ============================================
# ENTRY POINT
# ============================================
if __name__ == "__main__":
    # Send startup notification
    startup_msg = (
        f"🤖 BTC RSI Monitor Started\n\n"
        f"Symbol: {SYMBOL}\n"
        f"Interval: {INTERVAL}\n"
        f"RSI Period: {RSI_PERIOD}\n"
        f"Thresholds: <{RSI_LOWER_THRESHOLD} or >{RSI_UPPER_THRESHOLD}\n\n"
        f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Platform: Render.com"
    )
    send_telegram_message(startup_msg)
    
    # Start monitoring
    monitor_btc_rsi()