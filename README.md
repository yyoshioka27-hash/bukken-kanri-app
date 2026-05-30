# 物件管理アプリ 第三段階（Streamlit Cloud対応）

## ローカル起動方法
1. 依存関係をインストール
   ```bash
   pip install -r requirements.txt
   ```
2. アプリを起動
   ```bash
   streamlit run app_bkanri.py
   ```

## Streamlit Cloud公開時に必要なファイル
- `app_bkanri.py`（メインファイル）
- `requirements.txt`（必須）

## 補足
- Streamlit Cloudでは `requirements.txt` がないと依存ライブラリがインストールされないため、必ず配置してください。
- メインファイルは `app_bkanri.py` を指定してください。
- 音声メモの録音には Streamlit 1.40.0 以上の `st.audio_input` を使用します。依存関係は `pip install -r requirements.txt` で導入できます。
- ブラウザで録音するにはマイク権限が必要です。録音ボタンが反応しない場合は、ブラウザのマイク許可を確認してください。
- データはアプリ配下の `data/` 以下に保存されます（`data`, `backup`, `export_pdf`, `export_text` は初回起動時に自動作成）。
