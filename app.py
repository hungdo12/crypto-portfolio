"""
Crypto Portfolio Manager - Streamlit App v2
============================================
Giao diện quản lý đầu tư crypto, đồng bộ với Google Sheets.

Tính năng:
- Dashboard tổng quan với KPI cards
- Thêm giao dịch BUY/SELL nhanh
- Xem chi tiết portfolio theo token
- Lịch sử giao dịch + export CSV
- Cấu hình cảnh báo Telegram
- Cảnh báo concentration risk (1 chain > 50%)
- Auto-refresh giá real-time
- Sort portfolio theo P&L

Chạy: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import requests
import os
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

SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '').strip()
CREDS_FILE = os.getenv('GOOGLE_CREDS_FILE', 'credentials.json').strip()

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


# ====================== HELPER: CLEAN NUMBER ======================
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


def format_money(val: float, decimals: int = 2) -> str:
    """Format số tiền: $1,234.56"""
    return f"${val:,.{decimals}f}"


def format_pct(val: float) -> str:
    """Format phần trăm: +5.68%"""
    sign = '+' if val >= 0 else ''
    return f"{sign}{val:.2f}%"


# ====================== GOOGLE SHEETS CONNECTION ======================
@st.cache_resource
def get_gsheet_client():
    """Kết nối Google Sheets API"""
    try:
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Google Sheets: {e}")
        return None


@st.cache_data(ttl=60)
def load_dataframe(sheet_name: str) -> pd.DataFrame:
    """Đọc dữ liệu từ sheet thành DataFrame"""
    client = get_gsheet_client()
    if not client or not SHEET_ID:
        return pd.DataFrame()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet(sheet_name)
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and 'Token' in df.columns:
            df = df[df['Token'].notna() & (df['Token'] != '') & (df['Token'] != 'TỔNG')]
        return df.reset_index(drop=True)
    except Exception as e:
        st.error(f"❌ Lỗi đọc sheet '{sheet_name}': {e}")
        return pd.DataFrame()


def get_sheet(sheet_name: str):
    """Lấy 1 sheet để ghi"""
    client = get_gsheet_client()
    if not client or not SHEET_ID:
        return None
    try:
        return client.open_by_key(SHEET_ID).worksheet(sheet_name)
    except Exception as e:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}': {e}")
        return None


def append_transaction(tx_data: dict):
    """Thêm 1 giao dịch mới vào sheet Transactions"""
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
    """Lấy giá token từ Dexscreener API (free, không cần key)"""
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
            pairs = data['pairs']

        best_pair = max(pairs, key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0))

        return {
            'price': float(best_pair.get('priceUsd', 0) or 0),
            'price_change_24h': float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
            'volume_24h': float(best_pair.get('volume', {}).get('h24', 0) or 0),
            'liquidity': float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
            'fdv': float(best_pair.get('fdv', 0) or 0),
            'pair_url': best_pair.get('url', ''),
            'error': None
        }
    except Exception as e:
        return {'price': 0, 'error': str(e)}


def update_portfolio_prices():
    """Cập nhật giá hiện tại cho tất cả token trong Portfolio"""
    sheet = get_sheet('Portfolio')
    if not sheet:
        return 0

    df = load_dataframe('Portfolio')
    if df.empty:
        return 0

    updated = 0
    for idx, row in df.iterrows():
        contract = row.get('Contract', '')
        network = row.get('Mạng', '')
        if not contract or not network:
            continue

        result = fetch_price_dexscreener(contract, network)
        if result['price'] > 0:
            sheet.update_cell(idx + 2, 9, result['price'])
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
         "📜 Lịch Sử", "🔔 Cảnh Báo", "⚙️ Cài Đặt"]
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

    if SHEET_ID and os.path.exists(CREDS_FILE):
        st.caption("🟢 Kết nối Google Sheets OK")
    else:
        st.caption("🔴 Chưa cấu hình .env")


# ====================== PAGE: DASHBOARD ======================
if page == "📊 Dashboard":
    st.title("📊 Dashboard Tổng Quan")

    df_pf = load_dataframe('Portfolio')

    if df_pf.empty:
        st.warning("⚠️ Chưa có dữ liệu. Vào 'Thêm Giao Dịch' để bắt đầu.")
    else:
        money_cols = ['Tổng Chi USD', 'Giá Trị Hiện Tại', 'P&L USD',
                      'Giá TB Mua', 'Giá Hiện Tại', 'SL Đang Giữ']
        for col in money_cols:
            if col in df_pf.columns:
                df_pf[col] = df_pf[col].apply(clean_number)

        if 'P&L %' in df_pf.columns:
            df_pf['P&L %'] = df_pf['P&L %'].apply(clean_number)
            if df_pf['P&L %'].abs().max() < 1 and df_pf['P&L %'].abs().max() > 0:
                df_pf['P&L %'] = df_pf['P&L %'] * 100

        total_cost = df_pf['Tổng Chi USD'].sum()
        total_value = df_pf['Giá Trị Hiện Tại'].sum()
        total_pnl = total_value - total_cost
        roi = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        num_tokens = (len(df_pf[df_pf['SL Đang Giữ'] > 0])
                      if 'SL Đang Giữ' in df_pf.columns else len(df_pf))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 Vốn Đầu Tư", format_money(total_cost))
        col2.metric("📈 Giá Trị Hiện Tại", format_money(total_value),
                    f"{total_pnl:+,.2f}")
        col3.metric("💵 P&L Tổng", format_money(total_pnl), format_pct(roi))
        col4.metric("🪙 Số Token", f"{num_tokens}")

        st.markdown("---")

        # Cảnh báo concentration risk
        if 'Mạng' in df_pf.columns and total_value > 0:
            chain_alloc = df_pf.groupby('Mạng')['Giá Trị Hiện Tại'].sum()
            max_chain = chain_alloc.idxmax()
            max_pct = chain_alloc.max() / total_value * 100

            if max_pct > 70:
                st.error(f"🚨 **CẢNH BÁO TẬP TRUNG RỦI RO CAO**: {max_pct:.1f}% vốn đang ở **{max_chain}**. "
                         f"Khuyến nghị rebalance, không nên để 1 chain > 50%.")
            elif max_pct > 50:
                st.warning(f"⚠️ **Cảnh báo**: {max_pct:.1f}% vốn đang ở **{max_chain}**. "
                           f"Cân nhắc đa dạng hóa.")

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("🚀 Top Lãi")
            cols_show = ['Token', 'Mạng', 'P&L USD', 'P&L %']
            available_cols = [c for c in cols_show if c in df_pf.columns]
            winners = df_pf.nlargest(5, 'P&L USD')[available_cols].copy()
            winners['P&L USD'] = winners['P&L USD'].apply(format_money)
            winners['P&L %'] = winners['P&L %'].apply(format_pct)
            st.dataframe(winners, use_container_width=True, hide_index=True)

        with col_b:
            st.subheader("📉 Top Lỗ")
            losers = df_pf.nsmallest(5, 'P&L USD')[available_cols].copy()
            losers['P&L USD'] = losers['P&L USD'].apply(format_money)
            losers['P&L %'] = losers['P&L %'].apply(format_pct)
            st.dataframe(losers, use_container_width=True, hide_index=True)

        st.markdown("---")

        col_c, col_d = st.columns([2, 3])
        with col_c:
            st.subheader("🌐 Phân Bổ Theo Mạng")
            network_alloc = df_pf.groupby('Mạng')['Giá Trị Hiện Tại'].sum().reset_index()
            network_alloc = network_alloc[network_alloc['Giá Trị Hiện Tại'] > 0]
            network_alloc['%'] = (network_alloc['Giá Trị Hiện Tại'] /
                                   network_alloc['Giá Trị Hiện Tại'].sum() * 100).round(2)
            network_alloc['Giá Trị Hiện Tại'] = network_alloc['Giá Trị Hiện Tại'].apply(format_money)
            network_alloc['%'] = network_alloc['%'].apply(lambda x: f"{x:.2f}%")
            st.dataframe(network_alloc, use_container_width=True, hide_index=True)

        with col_d:
            st.subheader("📊 Tỷ Trọng Vốn")
            chain_data = df_pf.groupby('Mạng')['Giá Trị Hiện Tại'].sum()
            chain_data = chain_data[chain_data > 0].sort_values(ascending=False)
            if not chain_data.empty:
                # Dùng progress bar thay cho bar chart để tránh lỗi Vega
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
                              f"FDV: **${result['fdv']:,.0f}**")
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
            st.info(f"💵 **Tổng giá trị**: ${amount * price:,.4f} + phí ${gas_fee:.4f} = "
                   f"**${amount * price + gas_fee:,.4f}**")

        note = st.text_area("📝 Ghi chú", placeholder="VD: DCA lần 3, mua khi dump")

        submitted = st.form_submit_button("✅ Lưu Giao Dịch", type="primary",
                                          use_container_width=True)

        if submitted:
            if not token or not contract or amount <= 0 or price <= 0:
                st.error("❌ Vui lòng điền đầy đủ: Token, Contract, Số lượng, Giá!")
            else:
                tx_data = {
                    'date': tx_date.strftime('%Y-%m-%d'),
                    'type': tx_type,
                    'token': token.upper(),
                    'network': network,
                    'contract': contract,
                    'amount': amount,
                    'price': price,
                    'pay_with': pay_with,
                    'gas_fee': gas_fee,
                    'tx_hash': tx_hash,
                    'note': note
                }
                if append_transaction(tx_data):
                    st.success(f"✅ Đã lưu giao dịch **{tx_type} {amount:,.0f} {token}** "
                              f"@ ${price:.10f}")
                    st.balloons()


# ====================== PAGE: PORTFOLIO ======================
elif page == "📋 Portfolio":
    st.title("📋 Chi Tiết Danh Mục")

    df_pf = load_dataframe('Portfolio')
    if df_pf.empty:
        st.warning("⚠️ Chưa có dữ liệu.")
    else:
        money_cols = ['Tổng Chi USD', 'Giá Trị Hiện Tại', 'P&L USD',
                      'Giá TB Mua', 'Giá Hiện Tại', 'SL Đang Giữ']
        for col in money_cols:
            if col in df_pf.columns:
                df_pf[col] = df_pf[col].apply(clean_number)
        if 'P&L %' in df_pf.columns:
            df_pf['P&L %'] = df_pf['P&L %'].apply(clean_number)
            if df_pf['P&L %'].abs().max() < 1 and df_pf['P&L %'].abs().max() > 0:
                df_pf['P&L %'] = df_pf['P&L %'] * 100

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            filter_network = st.multiselect("🌐 Lọc mạng",
                                            options=df_pf['Mạng'].unique(),
                                            default=df_pf['Mạng'].unique())
        with col2:
            sort_by = st.selectbox("🔃 Sắp xếp theo",
                                    ['P&L USD ↓', 'P&L USD ↑', 'P&L % ↓', 'P&L % ↑',
                                     'Giá Trị ↓', 'Token A-Z'])
        with col3:
            show_only_holding = st.checkbox("Chỉ đang giữ", value=True)

        df_filtered = df_pf[df_pf['Mạng'].isin(filter_network)].copy()

        if show_only_holding and 'SL Đang Giữ' in df_filtered.columns:
            df_filtered = df_filtered[df_filtered['SL Đang Giữ'] > 0]

        sort_map = {
            'P&L USD ↓': ('P&L USD', False), 'P&L USD ↑': ('P&L USD', True),
            'P&L % ↓': ('P&L %', False), 'P&L % ↑': ('P&L %', True),
            'Giá Trị ↓': ('Giá Trị Hiện Tại', False), 'Token A-Z': ('Token', True),
        }
        if sort_by in sort_map:
            col, asc = sort_map[sort_by]
            if col in df_filtered.columns:
                df_filtered = df_filtered.sort_values(col, ascending=asc)

        st.dataframe(df_filtered, use_container_width=True, hide_index=True,
                     column_config={
                         "Tổng Chi USD": st.column_config.NumberColumn(format="$%.2f"),
                         "Giá TB Mua": st.column_config.NumberColumn(format="$%.10f"),
                         "Giá Hiện Tại": st.column_config.NumberColumn(format="$%.10f"),
                         "Giá Trị Hiện Tại": st.column_config.NumberColumn(format="$%.2f"),
                         "P&L USD": st.column_config.NumberColumn(format="$%.2f"),
                         "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
                     })


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

        st.caption(f"📌 Hiển thị {len(df_show)}/{len(df_tx)} giao dịch")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        csv = df_show.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 Tải xuống CSV (đã filter)",
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

    st.subheader("🔑 Kết Nối Hiện Tại")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Google Sheet ID", value=SHEET_ID if SHEET_ID else "(chưa cấu hình)",
                      disabled=True)
        st.text_input("Credentials file", value=CREDS_FILE, disabled=True)
    with col2:
        tg_token_display = os.getenv('TELEGRAM_BOT_TOKEN', '')
        st.text_input("Telegram Bot Token",
                      value=(tg_token_display[:10] + "...") if tg_token_display else "(chưa cấu hình)",
                      disabled=True)
        st.text_input("Telegram Chat ID",
                      value=os.getenv('TELEGRAM_CHAT_ID', '(chưa cấu hình)'),
                      disabled=True)

    st.markdown("---")

    st.subheader("📱 Test Telegram")
    if st.button("📤 Test gửi tin nhắn", type="primary"):
        tg_token = os.getenv('TELEGRAM_BOT_TOKEN')
        tg_chat_id = os.getenv('TELEGRAM_CHAT_ID')
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
            st.warning("⚠️ Chưa cấu hình Telegram trong .env")

    st.markdown("---")
    st.subheader("📊 Thông tin Sheet")
    if st.button("🔍 Kiểm tra kết nối"):
        client = get_gsheet_client()
        if client and SHEET_ID:
            try:
                ss = client.open_by_key(SHEET_ID)
                st.success(f"✅ Kết nối OK!")
                st.write(f"**File**: {ss.title}")
                st.write(f"**URL**: {ss.url}")
                st.write(f"**Các sheet**: {', '.join([s.title for s in ss.worksheets()])}")
            except Exception as e:
                st.error(f"❌ {e}")

    st.markdown("---")
    st.subheader("📖 Hướng Dẫn Setup")
    st.markdown("""
    1. **Google Sheets API**: Tạo project trên Google Cloud Console, bật `Google Sheets API` và `Google Drive API`, tạo Service Account, tải file JSON
    2. **Share Sheet**: Share Google Sheet (quyền Editor) cho email service account
    3. **Telegram Bot**: Chat với @BotFather → `/newbot` → lấy token. Chat với @userinfobot để lấy Chat ID
    4. **File .env**: Đặt `GOOGLE_SHEET_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
    5. **Chạy bot real-time**: `python price_updater.py` (mở terminal khác)
    """)