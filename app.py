import streamlit as st
import json
import pandas as pd
import re
from datetime import datetime, timedelta, time
import urllib.parse
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

st.set_page_config(page_title="スケジュール＆移動ルーター", layout="centered")

st.title("🗓 スケジュール＆移動ルーター")
st.write("確実な手順で、嘘のないスケジュールをカレンダーに登録します。")

# ==========================================
# STEP 1: 予定開始時間と目的地の設定
# ==========================================
st.header("1. 予定と目的地の設定")

event_title = st.text_input("予定のタイトル", "面談")
facility_name = st.text_input("施設名（目的地）", "LITALICOワークス藤沢")
event_address_full = st.text_input("目的地住所", "神奈川県藤沢市南藤沢5-9 朝日生命藤沢ビル4F")

st.write("---")
st.write("📅 **予定の日時**")
event_date = st.date_input("予定の日付", datetime.today())

st.write("🕒 **予定開始時間**")
col_s_h, col_s_m = st.columns(2)
with col_s_h:
    start_hour = st.selectbox("開始（時）", [f"{i:02d}" for i in range(24)], index=10)
with col_s_m:
    start_minute = st.selectbox("開始（分）", [f"{i:02d}" for i in range(60)], index=30)
start_time = time(int(start_hour), int(start_minute))

st.write("🕒 **予定終了時間**")
col_e_h, col_e_m = st.columns(2)
with col_e_h:
    end_hour = st.selectbox("終了（時）", [f"{i:02d}" for i in range(24)], index=11)
with col_e_m:
    end_minute = st.selectbox("終了（分）", [f"{i:02d}" for i in range(60)], index=30)
end_time = time(int(end_hour), int(end_minute))

# --- 目標到着時間の選択機能 ---
st.write("---")
st.write("🕒 **目標到着時間の選択**")
arrival_buffer_option = st.selectbox(
    "予定開始の何分前に到着しますか？",
    ["5分前", "10分前", "15分前", "20分前", "自由入力（分）"],
    index=1
)

if arrival_buffer_option == "自由入力（分）":
    buffer_minutes = st.number_input("到着バッファを入力（分単位）", value=30, min_value=0, step=1)
else:
    buffer_minutes = int(re.search(r'\d+', arrival_buffer_option).group())

event_dt = datetime.combine(event_date, start_time)
target_arrival_dt = event_dt - timedelta(minutes=buffer_minutes)

st.info(f"💡 目標到着時刻（{buffer_minutes}分前）: **{target_arrival_dt.strftime('%H:%M')}**")

# ==========================================
# STEP 2: 近隣駅からの徒歩と電車の到着デッドライン
# ==========================================
st.header("2. 降車駅からの徒歩計算")
arrival_station = st.text_input("目的地の近隣駅（降車駅）", "藤沢")
walk_to_dest = st.number_input(f"{arrival_station}駅から目的地までの徒歩時間（分）", value=5, step=1)

train_deadline_dt = target_arrival_dt - timedelta(minutes=walk_to_dest)
st.success(f"🚃 **{arrival_station}駅** に **{train_deadline_dt.strftime('%H:%M')}** までに到着する電車を探します。")

# ==========================================
# STEP 3: 乗換案内のWebサービスで調べる
# ==========================================
st.header("3. ルート検索と確定")

# 🚉 出発駅リストの管理（並び替え・削除・編集テーブル）
st.write("▼ 出発駅の候補リスト")
st.caption("【使い方】追加：一番下をクリック / 並び替え：「順番」を変更 / 削除：「削除」にチェックして下のボタンを押す")

if "station_df" not in st.session_state:
    st.session_state.station_df = pd.DataFrame({
        "削除": [False, False, False],
        "順番": [1, 2, 3],
        "出発駅名": ["小田原", "井細田", "足柄(神奈川県)"]
    })

edited_df = st.data_editor(
    st.session_state.station_df,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "削除": st.column_config.CheckboxColumn("🗑️ 削除", default=False, width="small"),
        "順番": st.column_config.NumberColumn("順番", min_value=1, step=1, width="small"),
        "出発駅名": st.column_config.TextColumn("🚉 出発駅名（必須）", required=True),
    }
)

if st.button("🗑️ チェックした駅をリストから削除"):
    new_df = edited_df[~edited_df["削除"]].copy()
    sorted_df = new_df.sort_values(by="順番", na_position='last').reset_index(drop=True)
    sorted_df["削除"] = False
    st.session_state.station_df = sorted_df
    st.rerun()

sorted_df = edited_df.sort_values(by="順番", na_position='last').reset_index(drop=True)
st.session_state.station_df = sorted_df

valid_stations = [s for s in sorted_df["出発駅名"].tolist() if s and str(s).strip() != ""]

if not valid_stations:
    st.warning("出発駅の候補を1つ以上入力してください。")
    st.stop()

depart_station = st.selectbox("今回利用する出発駅", valid_stations)

# ジョルダン乗換案内のURLを自動生成（到着時刻指定: Cway=1）
jorudan_params = {
    "eki1": depart_station,
    "eki2": arrival_station,
    "Dym": event_date.strftime("%Y%m"), 
    "Ddd": event_date.strftime("%d"),   
    "Dhh": train_deadline_dt.strftime("%H"), 
    "Dmn1": str(train_deadline_dt.minute // 10), 
    "Dmn2": str(train_deadline_dt.minute % 10),  
    "Cway": "1", 
    "Cfp": "1"
}
jorudan_url = "https://www.jorudan.co.jp/norikae/cgi/nori.cgi?" + urllib.parse.urlencode(jorudan_params, encoding='utf-8')

st.write("以下のボタンを押して、最適な電車の時間を調べてください。")
st.link_button("↗️ ジョルダン乗換案内でルートを検索", jorudan_url)

st.write("---")
st.write("▼ 調べた電車の時刻を入力してください")

st.write("🚃 **確定した電車の 出発時刻**")
col_td_h, col_td_m = st.columns(2)
with col_td_h:
    train_depart_hour = st.selectbox("出発（時）", [f"{i:02d}" for i in range(24)], index=9)
with col_td_m:
    train_depart_minute = st.selectbox("出発（分）", [f"{i:02d}" for i in range(60)], index=34)
train_depart_time = time(int(train_depart_hour), int(train_depart_minute))

st.write("🚃 **確定した電車の 到着時刻**")
col_ta_h, col_ta_m = st.columns(2)
with col_ta_h:
    train_arrive_hour = st.selectbox("到着（時）", [f"{i:02d}" for i in range(24)], index=10)
with col_ta_m:
    train_arrive_minute = st.selectbox("到着（分）", [f"{i:02d}" for i in range(60)], index=14)
train_arrive_time = time(int(train_arrive_hour), int(train_arrive_minute))

# ==========================================
# STEP 4: 出発駅への徒歩と準備時間の計算
# ==========================================
st.header("4. 出発前の準備")

st.write("▼ 現在地（スマホのGPS）から各候補駅までの徒歩時間を調べます")
for station in valid_stations:
    station_route_url = f"https://www.google.com/maps/dir/?api=1&destination={urllib.parse.quote(station + '駅')}&travelmode=walking"
    st.link_button(f"📍 現在地 から 【{station}駅】 までの徒歩ルート", station_route_url)

st.write("---")
st.write("▼ 🏠 自宅からの徒歩時間（ワンタッチ入力）")

if "walk_time" not in st.session_state:
    st.session_state.walk_time = 15

def set_walk_time(mins):
    st.session_state.walk_time = mins

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.button("🏠 井細田 (5分)", on_click=set_walk_time, args=(5,), use_container_width=True)
with col_b:
    st.button("🏠 足柄 (15分)", on_click=set_walk_time, args=(15,), use_container_width=True)
with col_c:
    st.button("🏠 小田原 (28分)", on_click=set_walk_time, args=(28,), use_container_width=True)

walk_to_station = st.number_input("現在地から【利用する出発駅】までの徒歩時間（分）", key="walk_time", step=1)
prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1)

train_depart_dt = datetime.combine(event_date, train_depart_time)
leave_home_dt = train_depart_dt - timedelta(minutes=walk_to_station)
start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

st.error(f"🏠 **準備開始時刻: {start_prep_dt.strftime('%H:%M')}**")
st.warning(f"🚶 **出発時刻: {leave_home_dt.strftime('%H:%M')}**")

# ==========================================
# STEP 5: カレンダーへの登録（本番クラウド対応版）
# ==========================================
st.header("5. カレンダー登録")
end_dt = datetime.combine(event_date, end_time)

if st.button("📅 このスケジュールをカレンダーに登録"):
    try:
        with st.spinner("Googleカレンダーに通信中..."):
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds = None
            
            if "GOOGLE_TOKEN_JSON" in st.secrets:
                token_info = json.loads(st.secrets["GOOGLE_TOKEN_JSON"])
                creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    st.error("❌ 認証エラー: 再度 Codespaces で token.json を取得し直して Secrets を更新してください。")
                    st.stop()

            service = build('calendar', 'v3', credentials=creds)

            def insert_event(summary, start_datetime, end_datetime, location=""):
                event_body = {
                    'summary': summary,
                    'location': location,
                    'start': {
                        'dateTime': start_datetime.isoformat(),
                        'timeZone': 'Asia/Tokyo',
                    },
                    'end': {
                        'dateTime': end_datetime.isoformat(),
                        'timeZone': 'Asia/Tokyo',
                    },
                }
                service.events().insert(calendarId='primary', body=event_body).execute()

            insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
            insert_event(f"🚃 移動：{event_title}", leave_home_dt, target_arrival_dt)
            
            full_location = f"{facility_name} {event_address_full}".strip()
            insert_event(event_title, event_dt, end_dt, location=full_location)

        st.success("✅ カレンダーに【準備】【移動】【本番】の3つの予定を登録しました！")
        st.balloons()

    except Exception as e:
        st.error("❌ カレンダーへの登録に失敗しました。")
        st.code(e)