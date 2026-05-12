from google_auth_oauthlib.flow import InstalledAppFlow

# Googleカレンダーの予定を編集する権限を要求
SCOPES = ['https://www.googleapis.com/auth/calendar']

print("Google認証を開始します...")

# credentials.json を読み込む
flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)

# ★ここが重要：ブラウザを自動で開かない設定（open_browser=False）にし、ポートを8080に固定する
creds = flow.run_local_server(port=8080, open_browser=False)

# 取得した許可証を token.json として保存
with open('token.json', 'w') as token:
    token.write(creds.to_json())

print("✅ 認証完了！ token.json が作成されました！")