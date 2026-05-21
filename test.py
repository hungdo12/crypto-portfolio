"""Script debug kết nối Google Sheets - chạy: python test_connection.py"""
import os
import json
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread

load_dotenv()

print("=" * 60)
print("🔍 DEBUG KẾT NỐI GOOGLE SHEETS")
print("=" * 60)

# Step 1: Check .env
SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '').strip()
CREDS_FILE = os.getenv('GOOGLE_CREDS_FILE', 'credentials.json').strip()

print(f"\n[1] SHEET_ID: '{SHEET_ID}'")
print(f"    Độ dài: {len(SHEET_ID)} ký tự (chuẩn ~44)")
print(f"[2] CREDS_FILE: '{CREDS_FILE}'")

# Step 2: Check file credentials tồn tại
if not os.path.exists(CREDS_FILE):
    print(f"\n❌ KHÔNG TÌM THẤY FILE '{CREDS_FILE}'!")
    print(f"   Thư mục hiện tại: {os.getcwd()}")
    print(f"   Các file có ở đây: {[f for f in os.listdir('.') if not f.startswith('.')]}")
    exit()
else:
    print(f"\n✅ File credentials tồn tại")

# Step 3: Đọc credentials, lấy email
try:
    with open(CREDS_FILE) as f:
        creds_data = json.load(f)
    email = creds_data.get('client_email', '???')
    project = creds_data.get('project_id', '???')
    print(f"\n[3] Service Account Email:")
    print(f"    {email}")
    print(f"    Project: {project}")
    print(f"\n⚠️  ĐẢM BẢO email này đã được share Editor trong Google Sheet!")
except Exception as e:
    print(f"❌ Lỗi đọc credentials: {e}")
    exit()

# Step 4: Authenticate
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
try:
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    print(f"\n✅ Authenticate thành công")
except Exception as e:
    print(f"\n❌ Lỗi authenticate: {e}")
    exit()

# Step 5: Mở Sheet
try:
    print(f"\n[4] Đang mở Sheet ID: {SHEET_ID}")
    spreadsheet = client.open_by_key(SHEET_ID)
    print(f"✅ MỞ FILE THÀNH CÔNG!")
    print(f"   Tên file: {spreadsheet.title}")
    print(f"   URL: {spreadsheet.url}")
except gspread.exceptions.APIError as e:
    print(f"\n❌ APIError khi mở file:")
    print(f"   {e}")
    print(f"\n💡 Phân tích lỗi:")
    err_str = str(e)
    if '404' in err_str:
        print("   → Lỗi 404: Drive API chưa bật, hoặc SHEET_ID sai")
    elif '403' in err_str:
        print("   → Lỗi 403: Chưa share quyền Editor cho service account")
        print(f"   → Share Sheet cho email: {email}")
    elif 'PERMISSION_DENIED' in err_str:
        print("   → Service account không có quyền truy cập file")
    exit()
except Exception as e:
    print(f"\n❌ Lỗi khác: {e}")
    exit()

# Step 6: List các sheet bên trong
try:
    sheets = spreadsheet.worksheets()
    print(f"\n[5] Các sheet tab bên trong file ({len(sheets)} sheet):")
    for s in sheets:
        print(f"   📄 '{s.title}'")

    expected = ['Dashboard', 'Transactions', 'Portfolio', 'Alerts']
    print(f"\n[6] Check sheet bắt buộc:")
    sheet_names = [s.title for s in sheets]
    for name in expected:
        if name in sheet_names:
            print(f"   ✅ '{name}' tồn tại")
        else:
            print(f"   ❌ '{name}' KHÔNG tồn tại - cần đổi tên hoặc tạo sheet này")

    # Test đọc data
    print(f"\n[7] Test đọc Portfolio sheet:")
    pf = spreadsheet.worksheet('Portfolio')
    data = pf.get_all_records()
    print(f"   ✅ Đọc được {len(data)} dòng")
    if data:
        print(f"   Cột: {list(data[0].keys())}")

    print(f"\n{'=' * 60}")
    print("🎉 TẤT CẢ OK! App phải chạy được rồi.")
    print(f"{'=' * 60}")
except Exception as e:
    print(f"\n❌ Lỗi list sheets: {e}")