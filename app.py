import streamlit as st
from datetime import datetime, timedelta
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Google Tasks APIの権限設定
SCOPES = ['https://www.googleapis.com/auth/tasks']

def get_tasks_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # credentials.jsonは後でアップロードします
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('tasks', 'v1', credentials=creds)

# --- UI部分 ---
st.title("🚉 移動準備リマインダー")

event_title = st.text_input("予定のタイトル", "都内ミーティング")
event_time = st.time_input("開始時刻")

# 10分単位のメニュー選択 ＋ 自由入力
prep_options = ["10分", "20分", "30分", "40分", "50分", "60分", "自由に直接入力"]
selected = st.selectbox("準備時間（何分前に通知しますか？）", prep_options, index=2)

if selected == "自由に直接入力":
    prep_min = st.number_input("分単位で入力", value=15, step=1)
else:
    prep_min = int(selected.replace("分", ""))

# 計算ロジック
target_dt = datetime.combine(datetime.today(), event_time)
ready_dt = target_dt - timedelta(minutes=prep_min)

st.info(f"⏰ {ready_dt.strftime('%H:%M')} に準備開始リマインダーをセットします")

if st.button("iPhoneリマインダーに登録"):
    try:
        service = get_tasks_service()
        task_time = f"{datetime.today().strftime('%Y-%m-%d')}T{ready_dt.strftime('%H:%M:%S')}Z"
        task = {
            'title': f"【準備開始】{event_title}",
            'due': task_time
        }
        service.tasks().insert(tasklist='@default', body=task).execute()
        st.success("✅ 登録しました！iPhoneを確認してください。")
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
        st.info("※credentials.jsonが正しく配置されているか確認してください。")
