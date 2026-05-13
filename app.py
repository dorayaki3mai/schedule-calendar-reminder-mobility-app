# --- 必要なライブラリのインポート ---
import streamlit as st
import streamlit.components.v1 as components
import json
import pandas as pd
import re
from datetime import datetime, timedelta, time
import urllib.parse
import os.path
import os
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
# 0. システム設定（タイムゾーンとCSS）
# ==========================================
st.set_page_config(page_title="スケジュール＆移動ルーター", layout="centered")

st.markdown("""
<style>
div[data-baseweb="input"] input {
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
/* 設定メニュー等のボタンを左寄せにするためのCSS調整 */
.menu-button button {
    justify-content: flex-start !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# データ管理系の初期化
# ==========================================

if "current_page" not in st.session_state:
    st.session_state.current_page = "main"

def go_to_main():
    st.session_state.current_page = "main"

def go_to_settings():
    st.session_state.current_page = "settings"

def go_to_settings_stations():
    st.session_state.current_page = "settings_stations"

def go_to_settings_presets():
    st.session_state.current_page = "settings_presets"


if "walk_time_train" not in st.session_state:
    st.session_state.walk_time_train = 15
if "walk_time_direct" not in st.session_state:
    st.session_state.walk_time_direct = 15

if "walk_presets" not in st.session_state:
    st.session_state.walk_presets = [{"name": "井細田", "time": 5}, {"name": "足柄", "time": 15}, {"name": "小田原", "time": 28}]

# --- 出発駅用 ---
if "station_history" not in st.session_state:
    st.session_state.station_history = []
if "station_df" not in st.session_state:
    st.session_state.station_df = pd.DataFrame([
        {"順番": 1, "出発駅名": "井細田"},
        {"順番": 2, "出発駅名": "足柄(神奈川県)"},
        {"順番": 3, "出発駅名": "小田原"}
    ])

if "app_timezone" not in st.session_state:
    st.session_state.app_timezone = "Asia/Tokyo"

app_tz = pytz.timezone(st.session_state.app_timezone)
now_with_tz = datetime.now(app_tz)

def save_to_history():
    snapshot = st.session_state.station_df.copy()
    timestamp = datetime.now(app_tz).strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.station_history.insert(0, {"time": timestamp, "data": snapshot})
    if len(st.session_state.station_history) > 5:
        st.session_state.station_history = st.session_state.station_history[:5]

# --- カレンダー管理用 ---
if "calendar_history" not in st.session_state:
    st.session_state.calendar_history = []
if "calendar_df" not in st.session_state:
    st.session_state.calendar_df = pd.DataFrame([
        {"順番": 1, "カレンダー名": "メインカレンダー", "カレンダーID": "primary"}
    ])

def save_cal_to_history():
    snapshot = st.session_state.calendar_df.copy()
    timestamp = datetime.now(app_tz).strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.calendar_history.insert(0, {"time": timestamp, "data": snapshot})
    if len(st.session_state.calendar_history) > 5:
        st.session_state.calendar_history = st.session_state.calendar_history[:5]

# ==========================================
# 安全な追加・同期用のコールバック関数
# ==========================================

def set_walk_time_callback(mins):
    st.session_state.walk_time_train = mins
    st.session_state.walk_time_direct = mins

def add_new_calendar_callback():
    name = st.session_state.new_cal_name_input.strip()
    cal_id = st.session_state.new_cal_id_input.strip()
    if name != "" and cal_id != "":
        save_cal_to_history()
        new_order = len(st.session_state.calendar_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "カレンダー名": name, "カレンダーID": cal_id}])
        st.session_state.calendar_df = pd.concat([st.session_state.calendar_df, new_row], ignore_index=True)
        st.session_state.new_cal_name_input = ""
        st.session_state.new_cal_id_input = ""

def add_new_station_callback():
    name = st.session_state.new_station_input.strip()
    if name != "":
        save_to_history()
        new_order = len(st.session_state.station_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "出発駅名": name}])
        st.session_state.station_df = pd.concat([st.session_state.station_df, new_row], ignore_index=True)
        st.session_state.new_station_input = ""

def add_new_station_sb_callback():
    name = st.session_state.new_station_input_sb.strip()
    if name != "":
        save_to_history()
        new_order = len(st.session_state.station_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "出発駅名": name}])
        st.session_state.station_df = pd.concat([st.session_state.station_df, new_row], ignore_index=True)
        st.session_state.new_station_input_sb = ""

def add_new_preset_callback():
    name = st.session_state.new_p_name_input.strip()
    mins = st.session_state.new_p_time_input
    if name != "":
        st.session_state.walk_presets.append({"name": name, "time": mins})
        st.session_state.new_p_name_input = ""
        st.session_state.new_p_time_input = 10

def add_new_preset_sb_callback():
    name = st.session_state.new_p_name_input_sb.strip()
    mins = st.session_state.new_p_time_input_sb
    if name != "":
        st.session_state.walk_presets.append({"name": name, "time": mins})
        st.session_state.new_p_name_input_sb = ""
        st.session_state.new_p_time_input_sb = 10

def set_depart_station_callback(sta):
    st.session_state.selected_depart_station = sta

def update_depart_station_from_sb():
    st.session_state.selected_depart_station = st.session_state.sb_depart_station

def update_timezone():
    st.session_state.app_timezone = st.session_state.tz_selector


# ==========================================
# 画面遷移のルーティング
# ==========================================

# ------------------------------------------
# A-1. 設定メニュー一覧画面
# ------------------------------------------
if st.session_state.current_page == "settings":
    
    st.button("◀️ メイン画面に戻る", on_click=go_to_main, type="primary", use_container_width=True)
    
    st.title("⚙️ 管理メニュー")
    st.caption("アプリの各種設定やデータの管理を行います。")
    st.write("---")

    with st.expander("🌍 一般設定 (タイムゾーン)", expanded=False):
        st.caption("海外へ移動した際などに変更してください。")
        tz_options = ["Asia/Tokyo", "UTC", "US/Pacific", "Europe/London", "Asia/Shanghai"]
        current_tz_index = tz_options.index(st.session_state.app_timezone) if st.session_state.app_timezone in tz_options else 0
        st.selectbox("基準タイムゾーン", tz_options, index=current_tz_index, key="tz_selector", on_change=update_timezone)

    with st.expander("👤 カレンダーアカウント連携", expanded=False):
        st.caption("連携しているGoogleアカウントの接続解除・切り替えを行います。")
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        if os.path.exists('token.json'):
            st.success("✅ 現在のアカウントは連携済みです")
            if st.button("🗑️ アカウント連携を解除する", use_container_width=True):
                try:
                    os.remove('token.json')
                    if "oauth_flow" in st.session_state:
                        del st.session_state["oauth_flow"]
                    st.success("連携を解除しました。")
                    st.rerun()
                except Exception as e:
                    st.error(f"ファイルの削除に失敗しました: {e}")
        elif "GOOGLE_TOKEN_JSON" in st.secrets:
            st.info("ℹ️ クラウドのシークレット(Secrets)で連携されています。")
        else:
            st.warning("⚠️ 現在アカウントは連携されていません")
            if os.path.exists('credentials.json'):
                if "oauth_flow" not in st.session_state:
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob' 
                    auth_url, _ = flow.authorization_url(prompt='consent')
                    st.session_state.oauth_flow = flow
                    st.session_state.auth_url = auth_url
                st.markdown(f"**[👉 ここをクリックしてGoogleにログイン]({st.session_state.auth_url})**")
                st.caption("許可後に出る「認証コード」をコピーし、下の欄に貼り付けてEnterを押してください。")
                auth_code = st.text_input("認証コードを貼り付け", key="auth_code_input")
                if auth_code:
                    try:
                        flow = st.session_state.oauth_flow
                        flow.fetch_token(code=auth_code)
                        creds = flow.credentials
                        with open('token.json', 'w') as token:
                            token.write(creds.to_json())
                        st.success("✅ 認証成功！メイン画面からカレンダーに登録できます。")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 認証失敗: {e}")
            else:
                st.error("❌ credentials.json ファイルが見つかりません。")

    with st.expander("📅 登録先カレンダーの管理", expanded=False):
        st.caption("Googleカレンダーの「カレンダーID」を登録します。")
        for idx, row in st.session_state.calendar_df.iterrows():
            col_name, col_del = st.columns([4, 1], vertical_alignment="center")
            with col_name: 
                st.markdown(f"**{row['順番']}. {row['カレンダー名']}**<br><span style='font-size:11px; color:gray;'>{row['カレンダーID']}</span>", unsafe_allow_html=True)
            with col_del:
                if row['カレンダーID'] != 'primary':
                    if st.button("🗑️", key=f"del_cal_sb_{idx}", use_container_width=True):
                        save_cal_to_history()
                        st.session_state.calendar_df = st.session_state.calendar_df.drop(idx).reset_index(drop=True)
                        st.session_state.calendar_df["順番"] = range(1, len(st.session_state.calendar_df) + 1)
                        st.rerun()
        st.divider()
        st.caption("💡 新しいカレンダーを追加")
        st.text_input("表示名", key="new_cal_name_input", placeholder="例：仕事用", label_visibility="collapsed")
        st.text_input("カレンダーID", key="new_cal_id_input", placeholder="例：xxx@group.calendar.google.com", label_visibility="collapsed")
        st.button("➕ 追加", key="add_cal_btn", use_container_width=True, on_click=add_new_calendar_callback)

        if st.session_state.calendar_history:
            st.divider()
            st.caption("⏪ カレンダー変更履歴")
            for i, h in enumerate(st.session_state.calendar_history):
                st.markdown(f"**{i+1}: {h['time']}**")
                col_res, col_del = st.columns(2)
                with col_res:
                    if st.button("⏪ 復元", key=f"hist_res_cal_{i}", use_container_width=True):
                        st.session_state.calendar_df = h["data"]
                        st.rerun()
                with col_del:
                    if st.button("🗑️ 削除", key=f"hist_del_cal_{i}", use_container_width=True):
                        st.session_state.calendar_history.pop(i)
                        st.rerun()
                st.write("")

    st.write("---")
    st.caption("詳細設定")
    st.markdown('<div class="menu-button">', unsafe_allow_html=True)
    st.button("🚉 出発駅リストの管理  ＞", on_click=go_to_settings_stations, use_container_width=True)
    st.button("🏠 徒歩時間ワンタッチボタンの管理  ＞", on_click=go_to_settings_presets, use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ------------------------------------------
# A-2. 個別設定画面（出発駅リストの管理）
# ------------------------------------------
elif st.session_state.current_page == "settings_stations":
    
    st.button("◀️ 管理メニューに戻る", on_click=go_to_settings, type="secondary", use_container_width=True)
    
    st.title("🚉 出発駅リストの管理")
    st.caption("登録済みの駅の確認と削除ができます。")
    st.write("---")

    for idx, row in st.session_state.station_df.iterrows():
        col_name, col_del = st.columns([4, 1], vertical_alignment="center")
        with col_name: 
            st.markdown(f"**{row['順番']}. {row['出発駅名']}**")
        with col_del:
            if st.button("🗑️", key=f"del_sta_sub_{idx}", use_container_width=True):
                save_to_history()
                st.session_state.station_df = st.session_state.station_df.drop(idx).reset_index(drop=True)
                st.session_state.station_df["順番"] = range(1, len(st.session_state.station_df) + 1)
                st.rerun()
                
    st.divider()
    st.subheader("💡 新しい駅を追加")
    st.text_input("駅名を入力", key="new_station_input_sb", placeholder="例：箱根板橋")
    st.button("➕ 追加する", key="add_station_btn_sub", type="primary", use_container_width=True, on_click=add_new_station_sb_callback)

    if st.session_state.station_history:
        st.divider()
        st.subheader("⏪ 変更履歴の管理（直近5件）")
        for i, h in enumerate(st.session_state.station_history):
            st.markdown(f"**{i+1}: {h['time']} の状態**")
            col_res, col_del = st.columns(2)
            with col_res:
                if st.button("⏪ 復元", key=f"hist_res_sub_{i}", use_container_width=True):
                    st.session_state.station_df = h["data"]
                    st.rerun()
            with col_del:
                if st.button("🗑️ 削除", key=f"hist_del_sub_{i}", use_container_width=True):
                    st.session_state.station_history.pop(i)
                    st.rerun()
            st.write("")


# ------------------------------------------
# A-3. 個別設定画面（徒歩時間ワンタッチボタンの管理）
# ------------------------------------------
elif st.session_state.current_page == "settings_presets":
    
    st.button("◀️ 管理メニューに戻る", on_click=go_to_settings, type="secondary", use_container_width=True)
    
    st.title("🏠 徒歩時間ボタンの管理")
    st.caption("自宅等からの徒歩時間のワンタッチボタンを確認・削除できます。")
    st.write("---")

    for i, preset in enumerate(st.session_state.walk_presets):
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="center")
        with c1: st.markdown(f"**{preset['name']}**")
        with c2: st.markdown(f"{preset['time']}分")
        with c3:
            if st.button("🗑️ 削除", key=f"del_preset_sub_{i}", use_container_width=True):
                st.session_state.walk_presets.pop(i)
                st.rerun()
                
    st.divider()
    st.subheader("💡 新しいボタンを追加")
    if len(st.session_state.walk_presets) < 6:
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
        with c1: st.text_input("表示名", key="new_p_name_input_sb", placeholder="例: コンビニ")
        with c2: st.number_input("分", min_value=1, value=10, step=1, key="new_p_time_input_sb")
        with c3: st.button("➕ 追加する", key="add_preset_btn_sub", type="primary", use_container_width=True, on_click=add_new_preset_sb_callback)
    else:
        st.warning("登録できるワンタッチボタンは最大6件までです。上のリストから不要なものを削除してください。")


# ------------------------------------------
# B. メイン画面（スケジュール登録画面）
# ------------------------------------------
elif st.session_state.current_page == "main":

    col_title, col_settings = st.columns([4, 1], vertical_alignment="center")
    with col_title:
        st.title("🗓 移動ルーター")
    with col_settings:
        st.button("⚙️ 設定", on_click=go_to_settings, use_container_width=True)

    st.write(f"現在の設定時刻: **{now_with_tz.strftime('%Y/%m/%d %H:%M:%S')}** ({st.session_state.app_timezone})")
    st.write("確実な手順で、嘘のないスケジュールをカレンダーに登録します。")

    def clean_address(addr):
        if not addr: return ""
        addr = re.sub(r'〒?\s*[0-9０-９]{3}[-ー][0-9０-９]{4}\s*', '', addr)
        addr = re.split(r'[ 　]', addr)[0]
        addr = re.sub(r'([0-9０-９]+[-ー][0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+丁目[0-9０-９]+番[0-9０-９]+号?).*$', r'\1', addr)
        return addr.strip()

    def render_hybrid_time_picker(label, state_key, max_value, on_change_callback=None):
        input_key = f"input_{state_key}"
        
        if input_key not in st.session_state and state_key in st.session_state:
            st.session_state[input_key] = st.session_state[state_key]

        def increment():
            val = int(st.session_state[state_key])
            new_val = (val + 1) % max_value
            st.session_state[state_key] = f"{new_val:02d}"; st.session_state[input_key] = f"{new_val:02d}"
            if on_change_callback: on_change_callback()
        def decrement():
            val = int(st.session_state[state_key])
            new_val = (val - 1) % max_value
            st.session_state[state_key] = f"{new_val:02d}"; st.session_state[input_key] = f"{new_val:02d}"
            if on_change_callback: on_change_callback()
        def manual_update():
            raw = st.session_state[input_key].translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            try:
                val = int(raw) % max_value
                st.session_state[state_key] = f"{val:02d}"; st.session_state[input_key] = f"{val:02d}"
            except ValueError:
                st.session_state[input_key] = st.session_state[state_key]
            if on_change_callback: on_change_callback()

        st.markdown(f"<div style='text-align:center; font-size:14px; color:gray;'>{label}</div>", unsafe_allow_html=True)
        st.button("▲", key=f"up_{state_key}", on_click=decrement, use_container_width=True)
        st.text_input("hidden", key=input_key, label_visibility="collapsed", on_change=manual_update)
        st.button("▼", key=f"down_{state_key}", on_click=increment, use_container_width=True)

    # ==========================================
    # STEP 1: 予定開始時間と目的地の設定
    # ==========================================
    st.header("1. 予定と目的地の設定")

    event_title = st.text_input("予定のタイトル", "")
    facility_name = st.text_input("施設名（目的地）", "")
    
    if facility_name:
        st.link_button(
            f"🗺️ 「{facility_name}」をGoogleマップで探す", 
            f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(facility_name)}"
        )

    event_address_full = st.text_input("目的地住所（ビル・マンション名まで含む）", "")
    cleaned_address = clean_address(event_address_full)
    full_destination_target = f"{facility_name} {event_address_full}".strip()

    search_destination = event_address_full if event_address_full else facility_name
    if search_destination:
        st.write("---")
        st.write(f"▼ 🗺️ 目的地のマップ（視覚的確認）")
        components.iframe(f"https://www.google.com/maps?q={urllib.parse.quote(search_destination)}&output=embed", height=350, scrolling=True)

    st.write("---")
    event_date = st.date_input("予定の日付", datetime.today())

    if "start_h" not in st.session_state:
        st.session_state.start_h = now_with_tz.strftime("%H"); st.session_state.input_start_h = st.session_state.start_h
    if "start_m" not in st.session_state:
        st.session_state.start_m = now_with_tz.strftime("%M"); st.session_state.input_start_m = st.session_state.start_m
    if "end_h" not in st.session_state:
        init_end = now_with_tz + timedelta(hours=1)
        st.session_state.end_h = init_end.strftime("%H"); st.session_state.input_end_h = st.session_state.end_h
    if "end_m" not in st.session_state:
        st.session_state.end_m = now_with_tz.strftime("%M"); st.session_state.input_end_m = st.session_state.end_m

    def sync_end_time():
        h = int(st.session_state.start_h)
        st.session_state.end_h = f"{(h + 1) % 24:02d}"; st.session_state.input_end_h = st.session_state.end_h
        st.session_state.end_m = st.session_state.start_m; st.session_state.input_end_m = st.session_state.start_m

    st.write("🕒 **予定開始時間**")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1: render_hybrid_time_picker("時", "start_h", 24, sync_end_time)
        with c2: render_hybrid_time_picker("分", "start_m", 60, sync_end_time)
    start_time = time(int(st.session_state.start_h), int(st.session_state.start_m))

    st.write("🕒 **予定終了時間**")
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1: render_hybrid_time_picker("時", "end_h", 24)
        with c2: render_hybrid_time_picker("分", "end_m", 60)
    end_time = time(int(st.session_state.end_h), int(st.session_state.end_m))

    st.write("---")
    arrival_buffer_option = st.selectbox("予定開始の何分前に到着しますか？", ["5分前", "10分前", "15分前", "20分前", "自由入力（分）"], index=1)
    buffer_minutes = st.number_input("到着バッファ（分）", value=30, min_value=0, step=1) if arrival_buffer_option == "自由入力（分）" else int(re.search(r'\d+', arrival_buffer_option).group())

    event_dt = datetime.combine(event_date, start_time)
    target_arrival_dt = event_dt - timedelta(minutes=buffer_minutes)
    st.info(f"💡 目標到着時刻: **{target_arrival_dt.strftime('%H:%M')}**")

    # ==========================================
    # 移動モードの選択
    # ==========================================
    st.write("---")
    st.write("▼ 🚶 移動手段の選択")
    if "travel_mode" not in st.session_state: 
        st.session_state.travel_mode = "🚃 電車を利用する"

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🚃 電車を利用する", use_container_width=True, type="primary" if st.session_state.travel_mode == "🚃 電車を利用する" else "secondary"):
            st.session_state.travel_mode = "🚃 電車を利用する"; st.rerun()
    with c2:
        if st.button("🚶 徒歩のみ（近場）", use_container_width=True, type="primary" if st.session_state.travel_mode == "🚶 徒歩のみ" else "secondary"):
            st.session_state.travel_mode = "🚶 徒歩のみ"; st.rerun()

    travel_mode = st.session_state.travel_mode

    train_depart_time = None; train_arrive_time = None; depart_station = ""; walk_to_dest = 0

    if "arrival_station_input" not in st.session_state:
        st.session_state.arrival_station_input = ""


    # ==========================================
    # STEP 2 & 3
    # ==========================================
    if travel_mode == "🚃 電車を利用する":
        with st.expander("🚃 STEP 2: 降車駅の検索と徒歩計算", expanded=True):
            if search_destination:
                around_target = cleaned_address if cleaned_address else facility_name
                st.write("▼ 🚉 周辺の駅を探す")
                st.link_button("🔍 地図を開いて周辺の駅を探す", f"https://www.google.com/maps/search/{urllib.parse.quote('周辺の駅 around:'+around_target)}", use_container_width=True)

            st.write("▼ 🚉 目的地の近隣駅を入力")
            st.text_input("地図を確認して近隣駅（降車駅）を入力してください", key="arrival_station_input")

            current_arrival_station = st.session_state.arrival_station_input

            if current_arrival_station and search_destination:
                clean_sta = re.sub(r'駅$', '', current_arrival_station)
                st.link_button(f"🚶‍♂️ {clean_sta}駅から目的地までのルートを確認", f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(clean_sta + '駅')}&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
            elif current_arrival_station and not search_destination:
                st.caption("※STEP 1で目的地を入力すると、ここから目的地までの徒歩ルート確認ボタンが表示されます。")

            st.write("---")
            st.write(f"🚉 確定した駅: **{current_arrival_station if current_arrival_station else '（未入力）'}**")
            walk_to_dest = st.number_input(f"駅から目的地までの徒歩時間（分）", value=5, step=1)
            train_deadline_dt = target_arrival_dt - timedelta(minutes=walk_to_dest)
            
            display_sta = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else "〇〇"
            st.success(f"🚃 **{display_sta}駅** に **{train_deadline_dt.strftime('%H:%M')}** までに到着する電車を探します。")

        # --- 【UI改善】STEP3の分割と再構築（データ抽出） ---
        valid_stations = [s for s in st.session_state.station_df["出発駅名"].tolist() if s and str(s).strip() != ""]
        if not valid_stations: valid_stations = ["駅名を入力してください"]
        
        if "selected_depart_station" not in st.session_state or st.session_state.selected_depart_station not in valid_stations:
            st.session_state.selected_depart_station = valid_stations[0]

        # --- ① 出発駅を探す専用のエキスパンダー ---
        with st.expander("🔍 出発駅を探す・追加・全リスト", expanded=False):
            st.write("▼ 📍 現在地から出発駅を探す")
            if st.toggle("🌍 GPSを起動して現在地を取得する", value=False):
                loc = streamlit_js_eval(js_expressions="new Promise((res, rej) => { navigator.geolocation.getCurrentPosition((p) => { res({lat: p.coords.latitude, lng: p.coords.longitude}); }, (e) => { res({error: e.message}); }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}); })", key="gps_promise_fetch")
                if loc:
                    if "error" in loc: st.error(f"❌ 位置情報の取得に失敗: {loc['error']}")
                    else:
                        st.success("✅ 位置情報の取得に成功しました！")
                        st.link_button("↗️ 現在地周辺の駅をGoogleMapで表示", f"https://www.google.com/maps?q={urllib.parse.quote('駅')}&ll={loc['lat']},{loc['lng']}&z=16", use_container_width=True)
                else: st.info("⌛ 位置情報を取得中...")

            st.write("---")
            st.write("▼ 出発駅の追加")
            st.caption("💡 新しい駅を追加する場合は入力してボタンを押してください。（リストの確認・削除は右上の「⚙️ 設定」メニューから）")
            c1, c2 = st.columns([3, 1])
            with c1: st.text_input("駅名を入力", key="new_station_input", label_visibility="collapsed", placeholder="例：箱根板橋")
            with c2: st.button("➕ 追加", key="add_station_btn", use_container_width=True, on_click=add_new_station_callback)

            st.write("---")
            st.write("▼ リストから選択")
            st.caption("登録されているすべての駅から選択します。")
            current_index = valid_stations.index(st.session_state.selected_depart_station) if st.session_state.selected_depart_station in valid_stations else 0
            st.selectbox(
                "出発駅", 
                valid_stations, 
                index=current_index, 
                key="sb_depart_station",
                on_change=update_depart_station_from_sb,
                label_visibility="collapsed"
            )

        # --- ② ワンタッチ選択と ③ ジョルダン検索を STEP3の先頭に ---
        with st.expander("🚃 STEP 3: ルート検索と電車の時刻入力", expanded=True):
            st.write("▼ 今回利用する出発駅を選択（ワンタッチ）")
            
            btn_stations = valid_stations[:6]
            cols = st.columns(3)
            for i, sta in enumerate(btn_stations):
                with cols[i % 3]:
                    is_selected = (st.session_state.selected_depart_station == sta)
                    st.button(
                        sta, 
                        key=f"btn_sel_sta_{i}", 
                        type="primary" if is_selected else "secondary", 
                        use_container_width=True, 
                        on_click=set_depart_station_callback, 
                        args=(sta,)
                    )

            # 選ばれた駅を変数に確保してジョルダンに渡す
            depart_station = st.session_state.selected_depart_station
            clean_arrival_sta_for_jorudan = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else ""
            jorudan_params = {"eki1": depart_station, "eki2": clean_arrival_sta_for_jorudan, "Dym": event_date.strftime("%Y%m"), "Ddd": event_date.strftime("%d"), "Dhh": train_deadline_dt.strftime("%H"), "Dmn1": str(train_deadline_dt.minute // 10), "Dmn2": str(train_deadline_dt.minute % 10), "Cway": "1"}
            
            st.write("---")
            st.write("▼ ジョルダン乗換案内でルートを検索")
            st.link_button("↗️ ジョルダン乗換案内を開く", "https://www.jorudan.co.jp/norikae/cgi/nori.cgi?" + urllib.parse.urlencode(jorudan_params), use_container_width=True)

            st.write("---")
            st.write("▼ 調べた電車の時刻を入力してください")

            if "train_dep_h" not in st.session_state:
                st.session_state.train_dep_h = now_with_tz.strftime("%H"); st.session_state.input_train_dep_h = st.session_state.train_dep_h
                st.session_state.train_dep_m = now_with_tz.strftime("%M"); st.session_state.input_train_dep_m = st.session_state.train_dep_m
                st.session_state.train_arr_h = now_with_tz.strftime("%H"); st.session_state.input_train_arr_h = st.session_state.train_arr_h
                st.session_state.train_arr_m = now_with_tz.strftime("%M"); st.session_state.input_train_arr_m = st.session_state.train_arr_m

            def sync_train_arrive_time():
                st.session_state.train_arr_h = st.session_state.train_dep_h; st.session_state.input_train_arr_h = st.session_state.train_dep_h
                st.session_state.train_arr_m = st.session_state.train_dep_m; st.session_state.input_train_arr_m = st.session_state.train_dep_m

            st.write("🚃 **確定した電車の 出発時刻**")
            with st.container(border=True):
                c1, c2 = st.columns(2)
                with c1: render_hybrid_time_picker("時", "train_dep_h", 24, sync_train_arrive_time)
                with c2: render_hybrid_time_picker("分", "train_dep_m", 60, sync_train_arrive_time)
            train_depart_time = time(int(st.session_state.train_dep_h), int(st.session_state.train_dep_m))

            st.write("🚃 **確定した電車の 到着時刻**")
            with st.container(border=True):
                c1, c2 = st.columns(2)
                with c1: render_hybrid_time_picker("時", "train_arr_h", 24)
                with c2: render_hybrid_time_picker("分", "train_arr_m", 60)
            train_arrive_time = time(int(st.session_state.train_arr_h), int(st.session_state.train_arr_m))


    # ==========================================
    # STEP 4: 出発前の準備
    # ==========================================
    st.header("4. 出発前の準備")
    st.write("---")
    st.write("▼ 🏠 自宅からの徒歩時間（ワンタッチ入力）")

    cols = st.columns(3)
    for i, preset in enumerate(st.session_state.walk_presets):
        with cols[i % 3]:
            st.button(f"🏠 {preset['name']} ({preset['time']}分)", on_click=set_walk_time_callback, args=(preset['time'],), key=f"preset_btn_{i}", use_container_width=True)

    with st.expander("➕ ワンタッチボタンの追加", expanded=False):
        st.caption("💡 新しいボタンを追加します。（リストの確認・削除は右上の「⚙️ 設定」メニューから）")
        if len(st.session_state.walk_presets) < 6:
            c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
            with c1: st.text_input("表示名", key="new_p_name_input", placeholder="例: コンビニ")
            with c2: st.number_input("分", min_value=1, value=10, step=1, key="new_p_time_input")
            with c3: st.button("➕ 追加", key="add_preset_btn", use_container_width=True, on_click=add_new_preset_callback)
        else:
            st.warning("登録できるワンタッチボタンは最大6件までです。設定画面から不要なものを削除してください。")

    st.write("---")

    if travel_mode == "🚃 電車を利用する":
        walk_to_station = st.number_input("現在地から【利用する出発駅】までの徒歩時間（分）", key="walk_time_train", step=1)
        prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1, key="prep_time_train")
        
        leave_home_dt = datetime.combine(event_date, train_depart_time) - timedelta(minutes=walk_to_station)
        start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

    else:
        st.write("▼ 🗺️ 目的地までの徒歩ルートと時間を確認")
        if st.toggle("🌍 GPSを起動して現在地を取得する", key="use_gps_walk", value=False):
            loc_walk = streamlit_js_eval(js_expressions="new Promise((res, rej) => { navigator.geolocation.getCurrentPosition((p) => { res({lat: p.coords.latitude, lng: p.coords.longitude}); }, (e) => { res({error: e.message}); }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}); })", key="gps_promise_fetch_walk")
            if loc_walk:
                if "error" in loc_walk: st.error(f"❌ 位置情報の取得に失敗: {loc_walk['error']}")
                else:
                    st.success("✅ 位置情報の取得に成功しました！")
                    if search_destination:
                        st.link_button("🚶‍♂️ 取得した現在地からの徒歩ルートを確認", f"https://www.google.com/maps/dir/?api=1&origin={loc_walk['lat']},{loc_walk['lng']}&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
                        st.caption("※Googleマップで表示された「徒歩〇〇分」の数字を、下の入力欄にセットしてください。")
                    else: st.warning("目的地が入力されていません。")
            else: st.info("⌛ 位置情報を取得中...")
        else:
            if search_destination:
                st.link_button("🚶‍♂️ 現在地から目的地までの徒歩ルートを確認", f"https://www.google.com/maps/dir/?api=1&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
                st.caption("※Googleマップで表示された「徒歩〇〇分」の数字を、下の入力欄にセットしてください。")
            else: st.warning("目的地が入力されていません。")
            
        walk_to_dest_direct = st.number_input("現在地から【目的地】までの総徒歩時間（分）", key="walk_time_direct", step=1)
        prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1, key="prep_time_direct")
        
        leave_home_dt = target_arrival_dt - timedelta(minutes=walk_to_dest_direct)
        start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

    st.info(f"🏁 **目標到着時刻: {target_arrival_dt.strftime('%H:%M')}**")
    st.error(f"🏠 **準備開始時刻: {start_prep_dt.strftime('%H:%M')}**")
    st.warning(f"🚶 **出発時刻: {leave_home_dt.strftime('%H:%M')}**")


    # ==========================================
    # STEP 5: カレンダー登録
    # ==========================================
    st.header("5. カレンダー登録")

    st.write("▼ 登録先カレンダーの選択")
    cal_options = [f"{row['カレンダー名']} ({row['カレンダーID']})" for idx, row in st.session_state.calendar_df.iterrows()]
    if cal_options:
        selected_cal_str = st.selectbox("予定を登録するカレンダーを選択してください", cal_options)
        selected_calendar_id = st.session_state.calendar_df.iloc[cal_options.index(selected_cal_str)]['カレンダーID']
    else:
        st.warning("カレンダーが登録されていません。デフォルト(primary)を使用します。")
        selected_calendar_id = "primary"

    st.write("---")

    if travel_mode == "🚃 電車を利用する":
        st.write("▼ 登録オプション")
        st.caption("カレンダーをすっきりさせたい場合、電車の乗車時間を登録から外すことができます。")
        include_train_event = st.toggle("🚃 電車の乗車時間もカレンダーに登録する", value=True)

    if st.button("📅 カレンダーに登録", type="primary", use_container_width=True):
        try:
            with st.spinner("Googleカレンダーに通信中..."):
                SCOPES = ['https://www.googleapis.com/auth/calendar']
                creds = None
                if os.path.exists('token.json'):
                    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
                elif "GOOGLE_TOKEN_JSON" in st.secrets:
                    creds = Credentials.from_authorized_user_info(json.loads(st.secrets["GOOGLE_TOKEN_JSON"]), SCOPES)
                
                if not creds or not creds.valid:
                    if creds and creds.expired and creds.refresh_token: 
                        creds.refresh(Request())
                    else: 
                        st.error("❌ 認証情報がありません。右上の「⚙️ 設定」を開き、「👤 カレンダーアカウント連携」からログインを完了させてください。")
                        st.stop()

                service = build('calendar', 'v3', credentials=creds)

                def insert_event(summary, start_datetime, end_datetime, location=""):
                    service.events().insert(calendarId=selected_calendar_id, body={'summary': summary, 'location': location, 'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'}, 'end': {'dateTime': end_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'}}).execute()

                if travel_mode == "🚃 電車を利用する":
                    train_arrive_dt = datetime.combine(event_date, train_arrive_time)
                    if train_arrive_dt < datetime.combine(event_date, train_depart_time): train_arrive_dt += timedelta(days=1)
                    actual_arrive_dt = train_arrive_dt + timedelta(minutes=walk_to_dest)

                    clean_arrival_sta_for_cal = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else ""

                    insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
                    insert_event(f"🚶 徒歩（自宅〜{depart_station}駅）：{event_title}", leave_home_dt, datetime.combine(event_date, train_depart_time))
                    if include_train_event:
                        insert_event(f"🚃 電車（{depart_station}駅〜{clean_arrival_sta_for_cal}駅）：{event_title}", datetime.combine(event_date, train_depart_time), train_arrive_dt)
                    insert_event(f"🚶 徒歩（{clean_arrival_sta_for_cal}駅〜目的地）：{event_title}", train_arrive_dt, actual_arrive_dt)
                    insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)
                    
                    st.success("✅ 準備から移動の詳細、本番までをカレンダーに登録しました！" if include_train_event else "✅ 電車の乗車時間を除く予定をカレンダーに登録しました！")

                else:
                    insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
                    insert_event(f"🚶 徒歩（出発地〜目的地）：{event_title}", leave_home_dt, target_arrival_dt)
                    insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)
                    
                    st.success("✅ 準備、徒歩移動、本番の3つの予定をカレンダーに登録しました！")

            st.balloons()
        except Exception as e:
            st.error(f"❌ 登録失敗: {e}")