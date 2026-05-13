# --- 必要なライブラリのインポート ---
# Webアプリケーションの骨組みとなるStreamlit
import streamlit as st
# HTMLやGoogle Mapsの埋め込み（iframe）などを表示するためのコンポーネント
import streamlit.components.v1 as components
# API連携時の認証情報などを扱うためのJSON操作
import json
# データの表形式管理（リスト機能などで使用）
import pandas as pd
# 文字列の検索・置換（住所のクレンジングや「駅」の重複防止）に使う正規表現
import re
# 時間や日付の計算（〇〇分前、などの計算）
from datetime import datetime, timedelta, time
# 日本語などのURLエンコード（Google Mapsへの安全な受け渡し）
import urllib.parse
# ファイルの存在確認（token.jsonがあるかどうか等）
import os.path
# タイムゾーン操作用（JSTやUTCなど、世界中の時間に対応するため）
import pytz
# Google Calendar API連携用（OAuth認証とイベント操作）
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
# --- GPS取得用のライブラリ ---
# Pythonからブラウザ側のJavaScriptを実行し、端末のGPS情報を取得するための拡張機能
from streamlit_js_eval import streamlit_js_eval

# ==========================================
# 0. システム設定（タイムゾーンとCSS）
# ==========================================
# アプリのページ設定（タイトルと、画面を中央に寄せるレイアウト指定）
st.set_page_config(page_title="スケジュール＆移動ルーター", layout="centered")

# --- カスタムCSSの適用 ---
# Streamlitのデフォルトでは左寄りになってしまう入力欄の文字を、中央揃えにしてドラムロール風に見せる
st.markdown("""
<style>
div[data-baseweb="input"] input {
    text-align: center;
    font-size: 18px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

# サイドバーにタイムゾーン選択を配置（デフォルトはAsia/Tokyo）
st.sidebar.header("⚙️ システム設定")
tz_options = ["Asia/Tokyo", "UTC", "US/Pacific", "Europe/London", "Asia/Shanghai"]
selected_tz_str = st.sidebar.selectbox("アプリの基準タイムゾーン", tz_options, index=0)
app_tz = pytz.timezone(selected_tz_str)

# 選択されたタイムゾーンに基づく「現在の正確な日時」を取得
now_with_tz = datetime.now(app_tz)

# ==========================================
# データ管理系の初期化（Session State）
# ==========================================
# Streamlitは画面が操作されるたびにプログラムが上から下へ再実行されるため、
# 消えてほしくないデータは `st.session_state` という裏側の辞書に保存します。

# 徒歩時間の初期化
if "walk_time_train" not in st.session_state:
    st.session_state.walk_time_train = 15
if "walk_time_direct" not in st.session_state:
    st.session_state.walk_time_direct = 15

# --- 出発駅のリスト初期化 ---
if "station_history" not in st.session_state:
    st.session_state.station_history = []
if "station_df" not in st.session_state:
    # 初回起動時にデフォルトで入っている駅のリスト
    st.session_state.station_df = pd.DataFrame([
        {"順番": 1, "出発駅名": "井細田"},
        {"順番": 2, "出発駅名": "足柄(神奈川県)"},
        {"順番": 3, "出発駅名": "小田原"}
    ])

# 削除などの操作が行われる直前に、現在の状態をバックアップする関数
def save_to_history():
    snapshot = st.session_state.station_df.copy()
    timestamp = datetime.now(app_tz).strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.station_history.insert(0, {"time": timestamp, "data": snapshot})
    # 履歴が増えすぎないよう、最新の5件だけを保持する
    if len(st.session_state.station_history) > 5:
        st.session_state.station_history = st.session_state.station_history[:5]

# --- 登録先カレンダーのリスト初期化 ---
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
# 安全な追加・同期用のコールバック関数群
# ==========================================
# ボタンが押された際、画面の再描画が行われる「前」に割り込んで実行される関数。
# これにより、入力欄を空にしてもStreamlitのエラー（後出し変更不可）を回避できます。

# STEP4 ワンタッチ徒歩時間ボタン用の同期
def set_walk_time_callback(mins):
    st.session_state.walk_time_train = mins
    st.session_state.walk_time_direct = mins

# カレンダーの新規追加処理
def add_new_calendar_callback():
    name = st.session_state.new_cal_name_input.strip()
    cal_id = st.session_state.new_cal_id_input.strip()
    if name != "" and cal_id != "":
        save_cal_to_history()
        new_order = len(st.session_state.calendar_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "カレンダー名": name, "カレンダーID": cal_id}])
        st.session_state.calendar_df = pd.concat([st.session_state.calendar_df, new_row], ignore_index=True)
        # 次の入力のために欄をリセット
        st.session_state.new_cal_name_input = ""
        st.session_state.new_cal_id_input = ""

# 出発駅の新規追加処理（メイン画面から）
def add_new_station_callback():
    name = st.session_state.new_station_input.strip()
    if name != "":
        save_to_history()
        new_order = len(st.session_state.station_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "出発駅名": name}])
        st.session_state.station_df = pd.concat([st.session_state.station_df, new_row], ignore_index=True)
        st.session_state.new_station_input = ""

# 出発駅の新規追加処理（サイドバーから）
def add_new_station_sb_callback():
    name = st.session_state.new_station_input_sb.strip()
    if name != "":
        save_to_history()
        new_order = len(st.session_state.station_df) + 1
        new_row = pd.DataFrame([{"順番": new_order, "出発駅名": name}])
        st.session_state.station_df = pd.concat([st.session_state.station_df, new_row], ignore_index=True)
        st.session_state.new_station_input_sb = ""

# STEP4 ワンタッチボタンの新規追加処理
def add_new_preset_callback():
    name = st.session_state.new_p_name_input.strip()
    mins = st.session_state.new_p_time_input
    if name != "":
        if "walk_presets" not in st.session_state:
            st.session_state.walk_presets = []
        st.session_state.walk_presets.append({"name": name, "time": mins})
        st.session_state.new_p_name_input = ""
        st.session_state.new_p_time_input = 10

# STEP3 ワンタッチ駅選択ボタン用（ボタンが押された駅を「選択中」として記憶）
def set_depart_station_callback(sta):
    st.session_state.selected_depart_station = sta

# STEP3 セレクトボックス用（プルダウンが変更された駅を「選択中」として記憶）
def update_depart_station_from_sb():
    st.session_state.selected_depart_station = st.session_state.sb_depart_station


# ==========================================
# サイドバーメニュー（管理機能）
# ==========================================
st.sidebar.markdown("---")

# --- 駅リスト管理のエキスパンダー ---
with st.sidebar.expander("🚉 出発駅リストの管理", expanded=False):
    st.caption("登録済みの駅の確認と削除ができます。")

    for idx, row in st.session_state.station_df.iterrows():
        col_name, col_del = st.columns([4, 1], vertical_alignment="center")
        with col_name: 
            st.markdown(f"**{row['順番']}. {row['出発駅名']}**")
        with col_del:
            # 削除ボタン
            if st.button("🗑️", key=f"del_sta_sb_{idx}", use_container_width=True):
                save_to_history() # 削除前にバックアップ
                st.session_state.station_df = st.session_state.station_df.drop(idx).reset_index(drop=True)
                st.session_state.station_df["順番"] = range(1, len(st.session_state.station_df) + 1)
                st.rerun() # 画面をリロードして反映

    st.divider()
    st.caption("💡 新しい駅を追加")
    # keyを指定することで、自動的にsession_stateに値が格納される
    st.text_input("駅名を入力", key="new_station_input_sb", placeholder="例：箱根板橋", label_visibility="collapsed")
    st.button("➕ 追加", key="add_station_btn_sb", use_container_width=True, on_click=add_new_station_sb_callback)

    # 履歴がある場合のみ復元UIを表示
    if st.session_state.station_history:
        st.divider()
        st.caption("⏪ 変更履歴の管理（直近5件）")
        for i, h in enumerate(st.session_state.station_history):
            st.markdown(f"**{i+1}: {h['time']} の状態**")
            col_res, col_del = st.columns(2)
            with col_res:
                if st.button("⏪ 復元", key=f"hist_res_sb_{i}", use_container_width=True):
                    st.session_state.station_df = h["data"]
                    st.rerun()
            with col_del:
                if st.button("🗑️ 削除", key=f"hist_del_sb_{i}", use_container_width=True):
                    st.session_state.station_history.pop(i)
                    st.rerun()
            st.write("")

# --- カレンダー管理のエキスパンダー ---
with st.sidebar.expander("📅 登録先カレンダーの管理", expanded=False):
    st.caption("Googleカレンダー設定画面の「カレンダーID」を登録します。")

    for idx, row in st.session_state.calendar_df.iterrows():
        col_name, col_del = st.columns([4, 1], vertical_alignment="center")
        with col_name: 
            st.markdown(f"**{row['順番']}. {row['カレンダー名']}**<br><span style='font-size:11px; color:gray;'>{row['カレンダーID']}</span>", unsafe_allow_html=True)
        with col_del:
            # 安全のため、メインカレンダー(primary)は削除不可とする
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


# ==========================================
# メイン画面開始
# ==========================================
st.title("🗓 スケジュール＆移動ルーター")
st.write(f"現在の設定時刻: **{now_with_tz.strftime('%Y/%m/%d %H:%M:%S')}** ({selected_tz_str})")
st.write("確実な手順で、嘘のないスケジュールをカレンダーに登録します。")

# 住所の表記ゆれや不要な情報を削ぎ落とし、マップ検索を正確にする関数
def clean_address(addr):
    if not addr: return ""
    # 1. まず郵便番号（〒〇〇〇-〇〇〇〇）を見つけて完全に除去する
    addr = re.sub(r'〒?\s*[0-9０-９]{3}[-ー][0-9０-９]{4}\s*', '', addr)
    # 2. 全角・半角スペースがある場合は、そこで分割して前半（純粋な住所）だけを残す（ビル名等を落とす）
    addr = re.split(r'[ 　]', addr)[0]
    # 3. さらに細かい番地や部屋番号らしきものを正規表現で丸めて落とす
    addr = re.sub(r'([0-9０-９]+[-ー][0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+[-ー][0-9０-９]+|[0-9０-９]+丁目[0-9０-９]+番[0-9０-９]+号?).*$', r'\1', addr)
    return addr.strip()

# スクロールせずに時間を上下ボタンで操作できる特製UIコンポーネント
def render_hybrid_time_picker(label, state_key, max_value, on_change_callback=None):
    input_key = f"input_{state_key}"
    def increment():
        val = int(st.session_state[state_key])
        new_val = (val + 1) % max_value # 24時を超えたら0時に戻る計算
        st.session_state[state_key] = f"{new_val:02d}"; st.session_state[input_key] = f"{new_val:02d}"
        if on_change_callback: on_change_callback()
    def decrement():
        val = int(st.session_state[state_key])
        new_val = (val - 1) % max_value # 0時を下回ったら23時になる計算
        st.session_state[state_key] = f"{new_val:02d}"; st.session_state[input_key] = f"{new_val:02d}"
        if on_change_callback: on_change_callback()
    def manual_update():
        # ユーザーが直接数字を手打ちした場合、全角を半角に変換して安全に処理する
        raw = st.session_state[input_key].translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        try:
            val = int(raw) % max_value
            st.session_state[state_key] = f"{val:02d}"; st.session_state[input_key] = f"{val:02d}"
        except ValueError:
            # 数字以外が入力されたら元の値に戻す
            st.session_state[input_key] = st.session_state[state_key]
        if on_change_callback: on_change_callback()

    st.markdown(f"<div style='text-align:center; font-size:14px; color:gray;'>{label}</div>", unsafe_allow_html=True)
    st.button("▲", key=f"up_{state_key}", on_click=increment, use_container_width=True)
    st.text_input("hidden", key=input_key, label_visibility="collapsed", on_change=manual_update)
    st.button("▼", key=f"down_{state_key}", on_click=decrement, use_container_width=True)

# ==========================================
# STEP 1: 予定開始時間と目的地の設定
# ==========================================
st.header("1. 予定と目的地の設定")

event_title = st.text_input("予定のタイトル", "")
facility_name = st.text_input("施設名（目的地）", "")
if facility_name:
    # 施設名から住所をGoogle検索するお助けリンク
    st.link_button(f"🔍 「{facility_name}」の住所をGoogleで検索", f"https://www.google.com/search?q={urllib.parse.quote(facility_name + ' 住所')}")

event_address_full = st.text_input("目的地住所（ビル・マンション名まで含む）", "")
# マップ検索用にノイズを落とした住所を作成
cleaned_address = clean_address(event_address_full)
# カレンダー登録用に、施設名と住所を合体させた完全な文字列を作成
full_destination_target = f"{facility_name} {event_address_full}".strip()

# Google Mapsへの検索クエリは、エラーを防ぐため「住所があれば住所、なければ施設名」の単一情報に絞る
search_destination = event_address_full if event_address_full else facility_name
if search_destination:
    st.write("---")
    st.write(f"▼ 🗺️ 目的地のマップ（視覚的確認）")
    # 決定した検索クエリでGoogle Mapの埋め込みプレビューを表示
    components.iframe(f"https://www.google.com/maps?q={urllib.parse.quote(search_destination)}&output=embed", height=350, scrolling=True)

st.write("---")
event_date = st.date_input("予定の日付", datetime.today())

# 時刻入力用の変数を、現在時刻を基準に初期化
if "start_h" not in st.session_state:
    st.session_state.start_h = now_with_tz.strftime("%H"); st.session_state.input_start_h = st.session_state.start_h
if "start_m" not in st.session_state:
    st.session_state.start_m = now_with_tz.strftime("%M"); st.session_state.input_start_m = st.session_state.start_m
if "end_h" not in st.session_state:
    init_end = now_with_tz + timedelta(hours=1)
    st.session_state.end_h = init_end.strftime("%H"); st.session_state.input_end_h = st.session_state.end_h
if "end_m" not in st.session_state:
    st.session_state.end_m = now_with_tz.strftime("%M"); st.session_state.input_end_m = st.session_state.end_m

# 開始時間が変更されたら、自動的に終了時間を「開始の1時間後」に同期させる関数
def sync_end_time():
    h = int(st.session_state.start_h)
    st.session_state.end_h = f"{(h + 1) % 24:02d}"; st.session_state.input_end_h = st.session_state.end_h
    st.session_state.end_m = st.session_state.start_m; st.session_state.input_end_m = st.session_state.start_m

st.write("🕒 **予定開始時間**")
with st.container(border=True):
    c1, c2 = st.columns(2)
    # sync_end_timeをコールバックに指定し、時間が操作されるたびに連動させる
    with c1: render_hybrid_time_picker("時", "start_h", 24, sync_end_time)
    with c2: render_hybrid_time_picker("分", "start_m", 60, sync_end_time)
# 計算用に datetime.time 型のオブジェクトを生成
start_time = time(int(st.session_state.start_h), int(st.session_state.start_m))

st.write("🕒 **予定終了時間**")
with st.container(border=True):
    c1, c2 = st.columns(2)
    with c1: render_hybrid_time_picker("時", "end_h", 24)
    with c2: render_hybrid_time_picker("分", "end_m", 60)
end_time = time(int(st.session_state.end_h), int(st.session_state.end_m))

st.write("---")
# バッファ時間の選択。自由入力の場合は数値入力フィールドを動的に表示する
arrival_buffer_option = st.selectbox("予定開始の何分前に到着しますか？", ["5分前", "10分前", "15分前", "20分前", "自由入力（分）"], index=1)
buffer_minutes = st.number_input("到着バッファ（分）", value=30, min_value=0, step=1) if arrival_buffer_option == "自由入力（分）" else int(re.search(r'\d+', arrival_buffer_option).group())

# 開始時刻からバッファ分を引いて、最終的な「目標到着時刻」を逆算
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

# トグルボタン風のUI。選択されている方は primary(青色) で目立たせる
c1, c2 = st.columns(2)
with c1:
    if st.button("🚃 電車を利用する", use_container_width=True, type="primary" if st.session_state.travel_mode == "🚃 電車を利用する" else "secondary"):
        st.session_state.travel_mode = "🚃 電車を利用する"; st.rerun()
with c2:
    if st.button("🚶 徒歩のみ（近場）", use_container_width=True, type="primary" if st.session_state.travel_mode == "🚶 徒歩のみ" else "secondary"):
        st.session_state.travel_mode = "🚶 徒歩のみ"; st.rerun()

# 以降の処理を分岐するための変数
travel_mode = st.session_state.travel_mode

# 各種計算用の変数を一旦リセット
train_depart_time = None; train_arrive_time = None; depart_station = ""; walk_to_dest = 0

# 再描画時に消えないよう、入力欄の初期値をsession_stateに確保
if "arrival_station_input" not in st.session_state:
    st.session_state.arrival_station_input = ""


# ==========================================
# STEP 2 & 3（電車モード限定）
# ==========================================
if travel_mode == "🚃 電車を利用する":
    with st.expander("🚃 STEP 2: 降車駅の検索と徒歩計算", expanded=True):
        if search_destination:
            # 目的地周辺の駅をGoogle Mapsで検索するための動的リンク
            around_target = cleaned_address if cleaned_address else facility_name
            st.write("▼ 🚉 周辺の駅を探す")
            st.link_button("🔍 地図を開いて周辺の駅を探す", f"https://www.google.com/maps/search/{urllib.parse.quote('周辺の駅 around:'+around_target)}", use_container_width=True)

        st.write("▼ 🚉 目的地の近隣駅を入力")
        # keyを指定しているため、ユーザーの入力は即座に裏側の memory (arrival_station_input) に保存される
        st.text_input("地図を確認して近隣駅（降車駅）を入力してください", key="arrival_station_input")

        current_arrival_station = st.session_state.arrival_station_input

        if current_arrival_station and search_destination:
            # ユーザーが「〇〇駅」と入力していても、二重の「駅駅」にならないように末尾の「駅」を除去
            clean_sta = re.sub(r'駅$', '', current_arrival_station)
            # URLを生成するときに初めて「駅」を付与して安全に検索させる
            st.link_button(f"🚶‍♂️ {clean_sta}駅から目的地までのルートを確認", f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(clean_sta + '駅')}&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
        elif current_arrival_station and not search_destination:
            st.caption("※STEP 1で目的地を入力すると、ここから目的地までの徒歩ルート確認ボタンが表示されます。")

        st.write("---")
        st.write(f"🚉 確定した駅: **{current_arrival_station if current_arrival_station else '（未入力）'}**")
        # ここで徒歩分数を入力し、電車のタイムリミットをさらに逆算する
        walk_to_dest = st.number_input(f"駅から目的地までの徒歩時間（分）", value=5, step=1)
        train_deadline_dt = target_arrival_dt - timedelta(minutes=walk_to_dest)
        
        # 表示用にもキレイにした文字列を使用
        display_sta = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else "〇〇"
        st.success(f"🚃 **{display_sta}駅** に **{train_deadline_dt.strftime('%H:%M')}** までに到着する電車を探します。")

    with st.expander("🚃 STEP 3: ルート検索と電車の時刻入力", expanded=False):
        st.write("▼ 📍 現在地から出発駅を探す")
        if st.toggle("🌍 GPSを起動して現在地を取得する", value=False):
            # JSを実行してブラウザのGPS APIを呼び出し、結果をPythonの変数(loc)で受け取る高度な連携
            loc = streamlit_js_eval(js_expressions="new Promise((res, rej) => { navigator.geolocation.getCurrentPosition((p) => { res({lat: p.coords.latitude, lng: p.coords.longitude}); }, (e) => { res({error: e.message}); }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}); })", key="gps_promise_fetch")
            if loc:
                if "error" in loc: st.error(f"❌ 位置情報の取得に失敗: {loc['error']}")
                else:
                    st.success("✅ 位置情報の取得に成功しました！")
                    st.link_button("↗️ 現在地周辺の駅をGoogleMapで表示", f"https://www.google.com/maps?q={urllib.parse.quote('駅')}&ll={loc['lat']},{loc['lng']}&z=16", use_container_width=True)
            else: st.info("⌛ 位置情報を取得中...")

        st.write("---")
        st.write("▼ 出発駅の追加")
        st.caption("💡 新しい駅を追加する場合は入力してボタンを押してください。（リストの確認・削除は左上の「＞」メニューから）")
        c1, c2 = st.columns([3, 1])
        with c1: st.text_input("駅名を入力", key="new_station_input", label_visibility="collapsed", placeholder="例：箱根板橋")
        with c2: st.button("➕ 追加", key="add_station_btn", use_container_width=True, on_click=add_new_station_callback)

        st.write("---")
        
        # セッションから空文字以外の有効な駅リストを抽出
        valid_stations = [s for s in st.session_state.station_df["出発駅名"].tolist() if s and str(s).strip() != ""]
        if not valid_stations: valid_stations = ["駅名を入力してください"]
        
        # 現在選択されている駅を管理（なければリストの先頭をセット）
        if "selected_depart_station" not in st.session_state or st.session_state.selected_depart_station not in valid_stations:
            st.session_state.selected_depart_station = valid_stations[0]

        st.write("▼ 今回利用する出発駅を選択")
        
        # 1. ワンタッチボタンUI（頻繁に使う上位6駅用）
        st.caption("👆 ワンタッチ選択")
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

        # 2. セレクトボックスUI（全リストからの選択用。ボタンと状態が同期する）
        st.caption("🔽 リストから選択")
        current_index = valid_stations.index(st.session_state.selected_depart_station) if st.session_state.selected_depart_station in valid_stations else 0
        st.selectbox(
            "出発駅", 
            valid_stations, 
            index=current_index, 
            key="sb_depart_station",
            on_change=update_depart_station_from_sb,
            label_visibility="collapsed"
        )
        
        # 最終的に確定した出発駅
        depart_station = st.session_state.selected_depart_station

        # 降車駅も「〇〇駅駅」にならないように末尾をカットしてジョルダンに渡す
        clean_arrival_sta_for_jorudan = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else ""
        
        # ジョルダン乗換案内のURLパラメータ。日時や時間を細かく指定して直接検索結果に飛ばす
        jorudan_params = {"eki1": depart_station, "eki2": clean_arrival_sta_for_jorudan, "Dym": event_date.strftime("%Y%m"), "Ddd": event_date.strftime("%d"), "Dhh": train_deadline_dt.strftime("%H"), "Dmn1": str(train_deadline_dt.minute // 10), "Dmn2": str(train_deadline_dt.minute % 10), "Cway": "1"}
        st.link_button("↗️ ジョルダン乗換案内でルートを検索", "https://www.jorudan.co.jp/norikae/cgi/nori.cgi?" + urllib.parse.urlencode(jorudan_params))

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
# STEP 4: 出発前の準備（逆算ロジックのコア）
# ==========================================
st.header("4. 出発前の準備")
st.write("---")
st.write("▼ 🏠 自宅からの徒歩時間（ワンタッチ入力）")

if "walk_presets" not in st.session_state:
    st.session_state.walk_presets = [{"name": "井細田", "time": 5}, {"name": "足柄", "time": 15}, {"name": "小田原", "time": 28}]

cols = st.columns(3)
for i, preset in enumerate(st.session_state.walk_presets):
    with cols[i % 3]:
        # ワンタッチボタン。押された分数が下の入力欄に一瞬で同期する
        st.button(f"🏠 {preset['name']} ({preset['time']}分)", on_click=set_walk_time_callback, args=(preset['time'],), key=f"preset_btn_{i}", use_container_width=True)

with st.expander("⚙️ ワンタッチボタンの編集（追加・削除）"):
    st.caption("【削除】不要なボタンは横の削除ボタンで消せます。")
    for i, preset in enumerate(st.session_state.walk_presets):
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="center")
        with c1: st.markdown(f"**{preset['name']}**")
        with c2: st.markdown(f"{preset['time']}分")
        with c3:
            if st.button("🗑️ 削除", key=f"del_preset_{i}", use_container_width=True):
                st.session_state.walk_presets.pop(i)
                st.rerun()
    st.divider()
    if len(st.session_state.walk_presets) < 6:
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="bottom")
        with c1: st.text_input("表示名", key="new_p_name_input", placeholder="例: コンビニ")
        with c2: st.number_input("分", min_value=1, value=10, step=1, key="new_p_time_input")
        with c3: st.button("➕ 追加", key="add_preset_btn", use_container_width=True, on_click=add_new_preset_callback)

st.write("---")

# 最終的な出発時間と準備開始時間を逆算するロジック（モード別）
if travel_mode == "🚃 電車を利用する":
    # train_depart_time（電車出発）を基準に逆算
    walk_to_station = st.number_input("現在地から【利用する出発駅】までの徒歩時間（分）", key="walk_time_train", step=1)
    prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1, key="prep_time_train")
    
    leave_home_dt = datetime.combine(event_date, train_depart_time) - timedelta(minutes=walk_to_station)
    start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

else:
    # 徒歩のみの場合は target_arrival_dt（目標到着）を基準に逆算
    st.write("▼ 🗺️ 目的地までの徒歩ルートと時間を確認")
    if st.toggle("🌍 GPSを起動して現在地を取得する", key="use_gps_walk", value=False):
        loc_walk = streamlit_js_eval(js_expressions="new Promise((res, rej) => { navigator.geolocation.getCurrentPosition((p) => { res({lat: p.coords.latitude, lng: p.coords.longitude}); }, (e) => { res({error: e.message}); }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}); })", key="gps_promise_fetch_walk")
        if loc_walk:
            if "error" in loc_walk: st.error(f"❌ 位置情報の取得に失敗: {loc_walk['error']}")
            else:
                st.success("✅ 位置情報の取得に成功しました！")
                if search_destination:
                    # GPS座標を始点（origin）としてGoogle Mapルート検索URLを生成
                    st.link_button("🚶‍♂️ 取得した現在地からの徒歩ルートを確認", f"https://www.google.com/maps/dir/?api=1&origin={loc_walk['lat']},{loc_walk['lng']}&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
                    st.caption("※Googleマップで表示された「徒歩〇〇分」の数字を、下の入力欄にセットしてください。")
                else: st.warning("目的地が入力されていません。")
        else: st.info("⌛ 位置情報を取得中...")
    else:
        if search_destination:
            # GPSがない場合は、Googleに現在地の特定を委ねるURLを生成
            st.link_button("🚶‍♂️ 現在地から目的地までの徒歩ルートを確認", f"https://www.google.com/maps/dir/?api=1&destination={urllib.parse.quote(search_destination)}&travelmode=walking", use_container_width=True)
            st.caption("※Googleマップで表示された「徒歩〇〇分」の数字を、下の入力欄にセットしてください。")
        else: st.warning("目的地が入力されていません。")
        
    walk_to_dest_direct = st.number_input("現在地から【目的地】までの総徒歩時間（分）", key="walk_time_direct", step=1)
    prep_time = st.number_input("移動前の準備（仕度）時間（分）", value=15, step=1, key="prep_time_direct")
    
    leave_home_dt = target_arrival_dt - timedelta(minutes=walk_to_dest_direct)
    start_prep_dt = leave_home_dt - timedelta(minutes=prep_time)

# 逆算結果のハイライト表示
st.info(f"🏁 **目標到着時刻: {target_arrival_dt.strftime('%H:%M')}**")
st.error(f"🏠 **準備開始時刻: {start_prep_dt.strftime('%H:%M')}**")
st.warning(f"🚶 **出発時刻: {leave_home_dt.strftime('%H:%M')}**")


# ==========================================
# STEP 5: カレンダー登録（Google API連携）
# ==========================================
st.header("5. カレンダー登録")

st.write("▼ 登録先カレンダーの選択")
# ユーザーがサイドバーで登録したカレンダーの一覧からプルダウンを生成
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

if st.button("📅 カレンダーに登録"):
    try:
        # スピナーを表示し、処理中であることをユーザーに伝える
        with st.spinner("Googleカレンダーに通信中..."):
            SCOPES = ['https://www.googleapis.com/auth/calendar']
            creds = None
            
            # --- OAuth2.0 認証フロー ---
            # 過去のログイン情報（通行証）があれば利用
            if os.path.exists('token.json'):
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            # クラウド環境でのシークレット認証
            elif "GOOGLE_TOKEN_JSON" in st.secrets:
                creds = Credentials.from_authorized_user_info(json.loads(st.secrets["GOOGLE_TOKEN_JSON"]), SCOPES)
            
            # 通行証が無効、または有効期限切れの場合の再認証
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
                else: st.error("❌ 認証エラー: 再認証が必要です。"); st.stop()

            # Google Calendar APIのインスタンスを構築
            service = build('calendar', 'v3', credentials=creds)

            # カレンダーに予定（イベント）を挿入する共通関数
            def insert_event(summary, start_datetime, end_datetime, location=""):
                service.events().insert(
                    calendarId=selected_calendar_id, 
                    body={
                        'summary': summary, 
                        'location': location, 
                        'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'}, 
                        'end': {'dateTime': end_datetime.isoformat(), 'timeZone': 'Asia/Tokyo'}
                    }
                ).execute()

            # --- カレンダーへの書き込み（電車モード） ---
            if travel_mode == "🚃 電車を利用する":
                train_arrive_dt = datetime.combine(event_date, train_arrive_time)
                # 夜行電車などで日をまたぐ場合の補正
                if train_arrive_dt < datetime.combine(event_date, train_depart_time): train_arrive_dt += timedelta(days=1)
                actual_arrive_dt = train_arrive_dt + timedelta(minutes=walk_to_dest)

                # カレンダー登録時も、重複した「駅」の文字をカットしてスマートに表示
                clean_arrival_sta_for_cal = re.sub(r'駅$', '', current_arrival_station) if current_arrival_station else ""

                # 逆算した各フェーズのスケジュールを順番にAPIへ送信
                insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
                insert_event(f"🚶 徒歩（自宅〜{depart_station}駅）：{event_title}", leave_home_dt, datetime.combine(event_date, train_depart_time))
                if include_train_event:
                    insert_event(f"🚃 電車（{depart_station}駅〜{clean_arrival_sta_for_cal}駅）：{event_title}", datetime.combine(event_date, train_depart_time), train_arrive_dt)
                insert_event(f"🚶 徒歩（{clean_arrival_sta_for_cal}駅〜目的地）：{event_title}", train_arrive_dt, actual_arrive_dt)
                insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)
                
                st.success("✅ 準備から移動の詳細、本番までをカレンダーに登録しました！" if include_train_event else "✅ 電車の乗車時間を除く予定をカレンダーに登録しました！")

            # --- カレンダーへの書き込み（徒歩モード） ---
            else:
                insert_event(f"🏠 準備：{event_title}", start_prep_dt, leave_home_dt)
                insert_event(f"🚶 徒歩（出発地〜目的地）：{event_title}", leave_home_dt, target_arrival_dt)
                insert_event(event_title, event_dt, datetime.combine(event_date, end_time), location=full_destination_target)
                
                st.success("✅ 準備、徒歩移動、本番の3つの予定をカレンダーに登録しました！")

        # 処理完了の風船アニメーション
        st.balloons()
    except Exception as e:
        # 万が一API通信等でエラーが起きた場合のキャッチ
        st.error(f"❌ 登録失敗: {e}")