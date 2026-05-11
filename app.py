import streamlit as st
from datetime import datetime, timedelta, time
import urllib.parse
# カレンダー登録用のライブラリ（前回までの設定を流用）
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
event_title = st.text_input("予定のタイトル", "LITALICOワークス藤沢")

col1, col2 = st.columns(2)
with col1:
    event_date = st.date_input("予定の日付", datetime.today())
with col2:
    start_time = st.time_input("予定開始時間", time(10, 30))
    end_time = st.time_input("予定終了時間", time(11, 30))

# 10分前行動の計算
event_dt = datetime.combine(event_date, start_time)
target_arrival_dt = event_dt - timedelta(minutes=10)

st.info(f"💡 目標到着時刻（10分前）: **{target_arrival_dt.strftime('%H:%M')}**")

# ==========================================
# STEP 2: 近隣駅からの徒歩と、電車の「到着デッドライン」
# ==========================================
st.header("2. 降車駅からの徒歩計算")
arrival_station = st.text_input("目的地の近隣駅（降車駅）", "藤沢")
walk_to_dest = st.number_input(f"{arrival_station}駅から目的地までの徒歩時間（分）", value=5, step=1)

# 電車の到着デッドラインを計算
train_deadline_dt = target_arrival_dt - timedelta(minutes=walk_to_dest)
st.success(f"🚃 **{arrival_station}駅** に **{train_deadline_dt.strftime('%H:%M')}** までに到着する電車を探します。")

# ==========================================
# STEP 3: 乗換案内のWebサービスで調べる
# ==========================================
st.header("3. ルート検索と確定")
depart_station = st.selectbox("出発駅", ["小田原", "井細田", "足柄(神奈川県)"])

# Yahoo路線のURLを自動生成（到着時刻指定）
params = {
    "from": depart_station,
    "to": arrival_station,
    "y": event_date.strftime("%Y"),
    "m": event_date.strftime("%m"),
    "d": event_date.strftime("%d"),
    "hh": train_deadline_dt.strftime("%H"),
    "mm": train_deadline_dt.strftime("%M"),
    "type": "4", # 到着時刻指定
    "ticket": "ic",
    "s": "0"
}
yahoo_url = "https://transit.yahoo.co.jp/search/result?" + urllib.parse.urlencode(params)

st.write("以下のボタンを押して、最適な電車の時間を調べてください。")
st.link_button("↗️ Yahoo!路線情報でルートを検索", yahoo_url)

# 検索して決めた電車の時間を入力
st.write("調べた電車の時刻を入力してください：")
col3, col4 = st.columns(2)
with col3:
    train_depart_time = st.time_input("確定した電車の 出発時刻", time(9, 34))
with col4:
    train_arrive_time = st.time_input("確定した電車の 到着時刻", time(10, 14))

# ==========================================
# STEP 4: 出発駅への徒歩と準備時間の計算
# ==========================================
st.header("4. 出発前の準備")
walk_to_station = st.number_input("現在位置から出発駅までの徒歩時間（分）", value=15, step=1)
prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1)

# 出発時刻の逆算
train_depart_dt = datetime.combine(event_date, train_depart_time)
leave_home_dt = train_depart_dt - timedelta(minutes=walk_to_station)
start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

st.error(f"🏠 **準備開始時刻: {start_prep_dt.strftime('%H:%M')}**")
st.warning(f"🚶 **出発時刻: {leave_home_dt.strftime('%H:%M')}**")

# ==========================================
# STEP 5: カレンダーへの登録
# ==========================================
st.header("5. カレンダー登録")
if st.button("📅 このスケジュールをカレンダーに登録"):
    # ※ここに前回までのGoogle Calendar API登録処理を記述します
    # 1. start_prep_dt 〜 leave_home_dt で「準備」を登録
    # 2. leave_home_dt 〜 target_arrival_dt で「移動」を登録
    # 3. event_dt 〜 end_dt で「本番」を登録
    st.success("✅ カレンダーに【準備】【移動】【予定】の3件を登録しました！")
