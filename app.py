# --- 必要なライブラリのインポート ---
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
# Google Calendar API連携用
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
# --- GPS取得用のライブラリ ---
from streamlit_js_eval import streamlit_js_eval

# ==========================================
# 0. システム設定（タイムゾーン）
# ==========================================
st.set_page_config(page_title="スケジュール＆移動ルーター", layout="centered")

st.sidebar.header("⚙️ システム設定")
tz_options = ["Asia/Tokyo", "UTC", "US/Pacific", "Europe/London", "Asia/Shanghai"]
selected_tz_str = st.sidebar.selectbox("アプリの基準タイムゾーン", tz_options, index=0)
app_tz = pytz.timezone(selected_tz_str)

now_with_tz = datetime.now(app_tz)

st.title("🗓 スケジュール＆移動ルーター")
st.write(f"現在の設定時刻: **{now_with_tz.strftime('%Y/%m/%d %H:%M:%S')}** ({selected_tz_str})")
st.write("確実な手順で、嘘のないスケジュールをカレンダーに登録します。")

# --- 住所クレンジング関数 ---
def clean_address(addr):
    if not addr: return ""
    addr = re.split(r'[ 　]', addr)[0]
    addr = re.sub(r'([0-9０-９]+[-ー][0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+丁目[0-9０-９]+番[0-9０-９]+号?).*$', r'\1', addr)
    return addr

# ==========================================
# STEP 1: 予定開始時間と目的地の設定
# ==========================================
st.header("1. 予定と目的地の設定")

event_title = st.text_input("予定のタイトル", "")

facility_name = st.text_input("施設名（目的地）", "")
if facility_name:
    google_search_url = f"https://www.google.com/search?q={urllib.parse.quote(facility_name + ' 住所')}"
    st.link_button(f"🔍 「{facility_name}」の住所をGoogleで検索", google_search_url)

event_address_full = st.text_input("目的地住所（ビル・マンション名まで含む）", "")

cleaned_address = clean_address(event_address_full)
full_destination_target = f"{facility_name} {event_address_full}".strip()

if event_address_full:
    st.write("---")
    st.write(f"▼ 🗺️ 目的地のマップ（視覚的確認）")
    map_embed_url = f"https://www.google.com/maps?q={urllib.parse.quote(full_destination_target)}&output=embed"
    components.iframe(map_embed_url, height=350, scrolling=True)

    st.write("▼ 🚉 周辺の駅を探す")
    nearby_search_query = f"周辺の駅 around:{cleaned_address}"
    nearby_station_url = f"https://www.google.com/maps/search/{urllib.parse.quote(nearby_search_query)}"
    st.link_button("🔍 地図を開いて周辺の駅を探す（別タブ）", nearby_station_url, use_container_width=True)

    st.write("▼ 🚉 目的地の近隣駅を入力")
    arrival_station = st.text_input("地図を確認して近隣駅（降車駅）を入力してください", "", key="arrival_station_input")

    if arrival_station:
        route_search_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(arrival_station + '駅')}&destination={urllib.parse.quote(cleaned_address)}&travelmode=walking"
        st.link_button(f"🚶‍♂️ {arrival_station}駅から目的地までのルートを全画面で確認", route_search_url, use_container_width=True)
    else:
        st.caption("※上のボタンで駅を探し、駅名を入力するとルート確認ボタンが表示されます。")
            
st.write("---")
event_date = st.date_input("予定の日付", datetime.today())

if "start_h" not in st.session_state:
    st.session_state.start_h = now_with_tz.strftime("%H")
if "start_m" not in st.session_state:
    st.session_state.start_m = now_with_tz.strftime("%M")

if "end_h" not in st.session_state:
    init_end_time = now_with_tz + timedelta(hours=1)
    st.session_state.end_h = init_end_time.strftime("%H")
if "end_m" not in st.session_state:
    st.session_state.end_m = now_with_tz.strftime("%M")

def sync_end_time():
    h = int(st.session_state.start_h)
    m = st.session_state.start_m
    end_h = (h + 1) % 24
    st.session_state.end_h = f"{end_h:02d}"
    st.session_state.end_m = m

st.write("🕒 **予定開始時間**")
col_s_h, col_s_m = st.columns(2)
with col_s_h:
    start_hour = st.selectbox("開始（時）", [f"{i:02d}" for i in range(24)], key="start_h", on_change=sync_end_time)
with col_s_m:
    start_minute = st.selectbox("開始（分）", [f"{i:02d}" for i in range(60)], key="start_m", on_change=sync_end_time)
start_time = time(int(start_hour), int(start_minute))

st.write("🕒 **予定終了時間**")
col_e_h, col_e_m = st.columns(2)
with col_e_h:
    end_hour = st.selectbox("終了（時）", [f"{i:02d}" for i in range(24)], key="end_h")
with col_e_m:
    end_minute = st.selectbox("終了（分）", [f"{i:02d}" for i in range(60)], key="end_m")
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
use_gps = st.toggle("🌍 GPSを起動して現在地を取得する", value=False)

if use_gps:
    js_code = """
    new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                resolve({lat: pos.coords.latitude, lng: pos.coords.longitude});
            },
            (err) => {
                resolve({error: err.message});
            },
            {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}
        );
    })
    """
    
    loc = streamlit_js_eval(js_expressions=js_code, key="gps_promise_fetch")

    if loc:
        if "error" in loc:
            st.error(f"❌ 位置情報の取得に失敗しました: {loc['error']}")
            st.caption("※スマートフォンの設定（プライバシー > 位置情報）やブラウザの権限設定をご確認ください。")
        else:
            lat, lng = loc['lat'], loc['lng']
            
            # --- 【重要変更】GoogleMapの検索URLを確実なパラメータ形式に変更 ---
            # q=駅 : 検索キーワードを「駅」に指定
            # ll=lat,lng : 地図の中心座標を現在地に強制固定
            # z=16 : 徒歩検索に最適なズームレベル（半径500m〜1km圏内）に指定
            # これにより、Googleの自動フィルタリングを回避し、最寄りの駅を確実に画面内に表示させます。
            gps_map_url = f"https://www.google.com/maps?q={urllib.parse.quote('駅')}&ll={lat},{lng}&z=16"
            
            st.success("✅ 位置情報の取得に成功しました！")
            st.link_button("↗️ 現在地周辺の駅をGoogleMapで表示", gps_map_url, use_container_width=True)
            st.caption(f"（内部データ: 緯度 {lat:.4f}, 経度 {lng:.4f}）")
    else:
        st.info("⌛ 位置情報を取得中、または許可待ちです...")

st.write("---")

# --- 出発駅候補リストの設定 ---
st.write("▼ 出発駅の候補リスト")

if "station_history" not in st.session_state:
    st.session_state.station_history = []

if "station_df" not in st.session_state:
    st.session_state.station_df = pd.DataFrame([
        {"順番": 1, "出発駅名": "井細田"},
        {"順番": 2, "出発駅名": "足柄(神奈川県)"},
        {"順番": 3, "出発駅名": "小田原"}
    ])

def save_to_history():
    snapshot = st.session_state.station_df.copy()
    timestamp = datetime.now(app_tz).strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.station_history.insert(0, {"time": timestamp, "data": snapshot})
    if len(st.session_state.station_history) > 5:
        st.session_state.station_history = st.session_state.station_history[:5]

st.caption("💡 新しい駅を追加する場合は入力してボタンを押してください。")
col_add_input, col_add_btn = st.columns([3, 1])
with col_add_input:
    new_station_name = st.text_input("駅名を入力", key="new_station_input", label_visibility="collapsed", placeholder="例：箱根板橋")
with col_add_btn:
    if st.button("➕ 追加", key="add_station_btn", use_container_width=True):
        if new_station_name.strip() != "":
            save_to_history()
            new_order = len(st.session_state.station_df) + 1
            new_row = pd.DataFrame([{"順番": new_order, "出発駅名": new_station_name.strip()}])
            st.session_state.station_df = pd.concat([st.session_state.station_df, new_row], ignore_index=True)
            st.rerun()

st.write("---")

for idx, row in st.session_state.station_df.iterrows():
    col_num, col_name, col_del = st.columns([1, 4, 2], vertical_alignment="center")
    
    with col_num:
        st.markdown(f"**{row['順番']}**")
    with col_name:
        st.markdown(f"**{row['出発駅名']}**")
    with col_del:
        if st.button("🗑️ 削除", key=f"del_sta_{idx}", use_container_width=True):
            save_to_history()
            st.session_state.station_df = st.session_state.station_df.drop(idx).reset_index(drop=True)
            st.session_state.station_df["順番"] = range(1, len(st.session_state.station_df) + 1)
            st.rerun()

st.write("---")

if st.session_state.station_history:
    with st.expander("⏪ 変更履歴の管理（直近5件）"):
        for i, h in enumerate(st.session_state.station_history):
            st.markdown(f"**{i+1}: {h['time']} の状態**")
            col_res, col_del = st.columns(2)
            with col_res:
                if st.button("⏪ 復元", key=f"hist_res_{i}", use_container_width=True):
                    st.session_state.station_df = h["data"]
                    st.rerun()
            with col_del:
                if st.button("🗑️ 削除", key=f"hist_del_{i}", use_container_width=True):
                    st.session_state.station_history.pop(i)
                    st.rerun()
            st.divider() 

valid_stations = [s for s in st.session_state.station_df["出発駅名"].tolist() if s and str(s).strip() != ""]
depart_station = st.selectbox("今回利用する出発駅", valid_stations if valid_stations else ["駅名を入力してください"])

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

if "train_dep_h" not in st.session_state:
    st.session_state.train_dep_h = now_with_tz.strftime("%H")
if "train_dep_m" not in st.session_state:
    st.session_state.train_dep_m = now_with_tz.strftime("%M")

if "train_arr_h" not in st.session_state:
    st.session_state.train_arr_h = now_with_tz.strftime("%H")
if "train_arr_m" not in st.session_state:
    st.session_state.train_arr_m = now_with_tz.strftime("%M")

def sync_train_arrive_time():
    st.session_state.train_arr_h = st.session_state.train_dep_h
    st.session_state.train_arr_m = st.session_state.train_dep_m

st.write("🚃 **確定した電車の 出発時刻**")
col_td_h, col_td_m = st.columns(2)
with col_td_h:
    train_depart_hour = st.selectbox("出発（時）", [f"{i:02d}" for i in range(24)], key="train_dep_h", on_change=sync_train_arrive_time)
with col_td_m:
    train_depart_minute = st.selectbox("出発（分）", [f"{i:02d}" for i in range(60)], key="train_dep_m", on_change=sync_train_arrive_time)
train_depart_time = time(int(train_depart_hour), int(train_depart_minute))

st.write("🚃 **確定した電車の 到着時刻**")
col_ta_h, col_ta_m = st.columns(2)
with col_ta_h:
    train_arrive_hour = st.selectbox("到着（時）", [f"{i:02d}" for i in range(24)], key="train_arr_h")
with col_ta_m:
    train_arrive_minute = st.selectbox("到着（分）", [f"{i:02d}" for i in range(60)], key="train_arr_m")
train_arrive_time = time(int(train_arrive_hour), int(train_arrive_minute))


# ==========================================
# STEP 4: 出発前の準備
# ==========================================
st.header("4. 出発前の準備")

st.write("---")
st.write("▼ 🏠 自宅からの徒歩時間（ワンタッチ入力）")

if "walk_presets" not in st.session_state:
    st.session_state.walk_presets = [
        {"name": "井細田", "time": 5},
        {"name": "足柄", "time": 15},
        {"name": "小田原", "time": 28}
    ]

if "walk_time" not in st.session_state:
    st.session_state.walk_time = 15

def set_walk_time(mins):
    st.session_state.walk_time = mins

cols = st.columns(3)
for i, preset in enumerate(st.session_state.walk_presets):
    col_idx = i % 3  
    with cols[col_idx]:
        st.button(
            f"🏠 {preset['name']} ({preset['time']}分)", 
            on_click=set_walk_time, 
            args=(preset['time'],), 
            key=f"preset_btn_{i}", 
            use_container_width=True
        )

with st.expander("⚙️ ワンタッチボタンの編集（追加・削除）"):
    st.caption("【削除】不要なボタンは横の削除ボタンで消せます。")
    for i, preset in enumerate(st.session_state.walk_presets):
        c_name, c_time, c_del = st.columns([3, 2, 2], vertical_alignment="center")
        with c_name:
            st.markdown(f"**{preset['name']}**")
        with c_time:
            st.markdown(f"{preset['time']}分")
        with c_del:
            if st.button("🗑️ 削除", key=f"del_preset_{i}", use_container_width=True):
                st.session_state.walk_presets.pop(i)
                st.rerun()
    
    st.divider()
    
    if len(st.session_state.walk_presets) < 6:
        st.caption("【追加】新しいボタンを作ります（最大6件）")
        c_new_name, c_new_time, c_new_btn = st.columns([3, 2, 2], vertical_alignment="bottom")
        with c_new_name:
            new_p_name = st.text_input("表示名", key="new_p_name_input", placeholder="例: コンビニ")
        with c_new_time:
            new_p_time = st.number_input("分", min_value=1, value=10, step=1, key="new_p_time_input")
        with c_new_btn:
            if st.button("➕ 追加", key="add_preset_btn", use_container_width=True):
                if new_p_name.strip() != "":
                    st.session_state.walk_presets.append({"name": new_p_name.strip(), "time": new_p_time})
                    st.rerun()
    else:
        st.warning("💡 登録上限（6件）に達しています。追加するには上のリストから削除してください。")

st.write("---")

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

st.write("▼ 登録オプション")
st.caption("カレンダーをすっきりさせたい場合、電車の乗車時間を登録から外すことができます。")
include_train_event = st.toggle("🚃 電車の乗車時間もカレンダーに登録する", value=True)

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

            train_arrive_dt = datetime.combine(event_date, train_arrive_time)
            
            if train_arrive_dt < train_depart_dt:
                train_arrive_dt += timedelta(days=1)
            
            actual_arrive_dt = train_arrive_dt + timedelta(minutes=walk_to_dest)

            insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
            insert_event(f"🚶 徒歩（自宅〜{depart_station}駅）：{event_title}", leave_home_dt, train_depart_dt)
            
            if include_train_event:
                insert_event(f"🚃 電車（{depart_station}駅〜{arrival_station}駅）：{event_title}", train_depart_dt, train_arrive_dt)
            
            insert_event(f"🚶 徒歩（{arrival_station}駅〜目的地）：{event_title}", train_arrive_dt, actual_arrive_dt)
            insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)

        if include_train_event:
            st.success("✅ 準備から移動の詳細、本番までの5つの予定をカレンダーに登録しました！")
        else:
            st.success("✅ 電車の乗車時間を除く、4つの予定をカレンダーに登録しました！")
            
        st.balloons()
    except Exception as e:
        st.error(f"❌ 登録失敗: {e}")