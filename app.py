"""
Crypto Portfolio Manager - Streamlit App v4 (P&L Đúng)
============================================================
Giao diện quản lý đầu tư crypto, đồng bộ với Google Sheets.

v4 Updates (QUAN TRỌNG):
- Đọc cấu trúc Portfolio MỚI (sau khi đã sửa công thức P&L)
- Hiển thị tách Realized P&L / Unrealized P&L
- Thêm metric "Vốn đã thu hồi" (Tổng DT Bán)
- Dashboard cards mới chia 6 ô thay vì 4

v3 Updates:
- Hỗ trợ cả local (.env + credentials.json) lẫn cloud (Streamlit Secrets)
- Tự động phát hiện môi trường
- Cảnh báo concentration risk

Chạy local: streamlit run app.py
Deploy cloud: push lên GitHub, deploy qua https://share.streamlit.io
"""

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()

# ====================== CONFIG ======================
st.set_page_config(
    page_title="Crypto Portfolio Manager",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded"
)

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

NETWORKS = {
    'ETH': {'chain_id': 1, 'dex': 'uniswap'},
    'BSC': {'chain_id': 56, 'dex': 'pancakeswap'},
    'BASE': {'chain_id': 8453, 'dex': 'uniswap'},
    'SONEIUM': {'chain_id': 1868, 'dex': 'soneium'},
    'ARB': {'chain_id': 42161, 'dex': 'uniswap'},
    'KATANA': {'chain_id': 747474, 'dex': 'katana'},
    'POLYGON': {'chain_id': 137, 'dex': 'quickswap'},
    'SOLANA': {'chain_id': 0, 'dex': 'raydium'},
}

# ====================================================================
# CẤU TRÚC CỘT MỚI
# ====================================================================
# Tên cột chính xác trong Google Sheet (sau khi đã sửa)
COL = {
    'token': 'Token',
    'network': 'Mạng',
    'contract': 'Contract',
    'total_buy': 'Tổng SL Mua',
    'total_sell': 'Tổng SL Bán',
    'holding': 'SL Đang Giữ',
    'total_cost': 'Tổng Chi USD',
    'avg_buy_price': 'Giá TB Mua',
    'current_price': 'Giá Hiện Tại',
    'total_sell_revenue': 'Tổng DT Bán USD',  # MỚI
    'avg_sell_price': 'Giá TB Bán',           # MỚI
    'current_value': 'Giá Trị Hiện Tại',
    'realized_pnl': 'Realized P&L',           # MỚI
    'unrealized_pnl': 'Unrealized P&L',       # MỚI
    'total_pnl': 'Total P&L',                 # ĐỔI TÊN (cũ: P&L USD)
    'pnl_pct': 'P&L %',
    'target': 'Target Chốt Lời',
    'stop_loss': 'Stop Loss',
    'portfolio_pct': '% Danh Mục',
}

# Cấu trúc cột sheet Wallet
WALLET_COL = {
    'date': 'Ngày',
    'type': 'Loại',         # DEPOSIT | WITHDRAWAL | BALANCE
    'network': 'Mạng',
    'coin': 'Đồng',         # ETH | USDT | USDC
    'amount': 'Số lượng',
    'price': 'Giá USD',
    'value': 'Giá Trị USD',
    'tx_hash': 'Tx Hash',
    'note': 'Ghi chú',
}

# Cột chứa giá hiện tại trong sheet — cần để biết cell nào update khi fetch giá mới
CURRENT_PRICE_COL_INDEX = 9  # cột I = thứ 9


# ====================================================================
# WALLET — Đọc và tính toán
# ====================================================================
def load_wallet_data() -> dict:
    """
    Đọc sheet Wallet và tính:
    - total_deposit, total_withdrawal, net_capital
    - eth_balance (USD value, từ tổng các dòng BALANCE)
    
    Returns dict với keys: total_deposit, total_withdrawal, net_capital, eth_balance
    """
    result = {
        'total_deposit': 0.0,
        'total_withdrawal': 0.0,
        'net_capital': 0.0,
        'eth_balance': 0.0,
        'has_wallet_sheet': False,
    }
    
    client = get_gsheet_client()
    if not client or not SHEET_ID:
        return result
    
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet('Wallet')
        data = sheet.get_all_records()
    except Exception:
        # Sheet Wallet chưa tồn tại — fallback gracefully
        return result
    
    result['has_wallet_sheet'] = True
    
    for row in data:
        loai = str(row.get(WALLET_COL['type'], '')).strip().upper()
        val = clean_number(row.get(WALLET_COL['value'], 0))
        
        if loai == 'DEPOSIT':
            result['total_deposit'] += val
        elif loai == 'WITHDRAWAL':
            result['total_withdrawal'] += val
        elif loai == 'BALANCE':
            result['eth_balance'] += val
    
    result['net_capital'] = result['total_deposit'] - result['total_withdrawal']
    return result


def append_wallet_entry(entry: dict) -> bool:
    """Thêm 1 dòng vào sheet Wallet."""
    sheet = get_sheet('Wallet')
    if not sheet:
        return False
    
    value_usd = entry['amount'] * entry['price']
    row = [
        entry['date'], entry['type'], entry['network'], entry['coin'],
        entry['amount'], entry['price'], value_usd,
        entry.get('tx_hash', ''), entry.get('note', '')
    ]
    sheet.append_row(row, value_input_option='USER_ENTERED')
    st.cache_data.clear()
    return True


def fetch_eth_price() -> float:
    """Lấy giá ETH hiện tại từ Dexscreener (WETH trên ETH mainnet)."""
    WETH_ETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
    try:
        result = fetch_price_dexscreener(WETH_ETH, 'ETH')
        if result['price'] > 0:
            return result['price']
    except Exception:
        pass
    return 2045.0  # fallback nếu API fail


# ====================== CONFIG LOADER ======================
def get_config(key: str, default: str = '') -> str:
    try:
        if hasattr(st, 'secrets') and key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.getenv(key, default).strip()


def get_credentials():
    try:
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            creds_dict = dict(st.secrets['gcp_service_account'])
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception:
        pass
    creds_file = get_config('GOOGLE_CREDS_FILE', 'credentials.json')
    if os.path.exists(creds_file):
        return Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    return None


SHEET_ID = get_config('GOOGLE_SHEET_ID')


# ====================== HELPER ======================
def clean_number(val):
    """Convert string từ Google Sheets ($1,234.56, (123), 5.68%) thành float."""
    if pd.isna(val) or val == '' or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    is_negative = s.startswith('(') and s.endswith(')')
    s = (s.replace('$', '').replace(',', '').replace('%', '')
         .replace('(', '').replace(')', '').strip())
    try:
        num = float(s)
        return -num if is_negative else num
    except (ValueError, TypeError):
        return 0.0


def clean_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert tất cả cột số trong DataFrame portfolio."""
    money_cols = [
        COL['total_cost'], COL['current_value'], COL['total_pnl'],
        COL['avg_buy_price'], COL['current_price'],
        COL['total_buy'], COL['total_sell'], COL['holding'],
        COL['total_sell_revenue'], COL['avg_sell_price'],
        COL['realized_pnl'], COL['unrealized_pnl'],
    ]
    for col in money_cols:
        if col in df.columns:
            df[col] = df[col].apply(clean_number)
    
    # P&L % và % Danh Mục — có thể bị Sheets format thành 0.x hoặc x%
    for col in [COL['pnl_pct'], COL['portfolio_pct']]:
        if col in df.columns:
            df[col] = df[col].apply(clean_number)
            # Nếu max < 1 thì đang ở dạng decimal → nhân 100
            if not df[col].empty and df[col].abs().max() < 1 and df[col].abs().max() > 0:
                df[col] = df[col] * 100
    return df


def format_money(val: float, decimals: int = 2) -> str:
    if val < 0:
        return f"(${abs(val):,.{decimals}f})"
    return f"${val:,.{decimals}f}"


def format_pct(val: float) -> str:
    sign = '+' if val >= 0 else ''
    return f"{sign}{val:.2f}%"


# ====================== GOOGLE SHEETS ======================
@st.cache_resource
def get_gsheet_client():
    try:
        creds = get_credentials()
        if not creds:
            st.error("❌ Không tìm thấy credentials! Check .env hoặc Streamlit Secrets.")
            return None
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Google Sheets: {e}")
        return None


@st.cache_data(ttl=60)
def load_dataframe(sheet_name: str) -> pd.DataFrame:
    client = get_gsheet_client()
    if not client or not SHEET_ID:
        return pd.DataFrame()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and COL['token'] in df.columns:
            df = df[df[COL['token']].notna() &
                    (df[COL['token']] != '') &
                    (df[COL['token']] != 'TỔNG')]
        return df.reset_index(drop=True)
    except Exception as e:
        st.error(f"❌ Lỗi đọc sheet '{sheet_name}': {e}")
        return pd.DataFrame()


def get_sheet(sheet_name: str):
    client = get_gsheet_client()
    if not client or not SHEET_ID:
        return None
    try:
        return client.open_by_key(SHEET_ID).worksheet(sheet_name)
    except Exception as e:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}': {e}")
        return None


def append_transaction(tx_data: dict):
    sheet = get_sheet('Transactions')
    if not sheet:
        return False
    total_value = tx_data['amount'] * tx_data['price']
    row = [
        tx_data['date'], tx_data['type'], tx_data['token'], tx_data['network'],
        tx_data['contract'], tx_data['amount'], tx_data['price'], total_value,
        tx_data['pay_with'], tx_data['gas_fee'], tx_data['tx_hash'], tx_data['note']
    ]
    sheet.append_row(row, value_input_option='USER_ENTERED')
    st.cache_data.clear()
    return True


# ====================== PRICE FETCHING ======================
def fetch_price_dexscreener(contract: str, network: str) -> dict:
    network_map = {
        'ETH': 'ethereum', 'BSC': 'bsc', 'BASE': 'base',
        'ARB': 'arbitrum', 'POLYGON': 'polygon', 'SONEIUM': 'soneium',
        'SOLANA': 'solana',
    }
    chain = network_map.get(network.upper(), network.lower())
    
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get('pairs'):
            return {'price': 0, 'error': 'Không tìm thấy pair'}
        
        pairs = [p for p in data['pairs'] if p.get('chainId') == chain]
        if not pairs:
            return {'price': 0, 'error': f'Không có pool trên {network}'}
        
        valid_pairs = [p for p in pairs
                       if float(p.get('liquidity', {}).get('usd', 0) or 0) > 1000]
        if not valid_pairs:
            valid_pairs = pairs
        
        TRUSTED = ['WETH', 'WBNB', 'USDC', 'USDT', 'DAI', 'ETH', 'BNB', 'SOL', 'WSOL']
        trusted = [p for p in valid_pairs
                   if p.get('quoteToken', {}).get('symbol', '').upper() in TRUSTED]
        if trusted:
            valid_pairs = trusted
        
        best_pair = max(valid_pairs,
                        key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))
        
        return {
            'price': float(best_pair.get('priceUsd', 0) or 0),
            'price_change_24h': float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
            'volume_24h': float(best_pair.get('volume', {}).get('h24', 0) or 0),
            'liquidity': float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
            'fdv': float(best_pair.get('fdv', 0) or 0),
            'pair_url': best_pair.get('url', ''),
            'pair_info': f"{best_pair.get('baseToken', {}).get('symbol')}/"
                         f"{best_pair.get('quoteToken', {}).get('symbol')} "
                         f"@ {best_pair.get('dexId')}",
            'error': None
        }
    except Exception as e:
        return {'price': 0, 'error': str(e)}


def update_portfolio_prices():
    """Update giá cho tất cả token. Cột I (index 9) = Giá Hiện Tại."""
    sheet = get_sheet('Portfolio')
    if not sheet:
        return 0
    df = load_dataframe('Portfolio')
    if df.empty:
        return 0
    
    updated = 0
    for idx, row in df.iterrows():
        contract = row.get(COL['contract'], '')
        network = row.get(COL['network'], '')
        if not contract or not network:
            continue
        result = fetch_price_dexscreener(contract, network)
        if result['price'] > 0:
            # idx + 2 vì row 1 là header, idx bắt đầu từ 0
            sheet.update_cell(idx + 2, CURRENT_PRICE_COL_INDEX, result['price'])
            updated += 1
    st.cache_data.clear()
    return updated


# ====================== SIDEBAR ======================
with st.sidebar:
    st.title("💰 Crypto Portfolio")
    st.markdown("---")
    
    page = st.radio(
        "📍 Menu",
        ["📊 Dashboard", "➕ Thêm Giao Dịch", "📋 Portfolio",
         "💎 Ví & Vốn", "📜 Lịch Sử", "🔔 Cảnh Báo", "⚙️ Cài Đặt"]
    )
    
    st.markdown("---")
    
    if st.button("🔄 Cập nhật giá real-time", use_container_width=True, type="primary"):
        with st.spinner("Đang lấy giá từ Dexscreener..."):
            count = update_portfolio_prices()
        if count > 0:
            st.success(f"✅ Đã update {count} token!")
        else:
            st.warning("⚠️ Không update được")
    
    if st.button("🔁 Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    st.caption(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    is_cloud = hasattr(st, 'secrets') and 'GOOGLE_SHEET_ID' in st.secrets
    env_label = "☁️ Cloud" if is_cloud else "💻 Local"
    
    if SHEET_ID:
        st.caption(f"🟢 {env_label} - Kết nối OK")
    else:
        st.caption(f"🔴 {env_label} - Chưa cấu hình")


# ====================== PAGE: DASHBOARD ======================
if page == "📊 Dashboard":
    st.title("📊 Dashboard Tổng Quan")
    
    df_pf = load_dataframe('Portfolio')
    
    if df_pf.empty:
        st.warning("⚠️ Chưa có dữ liệu. Vào 'Thêm Giao Dịch' để bắt đầu.")
    else:
        df_pf = clean_numeric_columns(df_pf)
        
        # === TÍNH TOÁN TỪ CỘT MỚI ===
        total_cost = df_pf[COL['total_cost']].sum() if COL['total_cost'] in df_pf else 0
        total_value = df_pf[COL['current_value']].sum() if COL['current_value'] in df_pf else 0
        total_sell_revenue = (df_pf[COL['total_sell_revenue']].sum()
                              if COL['total_sell_revenue'] in df_pf else 0)
        realized_pnl = (df_pf[COL['realized_pnl']].sum()
                        if COL['realized_pnl'] in df_pf else 0)
        unrealized_pnl = (df_pf[COL['unrealized_pnl']].sum()
                          if COL['unrealized_pnl'] in df_pf else (total_value - total_cost))
        
        # Total P&L từ công thức ĐÚNG
        if COL['total_pnl'] in df_pf:
            total_pnl = df_pf[COL['total_pnl']].sum()
        else:
            # Fallback nếu sheet chưa có cột Total P&L
            total_pnl = realized_pnl + unrealized_pnl
        
        roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        num_tokens = (len(df_pf[df_pf[COL['holding']] > 0])
                      if COL['holding'] in df_pf else len(df_pf))
        
        # === ROW 1: 4 metric chính ===
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 Vốn Đầu Tư", format_money(total_cost))
        col2.metric("📈 Giá Trị Hiện Tại", format_money(total_value),
                    f"{total_pnl:+,.2f}")
        col3.metric("💵 Total P&L", format_money(total_pnl), format_pct(roi))
        col4.metric("🪙 Số Token Giữ", f"{num_tokens}")
        
        # === ROW 2: 3 metric chi tiết P&L ===
        st.markdown("##### 📊 Phân tích P&L chi tiết")
        col_r1, col_r2, col_r3 = st.columns(3)
        
        col_r1.metric(
            "💵 Realized P&L (đã chốt)",
            format_money(realized_pnl),
            help="Lãi/lỗ THỰC SỰ đã bỏ túi từ các giao dịch bán"
        )
        col_r2.metric(
            "📊 Unrealized P&L (chưa chốt)",
            format_money(unrealized_pnl),
            help="Lãi/lỗ 'trên giấy' của số token còn đang giữ"
        )
        col_r3.metric(
            "🎯 Tổng DT Đã Bán",
            format_money(total_sell_revenue),
            help="Tổng tiền đã thu về từ các giao dịch bán (đã trừ gas)"
        )
        
        st.markdown("---")
        
        # === SECTION MỚI: VỐN THỰC & TỔNG TÀI SẢN ===
        wallet = load_wallet_data()
        
        if wallet['has_wallet_sheet']:
            st.markdown("##### 💎 Vốn Thực & Tổng Tài Sản")
            
            net_capital = wallet['net_capital']
            eth_balance = wallet['eth_balance']
            total_assets = total_value + eth_balance
            real_pnl = total_assets - net_capital
            real_roi = (real_pnl / net_capital * 100) if net_capital > 0 else 0
            
            col_w1, col_w2, col_w3 = st.columns(3)
            col_w1.metric(
                "💰 Vốn Ròng",
                format_money(net_capital),
                help=f"Tiền tươi từ ví ngoài (Deposit ${wallet['total_deposit']:,.2f} − "
                     f"Withdrawal ${wallet['total_withdrawal']:,.2f})"
            )
            col_w2.metric(
                "💎 Số Dư Ví",
                format_money(eth_balance),
                help="ETH/USDT đang giữ trong ví, chưa dùng mua token (từ dòng BALANCE trong sheet Wallet)"
            )
            col_w3.metric(
                "🏦 Tổng Tài Sản",
                format_money(total_assets),
                help="Giá Trị Token + Số Dư Ví"
            )
            
            col_p1, col_p2, col_p3 = st.columns(3)
            col_p1.metric(
                "📈 P&L Thực",
                format_money(real_pnl),
                format_pct(real_roi),
                help="Tổng Tài Sản − Vốn Ròng. Đây mới là LÃI/LỖ THỰC SỰ"
            )
            col_p2.metric(
                "💵 Tổng Deposit",
                format_money(wallet['total_deposit']),
                help="Tổng tiền đã nạp từ ví ngoài"
            )
            col_p3.metric(
                "🏧 Tổng Withdrawal",
                format_money(wallet['total_withdrawal']),
                help="Tổng tiền đã rút về ví ngoài"
            )
            
            # So sánh "P&L Tổng (cost basis)" vs "P&L Thực (cash flow)"
            if abs(total_pnl - real_pnl) > 1:
                with st.expander("ℹ️ Vì sao 'P&L Tổng' khác 'P&L Thực'?"):
                    st.markdown(f"""
                    - **P&L Tổng = ${total_pnl:,.2f}** → Tính theo cost basis từng token 
                      (kiểu Binance Portfolio). Khi ae lấy tiền bán token A mua token B, 
                      coi như 2 giao dịch độc lập, cộng dồn chi phí cả 2.
                    
                    - **P&L Thực = ${real_pnl:,.2f}** → Tính theo tiền tươi 
                      (kiểu CoinTracker). Chỉ tính những đồng tiền THỰC SỰ vào/ra khỏi crypto.
                    
                    → **Cả 2 đều đúng**, nhưng **P&L Thực** mới phản ánh số tiền 
                    ae thực sự lãi/lỗ trên vốn bỏ ra.
                    """)
        else:
            st.info("💡 Tip: Tạo sheet **Wallet** trong Google Sheets để track vốn thực, "
                    "số dư ETH/USDT trong ví và P&L thực sự (Vốn ròng vs Tổng tài sản). "
                    "Xem hướng dẫn ở trang **💎 Ví & Vốn**.")
        
        st.markdown("---")
        
        # === CẢNH BÁO TẬP TRUNG ===
        if COL['network'] in df_pf.columns and total_value > 0:
            chain_alloc = df_pf.groupby(COL['network'])[COL['current_value']].sum()
            max_chain = chain_alloc.idxmax()
            max_pct = chain_alloc.max() / total_value * 100
            
            if max_pct > 70:
                st.error(f"🚨 **CẢNH BÁO TẬP TRUNG RỦI RO CAO**: {max_pct:.1f}% vốn đang ở **{max_chain}**. "
                         f"Khuyến nghị rebalance, không nên để 1 chain > 50%.")
            elif max_pct > 50:
                st.warning(f"⚠️ **Cảnh báo**: {max_pct:.1f}% vốn đang ở **{max_chain}**. "
                           f"Cân nhắc đa dạng hóa.")
        
        # === TOP LÃI / LỖ ===
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("🚀 Top Lãi (Total P&L)")
            cols_show = [COL['token'], COL['network'], COL['total_pnl'], COL['pnl_pct']]
            available_cols = [c for c in cols_show if c in df_pf.columns]
            if COL['total_pnl'] in df_pf.columns:
                winners = df_pf.nlargest(5, COL['total_pnl'])[available_cols].copy()
                winners[COL['total_pnl']] = winners[COL['total_pnl']].apply(format_money)
                winners[COL['pnl_pct']] = winners[COL['pnl_pct']].apply(format_pct)
                st.dataframe(winners, use_container_width=True, hide_index=True)
        
        with col_b:
            st.subheader("📉 Top Lỗ (Total P&L)")
            if COL['total_pnl'] in df_pf.columns:
                losers = df_pf.nsmallest(5, COL['total_pnl'])[available_cols].copy()
                losers[COL['total_pnl']] = losers[COL['total_pnl']].apply(format_money)
                losers[COL['pnl_pct']] = losers[COL['pnl_pct']].apply(format_pct)
                st.dataframe(losers, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        
        # === PHÂN BỔ THEO MẠNG ===
        col_c, col_d = st.columns([2, 3])
        with col_c:
            st.subheader("🌐 Phân Bổ Theo Mạng")
            if COL['network'] in df_pf.columns:
                network_alloc = df_pf.groupby(COL['network'])[COL['current_value']].sum().reset_index()
                network_alloc = network_alloc[network_alloc[COL['current_value']] > 0]
                if not network_alloc.empty:
                    network_alloc['%'] = (network_alloc[COL['current_value']] /
                                          network_alloc[COL['current_value']].sum() * 100).round(2)
                    network_alloc[COL['current_value']] = (
                        network_alloc[COL['current_value']].apply(format_money))
                    network_alloc['%'] = network_alloc['%'].apply(lambda x: f"{x:.2f}%")
                    st.dataframe(network_alloc, use_container_width=True, hide_index=True)
        
        with col_d:
            st.subheader("📊 Tỷ Trọng Vốn")
            if COL['network'] in df_pf.columns:
                chain_data = df_pf.groupby(COL['network'])[COL['current_value']].sum()
                chain_data = chain_data[chain_data > 0].sort_values(ascending=False)
                if not chain_data.empty:
                    total = chain_data.sum()
                    for chain_name, value in chain_data.items():
                        pct = (value / total * 100) if total > 0 else 0
                        col_label, col_bar, col_val = st.columns([1, 4, 2])
                        with col_label:
                            st.write(f"**{chain_name}**")
                        with col_bar:
                            st.progress(min(pct / 100, 1.0))
                        with col_val:
                            st.write(f"${value:,.2f} ({pct:.1f}%)")


# ====================== PAGE: THÊM GIAO DỊCH ======================
elif page == "➕ Thêm Giao Dịch":
    st.title("➕ Thêm Giao Dịch Mới")
    
    st.subheader("🔍 Check giá trước khi nhập")
    col_check1, col_check2, col_check3 = st.columns([2, 1, 1])
    with col_check1:
        check_contract = st.text_input("Contract Address", key="check_contract",
                                        placeholder="0x...")
    with col_check2:
        check_network = st.selectbox("Mạng", list(NETWORKS.keys()), key="check_network")
    with col_check3:
        st.write("")
        st.write("")
        if st.button("🔎 Check giá"):
            if check_contract:
                with st.spinner("Đang lấy giá..."):
                    result = fetch_price_dexscreener(check_contract, check_network)
                if result['error']:
                    st.error(f"❌ {result['error']}")
                else:
                    st.success(f"💰 Giá: **${result['price']:.10f}** | "
                              f"24h: **{result['price_change_24h']:+.2f}%** | "
                              f"Liquidity: **${result['liquidity']:,.0f}** | "
                              f"Pool: {result.get('pair_info', '')}")
                    if result.get('pair_url'):
                        st.markdown(f"[🔗 Xem trên Dexscreener]({result['pair_url']})")
    
    st.markdown("---")
    
    with st.form("add_tx_form", clear_on_submit=True):
        st.subheader("📝 Nhập giao dịch")
        col1, col2 = st.columns(2)
        
        with col1:
            tx_date = st.date_input("📅 Ngày giao dịch", value=datetime.now())
            tx_type = st.selectbox("📊 Loại", ['BUY', 'SELL'])
            token = st.text_input("🪙 Token Symbol", placeholder="VD: PEPE, BRETT")
            network = st.selectbox("🌐 Mạng", list(NETWORKS.keys()))
            contract = st.text_input("📋 Contract Address", placeholder="0x...")
        
        with col2:
            amount = st.number_input("🔢 Số lượng Token", min_value=0.0, format="%.8f")
            price = st.number_input("💲 Giá/Token (USD)", min_value=0.0, format="%.10f")
            pay_with = st.selectbox("💳 Thanh toán bằng",
                                     ['USDT', 'USDC', 'ETH', 'BNB', 'SOL', 'BASE-ETH'])
            gas_fee = st.number_input("⛽ Phí Gas (USD)", min_value=0.0, format="%.4f")
            tx_hash = st.text_input("🔗 Tx Hash (optional)", placeholder="0x...")
        
        if amount > 0 and price > 0:
            if tx_type == 'BUY':
                st.info(f"💵 **Tổng chi**: ${amount * price:,.4f} + phí ${gas_fee:.4f} = "
                       f"**${amount * price + gas_fee:,.4f}**")
            else:
                st.info(f"💵 **Tổng thu**: ${amount * price:,.4f} − phí ${gas_fee:.4f} = "
                       f"**${amount * price - gas_fee:,.4f}**")
        
        note = st.text_area("📝 Ghi chú", placeholder="VD: DCA lần 3, mua khi dump")
        
        submitted = st.form_submit_button("✅ Lưu Giao Dịch", type="primary",
                                          use_container_width=True)
        
        if submitted:
            if not token or not contract or amount <= 0 or price <= 0:
                st.error("❌ Vui lòng điền đầy đủ: Token, Contract, Số lượng, Giá!")
            else:
                tx_data = {
                    'date': tx_date.strftime('%Y-%m-%d'),
                    'type': tx_type, 'token': token.upper(), 'network': network,
                    'contract': contract, 'amount': amount, 'price': price,
                    'pay_with': pay_with, 'gas_fee': gas_fee,
                    'tx_hash': tx_hash, 'note': note
                }
                if append_transaction(tx_data):
                    st.success(f"✅ Đã lưu giao dịch **{tx_type} {amount:,.0f} {token}** "
                              f"@ ${price:.10f}")
                    st.balloons()
                    st.info("💡 Vào sheet Portfolio để thêm token mới vào bảng "
                            "(nếu chưa có) — công thức sẽ tự tính khi token có trong sheet.")


# ====================== PAGE: PORTFOLIO ======================
elif page == "📋 Portfolio":
    st.title("📋 Chi Tiết Danh Mục")
    
    df_pf = load_dataframe('Portfolio')
    if df_pf.empty:
        st.warning("⚠️ Chưa có dữ liệu.")
    else:
        df_pf = clean_numeric_columns(df_pf)
        
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            networks_available = df_pf[COL['network']].unique() if COL['network'] in df_pf else []
            filter_network = st.multiselect("🌐 Lọc mạng",
                                            options=networks_available,
                                            default=networks_available)
        with col2:
            sort_options = ['Total P&L ↓', 'Total P&L ↑', 'Realized ↓', 'Unrealized ↓',
                            'P&L % ↓', 'P&L % ↑', 'Giá Trị ↓', 'Token A-Z']
            sort_by = st.selectbox("🔃 Sắp xếp theo", sort_options)
        with col3:
            show_only_holding = st.checkbox("Chỉ đang giữ", value=True)
        
        df_filtered = df_pf.copy()
        if filter_network and COL['network'] in df_filtered:
            df_filtered = df_filtered[df_filtered[COL['network']].isin(filter_network)]
        if show_only_holding and COL['holding'] in df_filtered.columns:
            df_filtered = df_filtered[df_filtered[COL['holding']] > 0]
        
        sort_map = {
            'Total P&L ↓': (COL['total_pnl'], False),
            'Total P&L ↑': (COL['total_pnl'], True),
            'Realized ↓': (COL['realized_pnl'], False),
            'Unrealized ↓': (COL['unrealized_pnl'], False),
            'P&L % ↓': (COL['pnl_pct'], False),
            'P&L % ↑': (COL['pnl_pct'], True),
            'Giá Trị ↓': (COL['current_value'], False),
            'Token A-Z': (COL['token'], True),
        }
        if sort_by in sort_map:
            col_name, asc = sort_map[sort_by]
            if col_name in df_filtered.columns:
                df_filtered = df_filtered.sort_values(col_name, ascending=asc)
        
        # Cấu hình hiển thị cột
        column_config = {
            COL['total_cost']: st.column_config.NumberColumn(format="$%.2f"),
            COL['avg_buy_price']: st.column_config.NumberColumn(format="$%.10f"),
            COL['current_price']: st.column_config.NumberColumn(format="$%.10f"),
            COL['avg_sell_price']: st.column_config.NumberColumn(format="$%.10f"),
            COL['current_value']: st.column_config.NumberColumn(format="$%.2f"),
            COL['total_sell_revenue']: st.column_config.NumberColumn(format="$%.2f"),
            COL['realized_pnl']: st.column_config.NumberColumn(format="$%.2f"),
            COL['unrealized_pnl']: st.column_config.NumberColumn(format="$%.2f"),
            COL['total_pnl']: st.column_config.NumberColumn(format="$%.2f"),
            COL['pnl_pct']: st.column_config.NumberColumn(format="%.2f%%"),
            COL['portfolio_pct']: st.column_config.NumberColumn(format="%.2f%%"),
        }
        
        st.dataframe(df_filtered, use_container_width=True, hide_index=True,
                     column_config=column_config)
        
        # === Summary phía dưới ===
        if not df_filtered.empty:
            st.markdown("##### 📊 Tóm tắt theo bộ lọc")
            c1, c2, c3, c4 = st.columns(4)
            
            sum_cost = df_filtered[COL['total_cost']].sum() if COL['total_cost'] in df_filtered else 0
            sum_value = df_filtered[COL['current_value']].sum() if COL['current_value'] in df_filtered else 0
            sum_realized = df_filtered[COL['realized_pnl']].sum() if COL['realized_pnl'] in df_filtered else 0
            sum_unrealized = df_filtered[COL['unrealized_pnl']].sum() if COL['unrealized_pnl'] in df_filtered else 0
            
            c1.metric("Vốn", format_money(sum_cost))
            c2.metric("Giá Trị", format_money(sum_value))
            c3.metric("Realized", format_money(sum_realized))
            c4.metric("Unrealized", format_money(sum_unrealized))


# ====================== PAGE: VÍ & VỐN ======================
elif page == "💎 Ví & Vốn":
    st.title("💎 Ví & Vốn Thực")
    
    wallet = load_wallet_data()
    
    if not wallet['has_wallet_sheet']:
        st.warning("⚠️ Chưa có sheet **Wallet** trong Google Sheets!")
        st.markdown("""
        ### 📝 Cách tạo sheet Wallet:
        
        **Cách 1 (khuyến nghị)**: Upload file Excel đã có sẵn sheet Wallet
        
        **Cách 2**: Tạo thủ công sheet mới tên `Wallet` với 9 cột:
        ```
        Ngày | Loại | Mạng | Đồng | Số lượng | Giá USD | Giá Trị USD | Tx Hash | Ghi chú
        ```
        
        **3 loại giao dịch:**
        - `DEPOSIT`: Nạp tiền từ ví ngoài vào crypto (vốn mới)
        - `WITHDRAWAL`: Rút từ crypto ra ví ngoài
        - `BALANCE`: Snapshot số dư ETH/USDT trong ví (cập nhật thủ công)
        """)
        st.stop()
    
    # === Tóm tắt vốn ===
    st.markdown("### 📊 Tóm tắt vốn")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Tổng Deposit", format_money(wallet['total_deposit']))
    col2.metric("🏧 Tổng Withdrawal", format_money(wallet['total_withdrawal']))
    col3.metric("💵 Vốn Ròng", format_money(wallet['net_capital']))
    col4.metric("💎 Số Dư Ví (BALANCE)", format_money(wallet['eth_balance']))
    
    st.markdown("---")
    
    # === Thêm giao dịch ví ===
    st.markdown("### ➕ Thêm Giao Dịch Ví")
    
    tab1, tab2, tab3 = st.tabs(["💰 DEPOSIT (Nạp)", "🏧 WITHDRAWAL (Rút)", "💎 BALANCE (Cập nhật số dư)"])
    
    with tab1:
        st.caption("Nạp thêm tiền từ ví ngoài vào crypto. Vốn ròng sẽ tăng.")
        with st.form("deposit_form", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                d_date = st.date_input("📅 Ngày nạp", value=datetime.now(), key='d_date')
                d_network = st.selectbox("🌐 Mạng", list(NETWORKS.keys()), key='d_net', index=2)  # default BASE
                d_coin = st.selectbox("🪙 Đồng", ['ETH', 'USDT', 'USDC', 'BNB', 'SOL'], key='d_coin')
            with col_b:
                d_amount = st.number_input("🔢 Số lượng", min_value=0.0, format="%.8f", key='d_amount')
                d_price = st.number_input("💲 Giá USD/đồng", min_value=0.0, format="%.4f",
                                          value=fetch_eth_price() if 'ETH' in 'ETH' else 1.0,
                                          key='d_price')
                d_note = st.text_input("📝 Ghi chú", placeholder="VD: Nạp thêm để DCA", key='d_note')
            
            if d_amount > 0 and d_price > 0:
                st.info(f"💵 Giá trị: **${d_amount * d_price:,.2f}**")
            
            if st.form_submit_button("✅ Lưu DEPOSIT", type="primary", use_container_width=True):
                if d_amount > 0 and d_price > 0:
                    entry = {
                        'date': d_date.strftime('%Y-%m-%d'),
                        'type': 'DEPOSIT',
                        'network': d_network,
                        'coin': d_coin,
                        'amount': d_amount,
                        'price': d_price,
                        'note': d_note,
                    }
                    if append_wallet_entry(entry):
                        st.success(f"✅ Đã nạp {d_amount} {d_coin} (${d_amount * d_price:,.2f})")
                        st.balloons()
                else:
                    st.error("❌ Vui lòng nhập số lượng và giá")
    
    with tab2:
        st.caption("Rút tiền từ crypto về ví ngoài. Vốn ròng sẽ giảm, P&L thực tăng (chốt lãi).")
        with st.form("withdraw_form", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                w_date = st.date_input("📅 Ngày rút", value=datetime.now(), key='w_date')
                w_network = st.selectbox("🌐 Mạng", list(NETWORKS.keys()), key='w_net', index=2)
                w_coin = st.selectbox("🪙 Đồng", ['ETH', 'USDT', 'USDC', 'BNB', 'SOL'], key='w_coin')
            with col_b:
                w_amount = st.number_input("🔢 Số lượng", min_value=0.0, format="%.8f", key='w_amount')
                w_price = st.number_input("💲 Giá USD/đồng", min_value=0.0, format="%.4f",
                                          value=fetch_eth_price(), key='w_price')
                w_note = st.text_input("📝 Ghi chú", placeholder="VD: Rút chốt lãi về Binance", key='w_note')
            
            if w_amount > 0 and w_price > 0:
                st.info(f"💵 Giá trị rút: **${w_amount * w_price:,.2f}**")
            
            if st.form_submit_button("✅ Lưu WITHDRAWAL", type="primary", use_container_width=True):
                if w_amount > 0 and w_price > 0:
                    entry = {
                        'date': w_date.strftime('%Y-%m-%d'),
                        'type': 'WITHDRAWAL',
                        'network': w_network,
                        'coin': w_coin,
                        'amount': w_amount,
                        'price': w_price,
                        'note': w_note,
                    }
                    if append_wallet_entry(entry):
                        st.success(f"✅ Đã rút {w_amount} {w_coin} (${w_amount * w_price:,.2f})")
                else:
                    st.error("❌ Vui lòng nhập số lượng và giá")
    
    with tab3:
        st.caption("Cập nhật số dư ETH/USDT hiện tại trong ví (chưa dùng mua token). "
                   "Khi cập nhật mới, app sẽ CỘNG DỒN các dòng BALANCE — nên ae cần xóa "
                   "hoặc đổi loại dòng BALANCE cũ trước khi nhập mới.")
        
        st.warning("⚠️ **Lưu ý**: App tính tổng SUM tất cả dòng BALANCE. "
                   "Nếu ae muốn cập nhật số dư mới, vào Google Sheets xóa dòng BALANCE cũ trước.")
        
        with st.form("balance_form", clear_on_submit=True):
            col_a, col_b = st.columns(2)
            with col_a:
                b_date = st.date_input("📅 Ngày snapshot", value=datetime.now(), key='b_date')
                b_network = st.selectbox("🌐 Mạng", list(NETWORKS.keys()), key='b_net', index=2)
                b_coin = st.selectbox("🪙 Đồng", ['ETH', 'USDT', 'USDC', 'BNB', 'SOL'], key='b_coin')
            with col_b:
                b_amount = st.number_input("🔢 Số dư hiện tại", min_value=0.0, format="%.8f", key='b_amount')
                b_price = st.number_input("💲 Giá USD/đồng", min_value=0.0, format="%.4f",
                                          value=fetch_eth_price(), key='b_price')
                b_note = st.text_input("📝 Ghi chú", placeholder="VD: Snapshot sau khi bán SURPLUS",
                                       key='b_note')
            
            if b_amount > 0 and b_price > 0:
                st.info(f"💵 Giá trị: **${b_amount * b_price:,.2f}**")
            
            if st.form_submit_button("✅ Lưu BALANCE", type="primary", use_container_width=True):
                if b_amount > 0 and b_price > 0:
                    entry = {
                        'date': b_date.strftime('%Y-%m-%d'),
                        'type': 'BALANCE',
                        'network': b_network,
                        'coin': b_coin,
                        'amount': b_amount,
                        'price': b_price,
                        'note': b_note,
                    }
                    if append_wallet_entry(entry):
                        st.success(f"✅ Đã cập nhật số dư {b_amount} {b_coin} (${b_amount * b_price:,.2f})")
                else:
                    st.error("❌ Vui lòng nhập số lượng và giá")
    
    st.markdown("---")
    
    # === Hiển thị toàn bộ Wallet history ===
    st.markdown("### 📜 Lịch sử Ví")
    
    client = get_gsheet_client()
    if client and SHEET_ID:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet('Wallet')
            wallet_data = sheet.get_all_records()
            df_wallet = pd.DataFrame(wallet_data)
            
            if not df_wallet.empty:
                # Filter ra các loại đã biết
                if WALLET_COL['type'] in df_wallet.columns:
                    df_wallet = df_wallet[df_wallet[WALLET_COL['type']].isin(
                        ['DEPOSIT', 'WITHDRAWAL', 'BALANCE'])]
                
                st.dataframe(df_wallet, use_container_width=True, hide_index=True,
                            column_config={
                                WALLET_COL['amount']: st.column_config.NumberColumn(format="%.6f"),
                                WALLET_COL['price']: st.column_config.NumberColumn(format="$%.4f"),
                                WALLET_COL['value']: st.column_config.NumberColumn(format="$%.2f"),
                            })
            else:
                st.info("Chưa có giao dịch ví nào.")
        except Exception as e:
            st.error(f"Lỗi đọc sheet Wallet: {e}")
    
    st.markdown("---")
    
    # === Tính P&L Thực ===
    df_pf = load_dataframe('Portfolio')
    if not df_pf.empty:
        df_pf = clean_numeric_columns(df_pf)
        total_value = df_pf[COL['current_value']].sum() if COL['current_value'] in df_pf else 0
        total_assets = total_value + wallet['eth_balance']
        real_pnl = total_assets - wallet['net_capital']
        real_roi = (real_pnl / wallet['net_capital'] * 100) if wallet['net_capital'] > 0 else 0
        
        st.markdown("### 📈 Kết Quả P&L Thực")
        col_pnl1, col_pnl2, col_pnl3, col_pnl4 = st.columns(4)
        col_pnl1.metric("🪙 Giá Trị Token", format_money(total_value))
        col_pnl2.metric("💎 Số Dư Ví", format_money(wallet['eth_balance']))
        col_pnl3.metric("🏦 Tổng Tài Sản", format_money(total_assets))
        col_pnl4.metric("📈 P&L Thực", format_money(real_pnl), format_pct(real_roi))


# ====================== PAGE: LỊCH SỬ ======================
elif page == "📜 Lịch Sử":
    st.title("📜 Lịch Sử Giao Dịch")
    
    client = get_gsheet_client()
    if client and SHEET_ID:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet('Transactions')
            data = sheet.get_all_records()
            df_tx = pd.DataFrame(data)
        except Exception as e:
            st.error(f"Lỗi: {e}")
            df_tx = pd.DataFrame()
    else:
        df_tx = pd.DataFrame()
    
    if df_tx.empty:
        st.warning("⚠️ Chưa có giao dịch nào.")
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_token = st.multiselect("🪙 Token",
                                          options=df_tx['Token'].unique() if 'Token' in df_tx else [],
                                          default=[])
        with col2:
            filter_type = st.multiselect("📊 Loại", options=['BUY', 'SELL'], default=['BUY', 'SELL'])
        with col3:
            filter_network = st.multiselect("🌐 Mạng",
                                            options=df_tx['Mạng'].unique() if 'Mạng' in df_tx else [],
                                            default=[])
        
        df_show = df_tx.copy()
        if filter_token:
            df_show = df_show[df_show['Token'].isin(filter_token)]
        if filter_type:
            df_show = df_show[df_show['Loại'].isin(filter_type)]
        if filter_network:
            df_show = df_show[df_show['Mạng'].isin(filter_network)]
        
        # Hiển thị thống kê nhanh
        if 'Loại' in df_show.columns:
            buy_count = len(df_show[df_show['Loại'] == 'BUY'])
            sell_count = len(df_show[df_show['Loại'] == 'SELL'])
            st.caption(f"📌 Hiển thị {len(df_show)}/{len(df_tx)} giao dịch — "
                       f"🟢 BUY: {buy_count} | 🔴 SELL: {sell_count}")
        
        st.dataframe(df_show, use_container_width=True, hide_index=True)
        
        csv = df_show.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 Tải xuống CSV",
            data=csv,
            file_name=f"transactions_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime='text/csv'
        )


# ====================== PAGE: CẢNH BÁO ======================
elif page == "🔔 Cảnh Báo":
    st.title("🔔 Cấu Hình Cảnh Báo Telegram")
    
    st.info("💡 Bot Python (`price_updater.py`) sẽ check giá mỗi 5 phút và gửi cảnh báo "
            "qua Telegram khi giá chạm target.")
    
    with st.expander("➕ Thêm Cảnh Báo Mới", expanded=False):
        with st.form("add_alert", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                a_token = st.text_input("Token")
                a_network = st.selectbox("Mạng", list(NETWORKS.keys()), key='alert_net')
                a_type = st.selectbox("Loại", ['TAKE_PROFIT', 'STOP_LOSS',
                                                'PRICE_ABOVE', 'PRICE_BELOW'])
            with col2:
                a_price = st.number_input("Giá Trigger (USD)", min_value=0.0, format="%.10f")
                a_note = st.text_area("Ghi chú")
            
            if st.form_submit_button("✅ Thêm Alert", type="primary"):
                if a_token and a_price > 0:
                    sheet = get_sheet('Alerts')
                    if sheet:
                        sheet.append_row([a_token.upper(), a_network, a_type, a_price,
                                         'ACTIVE', '', a_note])
                        st.success("✅ Đã thêm alert!")
                        st.cache_data.clear()
                else:
                    st.error("❌ Cần nhập Token và Giá Trigger")
    
    df_alerts = load_dataframe('Alerts')
    if not df_alerts.empty:
        st.subheader("📋 Danh sách cảnh báo")
        st.dataframe(df_alerts, use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có cảnh báo nào.")


# ====================== PAGE: CÀI ĐẶT ======================
elif page == "⚙️ Cài Đặt":
    st.title("⚙️ Cài Đặt")
    
    is_cloud = hasattr(st, 'secrets') and 'GOOGLE_SHEET_ID' in st.secrets
    env_text = "☁️ Streamlit Cloud" if is_cloud else "💻 Local"
    st.info(f"**Môi trường hiện tại**: {env_text}")
    
    st.subheader("🔑 Kết Nối Hiện Tại")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Google Sheet ID", value=SHEET_ID if SHEET_ID else "(chưa cấu hình)",
                      disabled=True)
    with col2:
        tg_token = get_config('TELEGRAM_BOT_TOKEN')
        st.text_input("Telegram Bot Token",
                      value=(tg_token[:10] + "...") if tg_token else "(chưa cấu hình)",
                      disabled=True)
        st.text_input("Telegram Chat ID",
                      value=get_config('TELEGRAM_CHAT_ID', '(chưa cấu hình)'),
                      disabled=True)
    
    st.markdown("---")
    
    st.subheader("📱 Test Telegram")
    if st.button("📤 Test gửi tin nhắn", type="primary"):
        tg_token = get_config('TELEGRAM_BOT_TOKEN')
        tg_chat_id = get_config('TELEGRAM_CHAT_ID')
        if tg_token and tg_chat_id:
            try:
                url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
                r = requests.post(url, json={
                    'chat_id': tg_chat_id,
                    'text': '✅ Test thành công! Bot crypto portfolio đã sẵn sàng.'
                }, timeout=10)
                if r.status_code == 200:
                    st.success("✅ Đã gửi! Check Telegram của bạn.")
                else:
                    st.error(f"❌ Lỗi: {r.text}")
            except Exception as e:
                st.error(f"❌ {e}")
        else:
            st.warning("⚠️ Chưa cấu hình Telegram")
    
    st.markdown("---")
    st.subheader("📊 Kiểm tra kết nối")
    if st.button("🔍 Test kết nối Sheet"):
        client = get_gsheet_client()
        if client and SHEET_ID:
            try:
                ss = client.open_by_key(SHEET_ID)
                st.success(f"✅ Kết nối OK!")
                st.write(f"**File**: {ss.title}")
                st.write(f"**URL**: {ss.url}")
                st.write(f"**Sheets**: {', '.join([s.title for s in ss.worksheets()])}")
                
                # Check cấu trúc cột Portfolio
                try:
                    pf = ss.worksheet('Portfolio')
                    headers = pf.row_values(1)
                    st.markdown("**Các cột trong Portfolio sheet:**")
                    st.code(" | ".join(headers))
                    
                    required = [COL['total_pnl'], COL['realized_pnl'],
                                COL['unrealized_pnl'], COL['total_sell_revenue']]
                    missing = [c for c in required if c not in headers]
                    if missing:
                        st.error(f"❌ Thiếu cột: {', '.join(missing)}. "
                                 f"Vui lòng upload lại file đã sửa P&L!")
                    else:
                        st.success("✅ Cấu trúc cột ĐÚNG. App sẽ chạy bình thường.")
                except Exception as e:
                    st.warning(f"⚠️ Không đọc được Portfolio: {e}")
            except Exception as e:
                st.error(f"❌ {e}")
    
    st.markdown("---")
    st.subheader("📖 Hướng Dẫn")
    st.markdown("""
    **App v4 — Đã sửa P&L tính sai**
    
    Yêu cầu Google Sheet phải có cấu trúc Portfolio MỚI (sau khi sửa):
    - `Token | Mạng | Contract | Tổng SL Mua | Tổng SL Bán | SL Đang Giữ`
    - `Tổng Chi USD | Giá TB Mua | Giá Hiện Tại`
    - `Tổng DT Bán USD | Giá TB Bán | Giá Trị Hiện Tại` ← MỚI
    - `Realized P&L | Unrealized P&L | Total P&L | P&L %` ← MỚI
    - `Target Chốt Lời | Stop Loss | % Danh Mục`
    
    Nếu chưa có cấu trúc mới, upload file Excel đã sửa lên Google Drive trước.
    """)
