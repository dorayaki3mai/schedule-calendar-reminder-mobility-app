import streamlit as st
import streamlit.components.v1 as components
import json
import pandas as pd
import re
from datetime import datetime, timedelta, time
import urllib.parse
import os.path
# タイムゾーン操作用
import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
# --- GPS取得用のライブラリを追加 ---
from streamlit_js_eval import streamlit_js_eval

# ==========================================
# 0. システム設定（タイムゾーン）
# ==========================================
st.set_page_config(page_title="スケジュール＆移動ルーター", layout="centered")

st.sidebar.header("⚙️ システム設定")
# 一般的なタイムゾーンのリスト
tz_options = ["Asia/Tokyo", "UTC", "US/Pacific", "Europe/London", "Asia/Shanghai"]
selected_tz_str = st.sidebar.selectbox("アプリの基準タイムゾーン", tz_options, index=0)
app_tz = pytz.timezone(selected_tz_str)

# 現在時刻の取得（選択されたタイムゾーンに基づく）
now_with_tz = datetime.now(app_tz)

st.title("🗓 スケジュール＆移動ルーター")
st.write(f"現在の設定時刻: **{now_with_tz.strftime('%Y/%m/%d %H:%M:%S')}** ({selected_tz_str})")
st.write("確実な手順で、嘘のないスケジュールをカレンダーに登録します。")

# --- 住所クレンジング関数（ビル・マンション名以降をカット） ---
def clean_address(addr):
    if not addr: return ""
    # 1. 全角・半角スペース以降を削除
    addr = re.split(r'[ 　]', addr)[0]
    # 2. 番地・号の後に続く文字列を削除（例: 1-1-1〇〇ビル -> 1-1-1）
    addr = re.sub(r'([0-9０-９]+[-ー][0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+丁目[0-9０-９]+番[0-9０-９]+号?).*$', r'\1', addr)
    return addr

# ==========================================
# STEP 1: 予定開始時間と目的地の設定
# ==========================================
st.header("1. 予定と目的地の設定")

event_title = st.text_input("予定のタイトル", "")

# 施設名入力
facility_name = st.text_input("施設名（目的地）", "")
if facility_name:
    google_search_url = f"https://www.google.com/search?q={urllib.parse.quote(facility_name + ' 住所')}"
    st.link_button(f"🔍 「{facility_name}」の住所をGoogleで検索", google_search_url)

# 目的地住所（フル）
event_address_full = st.text_input("目的地住所（ビル・マンション名まで含む）", "")

# 住所の加工
cleaned_address = clean_address(event_address_full)
# 視覚確認用：ビル名を含むフル情報
full_destination_target = f"{facility_name} {event_address_full}".strip()

# --------------------------------------------------
# 地図表示と近隣駅入力
# --------------------------------------------------
if event_address_full:
    st.write("---")
    st.write(f"▼ 🗺️ 目的地のマップ（視覚的確認）")
    # APIキーなしで利用可能な埋め込みURL形式
    map_embed_url = f"https://www.google.com/maps?q={urllib.parse.quote(full_destination_target)}&output=embed"
    components.iframe(map_embed_url, height=350, scrolling=True)

    st.write("▼ 🚉 周辺の駅を探す")
    
    # 検索クエリ：周辺の駅 around:cleaned_address 
    nearby_search_query = f"周辺の駅 around:{cleaned_address}"
    nearby_station_url = f"https://www.google.com/maps/search/{urllib.parse.quote(nearby_search_query)}"
    
    # 駅を探すボタンを表示
    st.link_button("🔍 地図を開いて周辺の駅を探す（別タブ）", nearby_station_url, use_container_width=True)

    st.write("▼ 🚉 目的地の近隣駅を入力")
    arrival_station = st.text_input("地図を確認して近隣駅（降車駅）を入力してください", "", key="arrival_station_input")

    # 駅名が入力されたら、その駅から目的地までの徒歩ルートボタンを表示
    if arrival_station:
        route_search_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(arrival_station + '駅')}&destination={urllib.parse.quote(cleaned_address)}&travelmode=walking"
        st.link_button(f"🚶‍♂️ {arrival_station}駅から目的地までのルートを全画面で確認", route_search_url, use_container_width=True)
    else:
        st.caption("※上のボタンで駅を探し、駅名を入力するとルート確認ボタンが表示されます。")
            
# --- 以下、時間設定やカレンダー登録などのロジック ---
st.write("---")
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

st.write("---")
arrival_buffer_option = st.selectbox(
    "予定開始の何分前に到着しますか？",
    ["5分前", "10分前", "15分前", "20分前", "自由入力（分）"],
    index=1
)
if arrival_buffer_option == "自由入力（分）":
    buffer_minutes = st.number_input("到着バッファ（分）", value=30, min_value=0, step=1)
else:
    buffer_minutes = int(re.search(r'\d+', arrival_buffer_option).group())

event_dt = datetime.combine(event_date, start_time)
target_arrival_dt = event_dt - timedelta(minutes=buffer_minutes)
st.info(f"💡 目標到着時刻: **{target_arrival_dt.strftime('%H:%M')}**")

# ==========================================
# STEP 2: 降車駅からの徒歩計算
# ==========================================
st.header("2. 降車駅からの徒歩計算")
if 'arrival_station_input' in st.session_state:
    arrival_station = st.session_state.arrival_station_input
else:
    arrival_station = ""
st.write(f"🚉 選択された駅: **{arrival_station if arrival_station else '（未入力）'}**")
walk_to_dest = st.number_input(f"駅から目的地までの徒歩時間（分）", value=5, step=1)
train_deadline_dt = target_arrival_dt - timedelta(minutes=walk_to_dest)
st.success(f"🚃 **{arrival_station}駅** に **{train_deadline_dt.strftime('%H:%M')}** までに到着する電車を探します。")

# ==========================================
# STEP 3: ルート検索と確定
# ==========================================
st.header("3. ルート検索と確定")

# --- GPSを用いた現在地周辺の駅検索 ---
st.write("▼ 📍 現在地から出発駅を探す")
st.caption("スマートフォンのGPSを利用して、周辺の駅を検索します。")

# JavaScriptで位置情報を取得
loc = streamlit_js_eval(js_expressions="done(window.navigator.geolocation.getCurrentPosition(pos => { \
    const lat = pos.coords.latitude; \
    const lng = pos.coords.longitude; \
    done({lat, lng}); \
}))", key="get_location")

if loc:
    lat, lng = loc['lat'], loc['lng']
    gps_query = f"周辺の駅 around:{lat},{lng}"
    gps_map_url = f"https://www.google.com/maps/search/{urllib.parse.quote(gps_query)}"
    st.link_button("↗️ 現在地周辺の駅をGoogleMapで表示", gps_map_url, use_container_width=True)
else:
    st.info("⌛ 位置情報の利用を許可すると、現在地からの検索ボタンが表示されます。")

st.write("---")

# --- 出発駅候補リストの設定 ---
st.write("▼ 出発駅の候補リスト")
st.caption("【使い方】「削除」にチェックを入れて下のボタンを押すと一括削除できます。")

# 1. 履歴管理用の初期化
if "station_history" not in st.session_state:
    st.session_state.station_history = []

if "station_df" not in st.session_state:
    # 初期表示の列順：順番, 出発駅名, 削除
    st.session_state.station_df = pd.DataFrame([
        {"順番": 1, "出発駅名": "井細田", "削除": False},
        {"順番": 2, "出発駅名": "足柄(神奈川県)", "削除": False},
        {"順番": 3, "出発駅名": "小田原", "削除": False}
    ])

# 2. 履歴保存関数（★ここでタイムゾーンと日付を適用）
def save_to_history():
    snapshot = st.session_state.station_df.copy()
    # app_tz（設定したタイムゾーン）を適用し、日付と時間の形式で取得
    timestamp = datetime.now(app_tz).strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.station_history.insert(0, {"time": timestamp, "data": snapshot})
    if len(st.session_state.station_history) > 5:
        st.session_state.station_history = st.session_state.station_history[:5]

# 3. データエディタの表示（列の順番を制御）
edited_stations = st.data_editor(
    st.session_state.station_df,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_order=("順番", "出発駅名", "削除"),
    column_config={
        "順番": st.column_config.NumberColumn("順", width=60, min_value=1, format="%d"),
        "出発駅名": st.column_config.TextColumn("🚉 出発駅名", required=True),
        "削除": st.column_config.CheckboxColumn("削除", width="small"),
    },
    key="station_editor"
)

# 4. 削除・整列ボタン
col_btn1, col_btn2 = st.columns([1, 1])
with col_btn1:
    if st.button("🗑️ チェックした駅をリストから削除", use_container_width=True):
        if edited_stations["削除"].any():
            save_to_history()
            new_df = edited_stations[edited_stations["削除"] == False].copy()
            st.session_state.station_df = new_df
            st.rerun()

with col_btn2:
    if st.button("🔢 リストの順番を1から振り直す", use_container_width=True):
        save_to_history()
        sorted_df = edited_stations.sort_values("順番").reset_index(drop=True)
        sorted_df["順番"] = range(1, len(sorted_df) + 1)
        sorted_df["削除"] = False
        st.session_state.station_df = sorted_df
        st.rerun()

# 5. 復元機能
if st.session_state.station_history:
    with st.expander("⏪ 変更履歴から復元（直近5件・タイムスタンプ付）"):
        history_labels = [f"{i+1}: {h['time']} の状態に戻す" for i, h in enumerate(st.session_state.station_history)]
        selected_label = st.radio("どの時点に戻しますか？", history_labels)
        if st.button("選択した履歴を復元する"):
            idx = history_labels.index(selected_label)
            st.session_state.station_df = st.session_state.station_history[idx]["data"]
            st.rerun()

# 自動連番ロジック
if len(edited_stations) > len(st.session_state.station_df):
    last_order = edited_stations["順番"].max() if not edited_stations.empty else 0
    edited_stations["順番"] = edited_stations["順番"].fillna(last_order + 1)
    edited_stations["削除"] = edited_stations["削除"].fillna(False)
    st.session_state.station_df = edited_stations
    st.rerun()
else:
    st.session_state.station_df = edited_stations

# 出発駅の選択
valid_stations = [s for s in st.session_state.station_df["出発駅名"].tolist() if s and str(s).strip() != ""]
depart_station = st.selectbox("今回利用する出発駅", valid_stations if valid_stations else ["駅名を入力してください"])

# ジョルダン乗換案内のURL生成
jorudan_params = {
    "eki1": depart_station,
    "eki2": arrival_station,
    "Dym": event_date.strftime("%Y%m"), 
    "Ddd": event_date.strftime("%d"),   
    "Dhh": train_deadline_dt.strftime("%H"), 
    "Dmn1": str(train_deadline_dt.minute // 10), 
    "Dmn2": str(train_deadline_dt.minute % 10),  
    "Cway": "1"
}
jorudan_url = "https://www.jorudan.co.jp/norikae/cgi/nori.cgi?" + urllib.parse.urlencode(jorudan_params)
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
# STEP 4: 出発前の準備
# ==========================================
st.header("4. 出発前の準備")

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
# STEP 5: カレンダー登録
# ==========================================
st.header("5. カレンダー登録")
if st.button("📅 カレンダーに登録"):
    try:
        with st.spinner("Googleカレンダーに通信中..."):
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds = None
            if os.path.exists('token.json'):
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            elif "GOOGLE_TOKEN_JSON" in st.secrets:
                token_info = json.loads(st.secrets["GOOGLE_TOKEN_JSON"])
                creds = Credentials.from_authorized_user_info(token_info, SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    st.error("❌ 認証エラー: 再認証が必要です。")
                    st.stop()

            service = build('calendar', 'v3', credentials=creds)

            def insert_event(summary, start_datetime, end_datetime, location=""):
                event_body = {
                    'summary': summary,
                    'location': location,
                    'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'},
                    'end': {'dateTime': end_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'},
                }
                service.events().insert(calendarId='primary', body=event_body).execute()

            # --- 予定の3分割と算出ロジック ---
            train_arrive_dt = datetime.combine(event_date, train_arrive_time)
            
            if train_arrive_dt < train_depart_dt:
                train_arrive_dt += timedelta(days=1)
            
            actual_arrive_dt = train_arrive_dt + timedelta(minutes=walk_to_dest)

            # --- カレンダーへのイベント登録（5連続） ---
            insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
            insert_event(f"🚶 徒歩（自宅〜{depart_station}駅）：{event_title}", leave_home_dt, train_depart_dt)
            insert_event(f"🚃 電車（{depart_station}駅〜{arrival_station}駅）：{event_title}", train_depart_dt, train_arrive_dt)
            insert_event(f"🚶 徒歩（{arrival_station}駅〜目的地）：{event_title}", train_arrive_dt, actual_arrive_dt)
            insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)

        st.success("✅ 準備から移動の詳細、本番までの5つの予定をカレンダーに登録しました！")
        st.balloons()
    except Exception as e:
        st.error(f"❌ 登録失敗: {e}")