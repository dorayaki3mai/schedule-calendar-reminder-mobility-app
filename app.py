import streamlit as st
from datetime import datetime, timedelta, time
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 権限設定（Tasks と Calendar 両方）
SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/calendar.events'
]

def get_google_services():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=8080)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return build('tasks', 'v1', credentials=creds), build('calendar', 'v3', credentials=creds)

# --- UI部分 ---
st.title("🗓 スケジュール＆準備リマインダー")

event_title = st.text_input("予定のタイトル", "都内ミーティング")

# 日付と時刻を別々に設定可能に修正
col1, col2 = st.columns(2)
with col1:
    event_date = st.date_input("予定の日付", datetime.today())
with col2:
    event_time = st.time_input("開始時刻", time(10, 0)) # デフォルト10:00

prep_options = ["10分", "20分", "30分", "40分", "50分", "60分", "自由に直接入力"]
selected = st.selectbox("準備時間（何分前に通知しますか？）", prep_options, index=2)

if selected == "自由に直接入力":
    prep_min = st.number_input("分単位で入力", value=15, step=1)
else:
    prep_min = int(selected.replace("分", ""))

# --- 計算ロジック ---
# 日付と時刻を結合
target_dt = datetime.combine(event_date, event_time)
# 準備開始時間（リマインダー用）を計算
ready_dt = target_dt - timedelta(minutes=prep_min)
# 予定の終了時間（とりあえず1時間後）
end_dt = target_dt + timedelta(hours=1)

st.warning(f"🔔 {ready_dt.strftime('%m/%d %H:%M')} に準備リマインダーをセットします")

if st.button("カレンダーとリマインダーに同時登録"):
    try:
        t_service, c_service = get_google_services()
        
        # 日本時間のオフセット (+09:00)
        # Google APIが理解しやすいISO形式（+09:00付き）に変換
        jst_offset = "+09:00"
        target_iso = target_dt.isoformat() + jst_offset
        ready_iso = ready_dt.isoformat() + jst_offset
        end_iso = end_dt.isoformat() + jst_offset

        # 1. Google Tasks（ToDoリスト）への登録
        task = {
            'title': f"【準備開始】{event_title}",
            'due': ready_iso  # 期限としてセット
        }
        t_service.tasks().insert(tasklist='@default', body=task).execute()
        
        # 2. Google Calendar（予定）への登録
        event = {
            'summary': event_title,
            'description': '移動準備リマインダーアプリから登録',
            'start': {'dateTime': target_iso, 'timeZone': 'Asia/Tokyo'},
            'end': {'dateTime': end_iso, 'timeZone': 'Asia/Tokyo'},
        }
        c_service.events().insert(calendarId='primary', body=event).execute()

        st.success("✅ 登録完了！カレンダーとToDoリストを確認してください。")
        
    except Exception as e:
        st.error(f"登録に失敗しました: {e}")
