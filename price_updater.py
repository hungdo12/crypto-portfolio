"""
Price Updater & Telegram Alert Bot
====================================
Chạy background, mỗi 5 phút:
1. Lấy giá hiện tại từ Dexscreener cho tất cả token
2. Update vào Google Sheets (cột "Giá Hiện Tại")
3. Check alerts - nếu giá chạm target -> gửi Telegram

Chạy: python price_updater.py
"""

import time
import os
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
CREDS_FILE = os.getenv('GOOGLE_CREDS_FILE', 'credentials.json')
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL_SECONDS', 300))  # 5 phút

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


def log(msg: str):
    """In log có timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def get_client():
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def send_telegram(message: str):
    """Gửi tin nhắn qua Telegram"""
    if not TG_TOKEN or not TG_CHAT_ID:
        log("⚠️ Telegram chưa cấu hình, bỏ qua")
        return
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            'chat_id': TG_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }, timeout=10)
    except Exception as e:
        log(f"❌ Lỗi gửi Telegram: {e}")


def fetch_price(contract: str, network: str) -> dict:
    """Lấy giá token từ Dexscreener"""
    network_map = {
        'ETH': 'ethereum', 'BSC': 'bsc', 'BASE': 'base',
        'ARB': 'arbitrum', 'POLYGON': 'polygon', 'SONEIUM': 'soneium',
    }
    chain = network_map.get(network.upper(), network.lower())
    
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get('pairs'):
            return {'price': 0, 'change_24h': 0, 'error': 'No pair'}
        
        pairs = [p for p in data['pairs'] if p.get('chainId') == chain]
        if not pairs:
            pairs = data['pairs']
        
        best_pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
        
        return {
            'price': float(best_pair.get('priceUsd', 0) or 0),
            'change_24h': float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
            'volume_24h': float(best_pair.get('volume', {}).get('h24', 0) or 0),
            'liquidity': float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
            'error': None
        }
    except Exception as e:
        return {'price': 0, 'change_24h': 0, 'error': str(e)}


def update_portfolio_prices(client):
    """Update giá cho toàn bộ portfolio"""
    sheet = client.open_by_key(SHEET_ID).worksheet('Portfolio')
    data = sheet.get_all_records()
    
    if not data:
        log("Portfolio rỗng")
        return {}
    
    prices = {}
    for idx, row in enumerate(data):
        contract = row.get('Contract', '')
        network = row.get('Mạng', '')
        token = row.get('Token', '')
        
        if not contract or not network:
            continue
        
        result = fetch_price(contract, network)
        if result['price'] > 0:
            # Cột I = column 9 (Giá Hiện Tại)
            sheet.update_cell(idx + 2, 9, result['price'])
            prices[f"{token}_{network}"] = {
                'price': result['price'],
                'change_24h': result['change_24h'],
                'token': token,
                'network': network
            }
            log(f"✅ {token} ({network}): ${result['price']:.10f} ({result['change_24h']:+.2f}%)")
        else:
            log(f"⚠️ {token}: {result['error']}")
        
        # Tránh rate limit
        time.sleep(0.5)
    
    return prices


def check_alerts(client, current_prices: dict):
    """Check alerts và gửi Telegram nếu trigger"""
    sheet = client.open_by_key(SHEET_ID).worksheet('Alerts')
    alerts = sheet.get_all_records()
    
    for idx, alert in enumerate(alerts):
        if alert.get('Trạng Thái') != 'ACTIVE':
            continue
        
        token = alert.get('Token', '')
        network = alert.get('Mạng', '')
        alert_type = alert.get('Loại Alert', '')
        trigger_price = float(alert.get('Giá Trigger', 0) or 0)
        
        key = f"{token}_{network}"
        if key not in current_prices:
            continue
        
        current_price = current_prices[key]['price']
        change_24h = current_prices[key]['change_24h']
        
        triggered = False
        emoji = ''
        action_text = ''
        
        if alert_type == 'TAKE_PROFIT' and current_price >= trigger_price:
            triggered = True
            emoji = '🚀'
            action_text = 'CHỐT LỜI'
        elif alert_type == 'STOP_LOSS' and current_price <= trigger_price:
            triggered = True
            emoji = '🔻'
            action_text = 'CẮT LỖ'
        elif alert_type == 'PRICE_ABOVE' and current_price >= trigger_price:
            triggered = True
            emoji = '📈'
            action_text = 'VƯỢT NGƯỠNG'
        elif alert_type == 'PRICE_BELOW' and current_price <= trigger_price:
            triggered = True
            emoji = '📉'
            action_text = 'DƯỚI NGƯỠNG'
        
        if triggered:
            msg = (
                f"{emoji} <b>CẢNH BÁO {action_text}</b>\n\n"
                f"🪙 Token: <b>{token}</b> ({network})\n"
                f"💰 Giá hiện tại: <b>${current_price:.10f}</b>\n"
                f"🎯 Giá target: ${trigger_price:.10f}\n"
                f"📊 24h: {change_24h:+.2f}%\n"
                f"📝 Ghi chú: {alert.get('Ghi Chú', '')}\n\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            send_telegram(msg)
            log(f"🔔 ALERT TRIGGERED: {token} {alert_type}")
            
            # Mark as triggered để không spam
            sheet.update_cell(idx + 2, 5, 'TRIGGERED')
            sheet.update_cell(idx + 2, 6, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def send_daily_summary(client):
    """Gửi báo cáo tổng quan hàng ngày"""
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet('Portfolio')
        data = sheet.get_all_records()
        
        if not data:
            return
        
        total_cost = sum(float(r.get('Tổng Chi USD', 0) or 0) for r in data)
        total_value = sum(float(r.get('Giá Trị Hiện Tại', 0) or 0) for r in data)
        total_pnl = total_value - total_cost
        roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        emoji_pnl = '🟢' if total_pnl >= 0 else '🔴'
        
        msg = (
            f"📊 <b>BÁO CÁO PORTFOLIO</b>\n\n"
            f"💰 Vốn: ${total_cost:,.2f}\n"
            f"📈 Giá trị: ${total_value:,.2f}\n"
            f"{emoji_pnl} P&L: ${total_pnl:+,.2f} ({roi:+.2f}%)\n"
            f"🪙 Số token: {len(data)}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        send_telegram(msg)
    except Exception as e:
        log(f"❌ Lỗi gửi summary: {e}")


def main():
    log("🚀 Khởi động Crypto Portfolio Bot")
    log(f"⏱️ Interval: {UPDATE_INTERVAL}s ({UPDATE_INTERVAL/60:.1f} phút)")
    
    if not SHEET_ID:
        log("❌ GOOGLE_SHEET_ID chưa cấu hình trong .env!")
        return
    
    client = get_client()
    send_telegram("🤖 Bot Crypto Portfolio đã khởi động!")
    
    last_summary_day = None
    
    while True:
        try:
            log("=" * 50)
            log("🔄 Bắt đầu update giá...")
            
            prices = update_portfolio_prices(client)
            
            if prices:
                check_alerts(client, prices)
            
            # Gửi summary lúc 8h sáng mỗi ngày
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            if now.hour == 8 and last_summary_day != today_str:
                send_daily_summary(client)
                last_summary_day = today_str
            
            log(f"✅ Hoàn tất. Ngủ {UPDATE_INTERVAL}s...")
        
        except KeyboardInterrupt:
            log("👋 Tạm biệt!")
            break
        except Exception as e:
            log(f"❌ Lỗi: {e}")
        
        time.sleep(UPDATE_INTERVAL)


if __name__ == '__main__':
    main()
