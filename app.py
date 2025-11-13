from flask import Flask, render_template, jsonify, request
import requests
import pandas as pd
from datetime import datetime
import pytz
import logging
import threading
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================
# CONFIGURATION
# ============================================
TELEGRAM_BOT_TOKEN = '8566686741:AAFnctYOIRD27PBxCZd28VKhRWrn-BOVnFA'
TELEGRAM_CHAT_ID = '777442408'

SYMBOL = "BTCUSDT"
RSI_PERIOD = 14
RSI_UPPER_THRESHOLD = 60
RSI_LOWER_THRESHOLD = 40

# Timezone for IST
IST = pytz.timezone('Asia/Kolkata')

# Global state
monitor_state = {
    'running': False,
    'current_price': 0,
    'current_rsi': 0,
    'last_update': None,
    'alerts_count': 0,
    'start_time': None,
    'status': 'Stopped',
    'monitor_thread': None,
    'interval': '1h',  # Default interval
    'check_frequency': 5  # Check every 5 seconds
}

# ============================================
# HELPER FUNCTIONS
# ============================================
def get_ist_time():
    """Get current time in IST"""
    return datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')

# ============================================
# BINANCE API FUNCTIONS
# ============================================
def get_current_price(symbol):
    """Get current price from Binance"""
    endpoints = [
        "https://api.binance.com/api/v3/ticker/price",
        "https://api1.binance.com/api/v3/ticker/price",
        "https://api2.binance.com/api/v3/ticker/price",
        "https://api3.binance.com/api/v3/ticker/price",
    ]

    for url in endpoints:
        try:
            response = requests.get(f"{url}?symbol={symbol}", timeout=10)
            response.raise_for_status()
            data = response.json()
            return float(data['price'])
        except Exception as e:
            logger.warning(f"Failed {url}: {e}")
            continue

    # Fallback to klines if price endpoint fails
    klines = get_klines(symbol, "1m", limit=1)
    if klines:
        return float(klines[0][4])
    return 0

def get_klines(symbol, interval, limit=100):
    """Fetch historical kline data from Binance"""
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

    for url in endpoints:
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed {url}: {e}")
            continue

    return None

# ============================================
# RSI CALCULATION
# ============================================
def calculate_rsi(prices, period=14):
    """Calculate RSI using closing prices"""
    if len(prices) < period + 1:
        return None

    try:
        df = pd.DataFrame(prices, columns=['close'])
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna()

        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
    except Exception as e:
        logger.error(f"RSI calculation error: {e}")
        return 50

# ============================================
# TELEGRAM FUNCTIONS
# ============================================
def send_telegram_message(message):
    """Send message to Telegram chat"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("✅ Telegram alert sent")
        return True
    except Exception as e:
        logger.error(f"❌ Telegram error: {e}")
        return False

def setup_telegram_bot():
    """Setup Telegram bot commands and start polling for messages"""
    threading.Thread(target=poll_telegram_updates, daemon=True).start()

def poll_telegram_updates():
    """Poll Telegram for new messages"""
    offset = None
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {'timeout': 30, 'offset': offset}
            
            response = requests.get(url, params=params, timeout=35)
            data = response.json()
            
            if data.get('ok') and data.get('result'):
                for update in data['result']:
                    offset = update['update_id'] + 1
                    
                    if 'message' in update and 'text' in update['message']:
                        message_text = update['message']['text'].strip()
                        chat_id = update['message']['chat']['id']
                        
                        # Only respond to our configured chat
                        if str(chat_id) == TELEGRAM_CHAT_ID:
                            handle_telegram_command(message_text)
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error polling Telegram: {e}")
            time.sleep(5)

def handle_telegram_command(command):
    """Handle Telegram bot commands"""
    global monitor_state, RSI_UPPER_THRESHOLD, RSI_LOWER_THRESHOLD  # Move global declaration to the top
    
    command = command.lower().strip()
    
    if command == '/start':
        response = (
            "🤖 <b>BTC RSI Monitor Bot</b>\n\n"
            "<b>Available Commands:</b>\n"
            "/status - Get current status\n"
            "/interval 15m - Set interval (1m, 5m, 15m, 1h, 4h, 1d)\n"
            "/threshold 65 35 - Set RSI thresholds\n"
            "/help - Show this message\n\n"
            f"Current Interval: <b>{monitor_state['interval']}</b>\n"
            f"Thresholds: <b>{RSI_LOWER_THRESHOLD}</b> - <b>{RSI_UPPER_THRESHOLD}</b>"
        )
        send_telegram_message(response)
    
    elif command == '/status':
        current_price = monitor_state['current_price']
        current_rsi = monitor_state['current_rsi']
        
        response = (
            f"📊 <b>Current Status</b>\n\n"
            f"💰 Price: <b>${current_price:,.2f}</b>\n"
            f"📈 RSI(14): <b>{current_rsi:.2f}</b>\n"
            f"⏱️ Interval: <b>{monitor_state['interval']}</b>\n"
            f"🔔 Alerts: <b>{monitor_state['alerts_count']}</b>\n"
            f"🕐 Updated: <b>{monitor_state['last_update']}</b>\n"
            f"Status: <b>{monitor_state['status']}</b>"
        )
        send_telegram_message(response)
    
    elif command.startswith('/interval'):
        try:
            parts = command.split()
            if len(parts) == 2:
                new_interval = parts[1].lower()
                valid_intervals = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']
                
                if new_interval in valid_intervals:
                    monitor_state['interval'] = new_interval
                    response = f"✅ Interval changed to <b>{new_interval}</b>"
                else:
                    response = f"❌ Invalid interval. Use: {', '.join(valid_intervals)}"
            else:
                response = "❌ Usage: /interval 15m"
        except Exception as e:
            response = f"❌ Error: {str(e)}"
        
        send_telegram_message(response)
    
    elif command.startswith('/threshold'):
        try:
            parts = command.split()
            if len(parts) == 3:
                upper = int(parts[1])
                lower = int(parts[2])
                
                if 0 < lower < upper < 100:
                    RSI_UPPER_THRESHOLD = upper
                    RSI_LOWER_THRESHOLD = lower
                    response = f"✅ Thresholds set to <b>{lower}</b> - <b>{upper}</b>"
                else:
                    response = "❌ Invalid thresholds. Ensure 0 < lower < upper < 100"
            else:
                response = "❌ Usage: /threshold 65 35"
        except Exception as e:
            response = f"❌ Error: {str(e)}"
        
        send_telegram_message(response)
    
    elif command == '/help':
        response = (
            "🤖 <b>BTC RSI Monitor Help</b>\n\n"
            "<b>Commands:</b>\n"
            "/status - Current price and RSI\n"
            "/interval [time] - Change check interval\n"
            "   Examples: /interval 15m, /interval 1h\n"
            "/threshold [upper] [lower] - Set RSI alerts\n"
            "   Example: /threshold 65 35\n\n"
            "<b>Valid Intervals:</b>\n"
            "1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d"
        )
        send_telegram_message(response)

# ============================================
# MONITORING LOGIC
# ============================================
def monitor_btc_rsi():
    """Background monitoring function - checks every 5 seconds"""
    global monitor_state

    logger.info(f"🚀 Starting BTC/USDT RSI monitor")

    last_alert_time = None
    alert_cooldown = 300  # 5 minutes cooldown between alerts

    while monitor_state['running']:
        try:
            # Get current price
            current_price = get_current_price(SYMBOL)

            # Get klines for RSI calculation using current interval
            interval = monitor_state['interval']
            klines = get_klines(SYMBOL, interval, limit=RSI_PERIOD + 50)

            if klines and len(klines) > RSI_PERIOD:
                closing_prices = [float(k[4]) for k in klines]
                rsi = calculate_rsi(closing_prices, RSI_PERIOD)
            else:
                rsi = 50  # Default value if calculation fails

            # Update global state with latest data
            monitor_state['current_price'] = current_price
            monitor_state['current_rsi'] = rsi
            monitor_state['last_update'] = get_ist_time()
            monitor_state['status'] = 'Active'

            logger.info(f"💰 {SYMBOL}: ${current_price:,.2f} | RSI: {rsi:.2f} | Interval: {interval}")

            # Check for alerts with cooldown
            current_time = time.time()
            should_alert = (last_alert_time is None or
                          (current_time - last_alert_time) >= alert_cooldown)

            if rsi > RSI_UPPER_THRESHOLD and should_alert:
                message = (
                    f"🔴 <b>BTC RSI ALERT - OVERBOUGHT</b>\n\n"
                    f"Symbol: <b>{SYMBOL}</b>\n"
                    f"💰 Price: <b>${current_price:,.2f}</b>\n"
                    f"📊 RSI(14): <b>{rsi:.2f}</b>\n"
                    f"⚠️ Threshold: <b>&gt; {RSI_UPPER_THRESHOLD}</b>\n"
                    f"⏱️ Interval: <b>{interval}</b>\n\n"
                    f"🕐 Time: {get_ist_time()}"
                )
                if send_telegram_message(message):
                    monitor_state['alerts_count'] += 1
                    last_alert_time = current_time

            elif rsi < RSI_LOWER_THRESHOLD and should_alert:
                message = (
                    f"🟢 <b>BTC RSI ALERT - OVERSOLD</b>\n\n"
                    f"Symbol: <b>{SYMBOL}</b>\n"
                    f"💰 Price: <b>${current_price:,.2f}</b>\n"
                    f"📊 RSI(14): <b>{rsi:.2f}</b>\n"
                    f"⚠️ Threshold: <b>&lt; {RSI_LOWER_THRESHOLD}</b>\n"
                    f"⏱️ Interval: <b>{interval}</b>\n\n"
                    f"🕐 Time: {get_ist_time()}"
                )
                if send_telegram_message(message):
                    monitor_state['alerts_count'] += 1
                    last_alert_time = current_time

            # Wait before next update (5 seconds)
            time.sleep(monitor_state['check_frequency'])

        except Exception as e:
            logger.error(f"❌ Monitoring error: {e}")
            time.sleep(10)

    monitor_state['status'] = 'Stopped'
    logger.info("⛔ Monitoring stopped")

# ============================================
# FLASK ROUTES
# ============================================
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/status')
def status():
    """API endpoint for current status"""
    runtime = 0
    if monitor_state['start_time']:
        runtime = int(time.time() - monitor_state['start_time'])

    return jsonify({
        'running': monitor_state['running'],
        'current_price': monitor_state['current_price'],
        'current_rsi': round(monitor_state['current_rsi'], 2),
        'last_update': monitor_state['last_update'],
        'alerts_count': monitor_state['alerts_count'],
        'runtime': runtime,
        'status': monitor_state['status'],
        'symbol': SYMBOL,
        'interval': monitor_state['interval'],
        'rsi_upper': RSI_UPPER_THRESHOLD,
        'rsi_lower': RSI_LOWER_THRESHOLD,
        'check_frequency': monitor_state['check_frequency']
    })

@app.route('/start')
def start_monitor():
    """Start the monitoring"""
    global monitor_state

    if not monitor_state['running']:
        monitor_state['running'] = True
        monitor_state['start_time'] = time.time()
        monitor_state['alerts_count'] = 0

        # Send startup notification
        startup_msg = (
            f"🤖 <b>BTC RSI Monitor Started</b>\n\n"
            f"Symbol: <b>{SYMBOL}</b>\n"
            f"⏱️ Interval: <b>{monitor_state['interval']}</b>\n"
            f"📊 RSI Period: <b>{RSI_PERIOD}</b>\n"
            f"⚠️ Thresholds: <b>&lt;{RSI_LOWER_THRESHOLD}</b> or <b>&gt;{RSI_UPPER_THRESHOLD}</b>\n"
            f"🔄 Check Frequency: <b>Every {monitor_state['check_frequency']}s</b>\n\n"
            f"🕐 Started: {get_ist_time()}"
        )
        send_telegram_message(startup_msg)

        # Start monitoring in background thread
        monitor_state['monitor_thread'] = threading.Thread(target=monitor_btc_rsi, daemon=True)
        monitor_state['monitor_thread'].start()

        return jsonify({'success': True, 'message': 'Monitor started'})
    else:
        return jsonify({'success': False, 'message': 'Monitor already running'})

@app.route('/stop')
def stop_monitor():
    """Stop the monitoring"""
    global monitor_state

    if monitor_state['running']:
        monitor_state['running'] = False

        # Wait for thread to finish
        if monitor_state['monitor_thread']:
            monitor_state['monitor_thread'].join(timeout=5)

        # Send stop notification
        stop_msg = (
            f"⛔ <b>BTC RSI Monitor Stopped</b>\n\n"
            f"🔔 Total Alerts Sent: <b>{monitor_state['alerts_count']}</b>\n"
            f"🕐 Stopped: {get_ist_time()}"
        )
        send_telegram_message(stop_msg)

        return jsonify({'success': True, 'message': 'Monitor stopped'})
    else:
        return jsonify({'success': False, 'message': 'Monitor not running'})

@app.route('/change-interval', methods=['POST'])
def change_interval():
    """Change monitoring interval"""
    global monitor_state
    
    data = request.json
    new_interval = data.get('interval', '1h')
    
    valid_intervals = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d']
    
    if new_interval in valid_intervals:
        monitor_state['interval'] = new_interval
        return jsonify({'success': True, 'message': f'Interval changed to {new_interval}'})
    else:
        return jsonify({'success': False, 'message': 'Invalid interval'})

if __name__ == '__main__':
    # Start Telegram bot polling
    setup_telegram_bot()
    
    # Start Flask app
    app.run(debug=False, host='0.0.0.0', port=5000)