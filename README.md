# 💰 Crypto Portfolio Manager

App quản lý đầu tư crypto: theo dõi giá mua, tính P&L tự động, cảnh báo Telegram, đồng bộ Google Sheets.

## 🎯 Tính năng

- ✅ **Quản lý danh mục đa chain**: ETH, BSC, BASE, Soneium, Arbitrum, Katana, Polygon
- ✅ **Tự động tính giá trung bình** (weighted average - có tính cả phí gas)
- ✅ **Lấy giá real-time** từ Dexscreener (miễn phí, không cần API key)
- ✅ **Tính P&L** lãi/lỗ tự động theo từng token và tổng danh mục
- ✅ **Cảnh báo Telegram** khi giá chạm target (chốt lời/cắt lỗ)
- ✅ **Phân bổ theo network** - xem tỷ trọng vốn ở mỗi chain
- ✅ **Lịch sử giao dịch** đầy đủ, export CSV
- ✅ **Đồng bộ Google Sheets** - xem mọi lúc mọi nơi trên điện thoại

## 📦 Cấu trúc

```
crypto_portfolio/
├── app.py                          # UI Streamlit (web app)
├── price_updater.py                # Bot chạy nền update giá + alert
├── create_template.py              # Tạo template Excel
├── Crypto_Portfolio_Template.xlsx  # Template để upload Google Sheets
├── requirements.txt                # Thư viện cần cài
├── .env.example                    # Mẫu file config
└── README.md                       # File này
```

## 🚀 Setup Bước-Bước

### Bước 1: Cài Python và thư viện

```bash
# Cài Python 3.9+ trước
pip install -r requirements.txt
```

### Bước 2: Upload template lên Google Sheets

1. Vào [Google Drive](https://drive.google.com), tạo folder mới (VD: "Crypto Portfolio")
2. Upload file `Crypto_Portfolio_Template.xlsx` lên
3. Click chuột phải file → "Open with" → "Google Sheets"
4. File → "Save as Google Sheets" để chuyển thành định dạng Google Sheets
5. **Copy ID từ URL**: `https://docs.google.com/spreadsheets/d/[COPY_ĐOẠN_NÀY]/edit`

### Bước 3: Tạo Google Service Account (để Python truy cập Sheet)

1. Vào [Google Cloud Console](https://console.cloud.google.com)
2. Tạo project mới (VD: "crypto-portfolio")
3. Vào menu **APIs & Services** → **Library**:
   - Bật **Google Sheets API**
   - Bật **Google Drive API**
4. Vào **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
   - Tên: `crypto-bot`
   - Vai trò: `Editor`
5. Tạo xong, click vào Service Account vừa tạo → tab **Keys** → **Add Key** → **JSON**
6. File JSON sẽ tải về, đổi tên thành `credentials.json` và đặt vào thư mục project
7. **QUAN TRỌNG**: Mở file `credentials.json`, copy email trong field `client_email` (dạng `xxx@xxx.iam.gserviceaccount.com`)
8. Mở Google Sheet của bạn → Click **Share** → Paste email → chọn quyền **Editor**

### Bước 4: Tạo Telegram Bot

1. Mở Telegram, chat với [@BotFather](https://t.me/BotFather)
2. Gõ `/newbot` → đặt tên → bot tạo xong sẽ cho bạn **TOKEN**
3. Chat với [@userinfobot](https://t.me/userinfobot) để lấy **Chat ID**

### Bước 5: Cấu hình .env

```bash
cp .env.example .env
```

Mở file `.env` và điền:
```env
GOOGLE_SHEET_ID=1xKpQ...          # ID lấy từ URL Sheet ở Bước 2
GOOGLE_CREDS_FILE=credentials.json
TELEGRAM_BOT_TOKEN=1234:ABC...     # Token từ Bước 4
TELEGRAM_CHAT_ID=123456789         # Chat ID từ Bước 4
UPDATE_INTERVAL_SECONDS=300        # 5 phút update 1 lần
```

### Bước 6: Chạy app

**Terminal 1** - Mở web UI:
```bash
streamlit run app.py
```
→ Mở trình duyệt http://localhost:8501

**Terminal 2** - Chạy bot update giá + alert:
```bash
python price_updater.py
```

## 📊 Cách sử dụng

### Quy trình nhập 1 giao dịch mới

1. Mở web app → vào "➕ Thêm Giao Dịch"
2. Điền: ngày, loại (BUY/SELL), token, mạng, contract, số lượng, giá
3. Click "🔍 Lấy giá hiện tại" để check (optional)
4. Click "✅ Lưu" → Dữ liệu tự động đẩy lên Google Sheets

### Xem báo cáo

- **Dashboard**: tổng quan toàn portfolio (vốn, P&L, ROI, phân bổ)
- **Portfolio**: chi tiết từng token với giá TB, P&L %
- **Google Sheets**: mở từ điện thoại, xem mọi lúc mọi nơi

### Đặt cảnh báo Telegram

1. Vào tab "🔔 Cảnh Báo"
2. Thêm alert mới: chọn token, loại (TAKE_PROFIT / STOP_LOSS), giá trigger
3. Bot sẽ check mỗi 5 phút, khi giá chạm sẽ gửi Telegram

## 🧮 Công thức giá trung bình

App dùng **weighted average** (trung bình có trọng số) - chuẩn DCA:

```
Giá TB = TỔNG (Số lượng × Giá mua + Phí gas) ÷ TỔNG Số lượng
```

**Ví dụ:**
- Mua lần 1: 1,000,000 PEPE @ $0.0000085 + gas $5.20 = chi $13.70
- Mua lần 2: 500,000 PEPE @ $0.0000095 + gas $4.80 = chi $9.55
- **Tổng**: 1,500,000 PEPE, chi $23.25
- **Giá TB** = $23.25 ÷ 1,500,000 = **$0.0000155 per PEPE**

Đây là cách tính đúng - khác với trung bình cộng đơn thuần.

## 🎨 Quy tắc màu trong Sheet

- 🔵 **Ô màu xanh dương**: Input - bạn nhập tay
- ⚫ **Ô màu đen**: Công thức - KHÔNG sửa
- 🟢 **Ô màu xanh lá**: Link sang sheet khác - KHÔNG sửa
- 🟡 **Ô nền vàng**: Giá hiện tại - bot Python tự cập nhật

## 🔥 Deploy lên Cloud (chạy 24/7)

### Streamlit Cloud (miễn phí)
1. Push code lên GitHub (private repo)
2. Vào [share.streamlit.io](https://share.streamlit.io)
3. Deploy từ repo → thêm secrets (env vars + credentials.json)

### Render / Railway (chạy bot 24/7)
- Deploy `price_updater.py` lên Render với worker
- Free tier OK nếu chỉ chạy 1 bot

## ❓ Troubleshooting

- **"Không tìm thấy sheet"** → Check đã share Sheet cho email service account chưa
- **"403 Forbidden"** → Bật Sheets API & Drive API trong Google Cloud Console
- **Giá không update** → Check contract address chính xác chưa, network có support Dexscreener không
- **Telegram không gửi** → Bạn phải /start với bot trước, sau đó bot mới gửi được tin

## 📝 TODO (mở rộng sau)

- [ ] Thêm sàn CEX (Binance/OKX) qua API
- [ ] Tích hợp ví thật để auto-fetch giao dịch on-chain
- [ ] Biểu đồ P&L theo thời gian (line chart)
- [ ] Tax report (FIFO/LIFO cost basis)
- [ ] So sánh performance với BTC/ETH benchmark
