# app_bkanri.py

import streamlit as st
import json
import os
import shutil
import tempfile
import uuid
import html
import urllib.parse
import base64
import unicodedata
import requests
import qrcode
from faster_whisper import WhisperModel
from datetime import datetime, date
from io import BytesIO
from pathlib import Path

try:
    from streamlit_local_storage import LocalStorage
except Exception:
    LocalStorage = None

APP_TITLE = "物件管理アプリ"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "bukken_data.json"

# 既存関数からも参照するため、ファイル名とGitHub上の保存先は定数として残す。
DATA_FILE_NAME = DATA_FILE.name
GITHUB_DATA_PATH = f"data/{DATA_FILE_NAME}"
APP_PUBLIC_URL = "https://bukken-kanri-app-bgm7sywfwtxeuojvhaeks.streamlit.app/"

STATUSES = ["未対応", "対応中", "対応済", "連絡待ち","保留"]
PRIORITIES = ["低", "中", "高", "スケジュール"]

LOCAL_STORAGE_KEY = "bukken_kanri_data_v1"
APP_STATE_STORAGE_KEY = "bukken_kanri_app_state_v1"


def notify_action_start(message="処理を開始しました"):
    st.toast(message)


def rerun_app():
    """Streamlit のバージョン差を吸収して画面を即時再描画する。"""
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def queue_feedback(kind, message):
    st.session_state.setdefault("_feedback_messages", []).append({"kind": kind, "message": message})


def show_queued_feedback():
    for feedback in st.session_state.pop("_feedback_messages", []):
        message = feedback.get("message", "")
        kind = feedback.get("kind", "info")
        if message:
            st.toast(message)
        if kind == "success":
            st.success(message)
        elif kind == "error":
            st.error(message)
        elif kind == "warning":
            st.warning(message)
        elif message:
            st.info(message)


def notify_download_start(message):
    st.toast(message)


def notify_json_download_complete():
    st.session_state["json_download_notice"] = True
    st.toast("最新JSONをダウンロードしました")


@st.cache_data
def build_app_qr_code_bytes():
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(APP_PUBLIC_URL)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def get_local_storage_data():
    if LocalStorage is None:
        return None

    try:
        local_storage = LocalStorage()
        raw = local_storage.getItem(LOCAL_STORAGE_KEY)
        if not raw:
            return None
        return normalize_data(json.loads(raw))
    except Exception:
        return None


def save_local_storage_data(data):
    if LocalStorage is None:
        return

    try:
        local_storage = LocalStorage()
        local_storage.setItem(LOCAL_STORAGE_KEY, json.dumps(normalize_data(data), ensure_ascii=False))
    except Exception:
        pass


def persist_data(data):
    """画面操作で変更されたデータを session_state とアプリ内JSONへ即時保存する。"""
    normalized = normalize_data(data)
    st.session_state["data"] = normalized
    save_local_data(normalized)
    save_local_storage_data(normalized)
    save_app_state()


def normalize_filter_mode(value):
    valid_modes = ["すべて", "未対応あり", "重要度高あり"]
    return value if value in valid_modes else "すべて"


def save_app_state():
    if LocalStorage is None:
        return

    try:
        local_storage = LocalStorage()
        payload = {
            "data": normalize_data(st.session_state.get("data", {"projects": []})),
            "selected_project_id": st.session_state.get("selected_project_id"),
            "selected_property_id": st.session_state.get("selected_property_id"),
            "current_view": st.session_state.get("current_view", "list"),
            "filter_mode": normalize_filter_mode(st.session_state.get("filter_mode", "すべて")),
        }
        local_storage.setItem(APP_STATE_STORAGE_KEY, json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def load_app_state():
    if LocalStorage is None:
        return None

    try:
        local_storage = LocalStorage()
        raw = local_storage.getItem(APP_STATE_STORAGE_KEY)
        if not raw:
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return {
            "data": normalize_data(payload.get("data", {"projects": []})),
            "selected_project_id": payload.get("selected_project_id"),
            "selected_property_id": payload.get("selected_property_id") or payload.get("selected_project_id"),
            "current_view": payload.get("current_view", "list"),
            "filter_mode": normalize_filter_mode(payload.get("filter_mode", "すべて")),
        }
    except Exception:
        return None


def load_initial_data():
    """起動時にアプリ内JSONを優先して読み込み、前回状態を復元する。"""
    app_state = load_app_state()
    if app_state is not None:
        selected_id = app_state.get("selected_property_id") or app_state.get("selected_project_id")
        st.session_state["selected_project_id"] = selected_id
        st.session_state["selected_property_id"] = selected_id
        st.session_state["current_view"] = app_state.get("current_view", "list")
        st.session_state["filter_mode"] = app_state.get("filter_mode", "すべて")

    local_data = load_local_data()
    if local_data is not None:
        st.session_state["_auto_loaded_local_data"] = True
        return local_data

    local_storage_data = get_local_storage_data()
    if local_storage_data is not None:
        return local_storage_data

    return {"projects": []}


def get_data_file():
    return DATA_FILE


def get_data_dir():
    return DATA_DIR


def get_backup_dir():
    return get_data_dir() / "backup"


def get_export_text_dir():
    return get_data_dir() / "export_text"


def get_export_pdf_dir():
    return get_data_dir() / "export_pdf"


def init_dirs():
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    get_backup_dir().mkdir(parents=True, exist_ok=True)
    get_export_text_dir().mkdir(parents=True, exist_ok=True)
    get_export_pdf_dir().mkdir(parents=True, exist_ok=True)


def normalize_data(data):
    if not isinstance(data, dict):
        return {"projects": []}
    if "projects" not in data or not isinstance(data["projects"], list):
        data["projects"] = []
    return data


def load_local_data():
    """アプリ内の data/bukken_data.json を読み込み、存在しない/壊れている場合は None を返す。"""
    init_dirs()
    data_file = get_data_file()
    if not data_file.exists():
        return None

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return normalize_data(data)
    except Exception:
        return None


def save_local_data(data):
    """アプリ内の data/bukken_data.json へ現在データを自動保存する。"""
    init_dirs()
    normalized = normalize_data(data)
    data_file = get_data_file()
    backup_dir = get_backup_dir()
    if data_file.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(data_file, backup_dir / f"bukken_data_{ts}.json")
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)


def load_data():
    """後方互換用: アプリ内JSONを読み込み、なければ空データを返す。"""
    return load_local_data() or {"projects": []}


def save_data(data):
    """後方互換用: アプリ内JSONへ保存する。"""
    save_local_data(data)


def _github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_file_api_url(repo, path):
    return f"https://api.github.com/repos/{repo}/contents/{path}"


def load_data_from_github():
    token = st.secrets.get("GITHUB_TOKEN")
    repo = st.secrets.get("GITHUB_REPO")
    if not token or not repo:
        return None, "Streamlit secrets に GITHUB_TOKEN / GITHUB_REPO が未設定です。"

    url = _github_file_api_url(repo, GITHUB_DATA_PATH)
    try:
        response = requests.get(url, headers=_github_headers(token), timeout=20)
        if response.status_code == 404:
            empty_data = {"projects": []}
            create_error = save_data_to_github(empty_data)
            if create_error:
                return None, f"GitHubファイルが未作成で、自動作成にも失敗しました: {create_error}"
            return empty_data, None
        response.raise_for_status()
        payload = response.json()
        encoded = payload.get("content", "")
        if not encoded:
            return {"projects": []}, None
        decoded = base64.b64decode(encoded).decode("utf-8")
        return normalize_data(json.loads(decoded)), None
    except requests.RequestException as e:
        return None, f"通信エラー: {e}"
    except Exception as e:
        return None, f"解析エラー: {e}"


def save_data_to_github(data):
    token = st.secrets.get("GITHUB_TOKEN")
    repo = st.secrets.get("GITHUB_REPO")
    if not token or not repo:
        return "Streamlit secrets に GITHUB_TOKEN / GITHUB_REPO が未設定です。"

    url = _github_file_api_url(repo, GITHUB_DATA_PATH)
    sha = None
    try:
        current = requests.get(url, headers=_github_headers(token), timeout=20)
        if current.status_code == 200:
            sha = current.json().get("sha")
        elif current.status_code != 404:
            current.raise_for_status()

        body = {
            "message": f"Update {GITHUB_DATA_PATH}",
            "content": base64.b64encode(
                json.dumps(normalize_data(data), ensure_ascii=False, indent=2).encode("utf-8")
            ).decode("utf-8"),
        }
        if sha:
            body["sha"] = sha

        put_response = requests.put(url, headers=_github_headers(token), json=body, timeout=20)
        put_response.raise_for_status()
        return None
    except requests.RequestException as e:
        return f"通信エラー: {e}"
    except Exception as e:
        return f"保存処理エラー: {e}"


def open_path(path_text):
    if not path_text:
        st.warning("パスが登録されていません。")
        return

    path_text = str(path_text).strip().strip('"').strip("'")
    path = Path(path_text)

    if not path.exists():
        st.error(f"指定されたファイルまたはフォルダが見つかりません：{path_text}")
        return

    try:
        os.startfile(str(path))
    except Exception:
        try:
            os.system(f'explorer "{path_text}"')
        except Exception as e:
            st.error(f"開けませんでした: {e}")


def sanitize_windows_filename(name):
    invalid_chars = '<>:"/\\|?*'
    safe = "".join("_" if c in invalid_chars else c for c in str(name))
    safe = safe.strip().strip(".")
    return safe or "project"


def build_structural_memo_text(project):
    """選択物件のやり取り履歴から、A4印刷しやすい構造設計メモtxt本文を作成する。"""
    project_name = project.get("name", "")
    client = project.get("client", "")
    created_at = project.get("created_at", "")
    folder_path = project.get("folder_path", "")
    schedule_pdf_path = project.get("schedule_pdf_path", "")
    logs = sorted(project.get("logs", []), key=lambda x: x.get("date", ""))

    lines = []
    lines.append("構造設計メモ")
    lines.append("=" * 60)
    lines.append(f"物件名：{project_name}")
    lines.append(f"相手先・担当：{client}")
    lines.append(f"登録日：{created_at}")
    lines.append(f"出力日：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("【パス情報】")
    lines.append(f"物件フォルダ：{folder_path}")
    lines.append(f"工程表PDF：{schedule_pdf_path}")
    lines.append("")
    lines.append("【集計】")
    lines.append(f"未対応・対応中：{count_open_logs(project)} 件")
    lines.append(f"重要度高：{count_high_logs(project)} 件")
    lines.append("")
    lines.append("【やり取り履歴】")

    if not logs:
        lines.append("表示するやり取りはありません。")
    else:
        for i, log in enumerate(logs, start=1):
            lines.append("-" * 60)
            lines.append(f"No.{i}")
            lines.append(f"日付：{log.get('date', '')}")
            lines.append(f"状態：{log.get('status', '')}")
            lines.append(f"期限：{log.get('due_date', '')}")
            lines.append(f"相手先：{log.get('person', '')}")
            lines.append(f"重要度：{log.get('priority', '')}")
            attachment_path = log.get("attachment_path", "")
            if attachment_path:
                lines.append(f"添付：{attachment_path}")
            lines.append("内容：")
            lines.append(str(log.get("content", "")))

    lines.append("=" * 60)
    lines.append("# END")
    return "\n".join(lines)




def build_structural_memo_pdf(project):
    """選択物件のやり取り履歴をPDF出力用バイト列として作成する。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"{project.get('name', '')}_やり取り履歴",
    )
    styles = getSampleStyleSheet()
    base_style = ParagraphStyle(
        "JapaneseBody",
        parent=styles["BodyText"],
        fontName="HeiseiMin-W3",
        fontSize=10,
        leading=14,
        wordWrap="CJK",
        spaceAfter=4,
    )
    title_style = ParagraphStyle(
        "JapaneseTitle",
        parent=styles["Title"],
        fontName="HeiseiMin-W3",
        fontSize=16,
        leading=22,
        wordWrap="CJK",
        spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "JapaneseSection",
        parent=base_style,
        fontSize=12,
        leading=16,
        spaceBefore=8,
        spaceAfter=6,
    )

    def paragraph(text, style=base_style):
        escaped = html.escape(str(text)).replace("\n", "<br/>")
        return Paragraph(escaped, style)

    logs = sorted(project.get("logs", []), key=lambda x: x.get("date", ""))
    story = [paragraph("構造設計メモ / やり取り履歴", title_style)]
    story.extend(
        [
            paragraph(f"物件名：{project.get('name', '')}"),
            paragraph(f"相手先・担当：{project.get('client', '')}"),
            paragraph(f"登録日：{project.get('created_at', '')}"),
            paragraph(f"出力日：{datetime.now().strftime('%Y-%m-%d %H:%M')}"),
            Spacer(1, 4 * mm),
            paragraph("【パス情報】", section_style),
            paragraph(f"物件フォルダ：{project.get('folder_path', '')}"),
            paragraph(f"工程表PDF：{project.get('schedule_pdf_path', '')}"),
            Spacer(1, 4 * mm),
            paragraph("【集計】", section_style),
            paragraph(f"未対応・対応中：{count_open_logs(project)} 件"),
            paragraph(f"重要度高：{count_high_logs(project)} 件"),
            Spacer(1, 4 * mm),
            paragraph("【やり取り履歴】", section_style),
        ]
    )

    if not logs:
        story.append(paragraph("表示するやり取りはありません。"))
    else:
        for i, log in enumerate(logs, start=1):
            attachment_path = log.get("attachment_path", "")
            story.append(paragraph("-" * 58))
            story.append(paragraph(f"No.{i}"))
            story.append(paragraph(f"日付：{log.get('date', '')}"))
            story.append(paragraph(f"状態：{log.get('status', '')}"))
            story.append(paragraph(f"期限：{log.get('due_date', '')}"))
            story.append(paragraph(f"相手先：{log.get('person', '')}"))
            story.append(paragraph(f"重要度：{log.get('priority', '')}"))
            if attachment_path:
                story.append(paragraph(f"添付：{attachment_path}"))
            story.append(paragraph("内容："))
            story.append(paragraph(log.get("content", "")))
            story.append(Spacer(1, 2 * mm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def save_structural_memo_pdf(project):
    """構造設計メモPDFを保存し、保存パスとPDFバイト列を返す。"""
    init_dirs()
    pdf_bytes = build_structural_memo_pdf(project)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_windows_filename(project.get("name", "project"))
    file_path = get_export_pdf_dir() / f"{safe_name}_やり取り履歴_{today}.pdf"

    with open(file_path, "wb") as f:
        f.write(pdf_bytes)

    return file_path, pdf_bytes


@st.cache_resource(show_spinner=False)
def load_whisper_model(model_size="small"):
    """faster-whisper のモデルを一度だけ読み込み、以後はキャッシュして再利用する。"""
    return WhisperModel(model_size, device="cpu", compute_type="int8")


def transcribe_audio_bytes(audio_bytes, model_size="small"):
    """録音バイト列を一時 wav ファイルへ保存し、日本語文字起こし結果を返す。"""
    temp_audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
            temp_audio.write(audio_bytes)
            temp_audio.flush()
            temp_audio_path = temp_audio.name

        model = load_whisper_model(model_size)
        segments, _ = model.transcribe(temp_audio_path, language="ja")
        return "".join(segment.text for segment in segments).strip()
    finally:
        if temp_audio_path:
            Path(temp_audio_path).unlink(missing_ok=True)


def append_voice_memo_text(current_text, transcript):
    """既存の音声メモを上書きせず、文字起こし結果を末尾へ追記する。"""
    transcript = transcript.strip()
    if not transcript:
        return current_text

    if not current_text.strip():
        return transcript

    return f"{current_text.rstrip()}\n{transcript}"


def render_audio_memo_recorder(project_id, voice_memo_key=None):
    """ブラウザのマイク録音ウィジェットと文字起こし操作を表示する。"""
    audio_state_key = f"voice_memo_audio_bytes_{project_id}"
    audio_mime_key = f"voice_memo_audio_mime_{project_id}"
    audio_name_key = f"voice_memo_audio_name_{project_id}"

    if audio_state_key not in st.session_state:
        st.session_state[audio_state_key] = None
    if audio_mime_key not in st.session_state:
        st.session_state[audio_mime_key] = "audio/wav"
    if audio_name_key not in st.session_state:
        st.session_state[audio_name_key] = ""

    if not hasattr(st, "audio_input"):
        st.error(
            "このStreamlit環境では st.audio_input が利用できません。"
            "ブラウザ録音を使うには Streamlit を最新版へ更新してください。"
        )
        st.code("pip install -U streamlit", language="bash")
        return None

    st.info("🎙 マイクボタンを押すと録音を開始します。停止後は文字起こしできます。")
    recorded_audio = st.audio_input(
        "録音開始・停止",
        key=f"voice_memo_audio_input_{project_id}",
    )

    if recorded_audio is not None:
        audio_bytes = recorded_audio.getvalue()
        if audio_bytes:
            st.session_state[audio_state_key] = audio_bytes
            st.session_state[audio_mime_key] = getattr(recorded_audio, "type", None) or "audio/wav"
            st.session_state[audio_name_key] = getattr(recorded_audio, "name", "") or "recorded_audio.wav"
            st.toast("録音を停止しました")
            st.success("録音データを受け取りました。文字起こしできます。")
        else:
            st.session_state[audio_state_key] = None
            st.error("文字起こしに失敗しました。マイク許可または録音データを確認してください")

    audio_bytes = st.session_state.get(audio_state_key)
    if audio_bytes and st.button("文字起こしする", key=f"transcribe_voice_audio_{project_id}", type="primary"):
        notify_action_start("文字起こし中です...")
        try:
            with st.spinner("文字起こし中です..."):
                transcript = transcribe_audio_bytes(audio_bytes)

            if not transcript:
                st.error("文字起こしに失敗しました。マイク許可または録音データを確認してください")
            elif voice_memo_key:
                current_text = st.session_state.get(voice_memo_key, "")
                st.session_state[voice_memo_key] = append_voice_memo_text(current_text, transcript)
                st.toast("文字起こしが完了しました")
                st.success("文字起こしが完了しました")
        except Exception:
            st.error("文字起こしに失敗しました。マイク許可または録音データを確認してください")

    return audio_bytes


def save_structural_memo_text(project):
    """構造設計メモtxtを保存し、保存パスと本文を返す。"""
    init_dirs()
    memo_text = build_structural_memo_text(project)
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_windows_filename(project.get("name", "project"))
    file_path = get_export_text_dir() / f"{safe_name}_構造設計メモ_{today}.txt"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(memo_text)

    return file_path, memo_text



def normalize_text(value):
    """検索用に値を文字列化し、大小文字・全角半角・カナ差分をできるだけ吸収する。"""
    if value is None:
        return ""

    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    # カタカナをひらがなに寄せ、ひらがな・カタカナの違いも簡易的に吸収する。
    text = "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
        for char in text
    )
    return text


def flatten_project_text(project):
    """物件データ内の文字列・数値・日付などを再帰的に集約して検索用テキストを作る。"""
    parts = []

    def collect(value):
        if value is None:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                parts.append(normalize_text(key))
                collect(child)
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                collect(child)
            return
        parts.append(normalize_text(value))

    collect(project)
    return " ".join(part for part in parts if part)


def match_keywords(project, query):
    """複数キーワードを空白区切りで分割し、すべて含む物件だけTrueにする。"""
    normalized_query = normalize_text(query)
    keywords = [keyword for keyword in normalized_query.split() if keyword]
    if not keywords:
        return True

    project_text = flatten_project_text(project)
    return all(keyword in project_text for keyword in keywords)


def filter_projects_by_keyword(projects, query):
    """元データを書き換えず、検索条件に一致する物件リストだけを返す。"""
    if not normalize_text(query):
        return list(projects)
    return [project for project in projects if match_keywords(project, query)]

def get_project(data, project_id):
    for p in data["projects"]:
        if p["id"] == project_id:
            return p
    return None


def count_open_logs(project):
    return len(
        [
            x
            for x in project.get("logs", [])
            if x.get("status") in ["未対応", "対応中"]
        ]
    )


def count_high_logs(project):
    return len(
        [
            x
            for x in project.get("logs", [])
            if x.get("priority") == "高"
            and x.get("status") in ["未対応", "対応中"]
        ]
    )


def parse_date_safe(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%d").date()
    except Exception:
        return None


def build_google_calendar_url(project, log):
    """やり取り履歴の内容からGoogleカレンダー登録用URLを作成する。

    無料・APIキー不要の方式。
    ブラウザでGoogleカレンダーの予定作成画面を開く。
    """
    project_name = project.get("name", "")
    person = log.get("person", "")
    due_text = log.get("due_date", "") or log.get("date", "")
    target_date = parse_date_safe(due_text) or date.today()
    next_day = date.fromordinal(target_date.toordinal() + 1)

    title = f"{project_name}｜{person}｜{log.get('status', '')}".strip("｜")
    if not title:
        title = "物件対応予定"

    details_lines = [
        f"物件名：{project_name}",
        f"相手先・担当：{project.get('client', '')}",
        f"やり取り相手：{person}",
        f"状態：{log.get('status', '')}",
        f"重要度：{log.get('priority', '')}",
        f"期限：{log.get('due_date', '')}",
        "",
        "【内容】",
        str(log.get("content", "")),
    ]

    attachment_path = log.get("attachment_path", "")
    if attachment_path:
        details_lines.extend(["", f"添付：{attachment_path}"])

    folder_path = project.get("folder_path", "")
    if folder_path:
        details_lines.extend(["", f"物件フォルダ：{folder_path}"])

    details = "\n".join(details_lines)

    # 終日予定として登録する。Googleカレンダーの終日予定は終了日を翌日にする。
    dates = f"{target_date.strftime('%Y%m%d')}/{next_day.strftime('%Y%m%d')}"

    params = {
        "action": "TEMPLATE",
        "text": title,
        "details": details,
        "dates": dates,
    }

    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def due_style(log):
    due = parse_date_safe(log.get("due_date", ""))
    today = date.today()
    priority = log.get("priority", "中")

    if log.get("status") == "対応済":
        return "#ffffff", "#dddddd", ""

    if due and due < today:
        return "#ffe5e5", "#ff3333", "期限超過"

    if due and due == today:
        return "#fff0e0", "#ff8800", "本日期限"

    if due and 0 < (due - today).days <= 3:
        return "#eaf3ff", "#4d94ff", "3日以内"

    if priority == "高":
        return "#eaf3ff", "#4d94ff", "重要度高"

    return "#ffffff", "#dddddd", ""


def get_today_tasks(data):
    rows = []
    today = date.today()

    for project in data.get("projects", []):
        for log in project.get("logs", []):
            if log.get("status") not in ["未対応", "対応中"]:
                continue

            due = parse_date_safe(log.get("due_date", ""))
            is_target = False

            if due and due <= today:
                is_target = True

            if log.get("priority") == "高":
                is_target = True

            if is_target:
                row = dict(log)
                row["project_id"] = project["id"]
                row["project_name"] = project.get("name", "")
                rows.append(row)

    return sorted(rows, key=lambda x: (x.get("due_date", ""), x.get("priority", "")))




def get_schedule_logs(data):
    rows = []

    for project in data.get("projects", []):
        for log in project.get("logs", []):
            if log.get("priority") != "スケジュール":
                continue

            row = dict(log)
            row["project_name"] = project.get("name", "")
            rows.append(row)

    def sort_key(row):
        due = parse_date_safe(row.get("due_date", ""))
        log_date = parse_date_safe(row.get("date", ""))
        due_missing = due is None
        return (
            due_missing,
            due or date.max,
            log_date or date.max,
        )

    return sorted(rows, key=sort_key)


def render_schedule_card(log):
    due_text = log.get("due_date", "") or "（未設定）"
    st.markdown(
        f"""
        <div style="
            border:1px solid #cfd8e3;
            border-left:6px solid #4d94ff;
            background:#ffffff;
            border-radius:10px;
            padding:12px;
            margin-bottom:10px;
            color:#111111;
            line-height:1.6;
            word-break:break-word;
        ">
            <div style="font-weight:700; font-size:1.05rem; margin-bottom:4px;">{html.escape(str(log.get('project_name', '')))}</div>
            <div><b>日付:</b> {html.escape(str(log.get('date', '')))}</div>
            <div><b>期限:</b> {html.escape(str(due_text))}</div>
            <div><b>状態:</b> {html.escape(str(log.get('status', '')))}</div>
            <div style="margin-top:6px;"><b>内容・メモ:</b><br>{html.escape(str(log.get('content', ''))).replace(chr(10), '<br>')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def simple_summary(text):
    text = text.replace("\r", "\n")
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    picked = []

    keywords = [
        "未対応",
        "確認",
        "依頼",
        "期限",
        "至急",
        "修正",
        "回答",
        "提出",
        "申請",
        "杭",
        "基礎",
        "設備",
        "意匠",
    ]

    for line in lines:
        if any(k in line for k in keywords):
            picked.append(line)

    if not picked:
        picked = lines[:10]

    picked = picked[:15]

    result = "【簡易要約】\n"
    result += "※無料版の簡易要約です。必要な行を自動抽出しています。\n\n"

    for i, line in enumerate(picked, start=1):
        result += f"{i}. {line}\n"

    return result


def read_uploaded_text(uploaded_file):
    if uploaded_file is None:
        return ""

    name = uploaded_file.name.lower()
    data_bytes = uploaded_file.read()

    if name.endswith(".txt"):
        for enc in ["utf-8", "cp932", "shift_jis"]:
            try:
                return data_bytes.decode(enc)
            except Exception:
                pass
        return ""

    if name.endswith(".pdf"):
        try:
            import pypdf
            import io

            reader = pypdf.PdfReader(io.BytesIO(data_bytes))
            texts = []

            for page in reader.pages:
                texts.append(page.extract_text() or "")

            return "\n".join(texts)

        except Exception:
            return "PDF本文の抽出に失敗しました。pypdf が未導入の場合は、PowerShellで pip install pypdf を実行してください。"

    return "この形式はまだ本文抽出に対応していません。txt または PDF で試してください。"


def card_html(log, bg_color, border_color, due_label):
    text_date = html.escape(str(log.get("date", "")))
    text_project = html.escape(str(log.get("project_name", "")))
    text_status = html.escape(str(log.get("status", "")))
    text_due = html.escape(str(log.get("due_date", "")))
    text_person = html.escape(str(log.get("person", "")))
    text_priority = html.escape(str(log.get("priority", "")))
    text_content = html.escape(str(log.get("content", ""))).replace("\n", "<br>")
    text_due_label = html.escape(str(due_label))

    if text_due_label:
        label_html = (
            f'<span style="display:inline-block; background:{border_color}; '
            f'color:white; padding:2px 8px; border-radius:8px; '
            f'font-size:12px; margin-left:8px;">{text_due_label}</span>'
        )
    else:
        label_html = ""

    return (
        f'<div style="'
        f'background-color:{bg_color}; '
        f'border:1px solid {border_color}; '
        f'border-left:8px solid {border_color}; '
        f'padding:12px 14px; '
        f'border-radius:10px; '
        f'margin-bottom:8px; '
        f'line-height:1.7; '
        f'width:100%; '
        f'box-sizing:border-box;">'
        f'<b>{text_project}</b> ｜ <b>{text_date}</b>　'
        f'状態：{text_status}　'
        f'期限：{text_due} '
        f'{label_html}　'
        f'相手先：{text_person}　'
        f'重要度：<b>{text_priority}</b>'
        f'<br>'
        f'{text_content}'
        f'</div>'
    )


st.set_page_config(page_title=APP_TITLE, layout="wide")

st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        font-size: 18px !important;
    }

    .stApp {
        background-color: #ffffff !important;
        color: #111111 !important;
    }

    .stMarkdown, .stText, .stTextInput, .stTextArea, .stSelectbox, .stDateInput, .stButton, .stDownloadButton {
        color: #111111 !important;
    }

    label, p, span, div {
        color: #111111 !important;
    }

    input, textarea, select, option {
        font-size: 18px !important;
        color: #111111 !important;
        background-color: #ffffff !important;
        -webkit-text-fill-color: #111111 !important;
    }

    button {
        font-size: 18px !important;
        min-height: 44px !important;
        color: #111111 !important;
    }

    .stButton button, .stDownloadButton button, button[kind="secondary"] {
        background-color: #f5f5f5 !important;
        color: #111111 !important;
        border: 1px solid #bdbdbd !important;
        width: 100% !important;
        white-space: normal !important;
        word-break: break-word !important;
        line-height: 1.4 !important;
    }

    /* Streamlit全体の主要ボタンに、物理ボタンのような押下感を付与 */
    .stButton button,
    .stDownloadButton button,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stLinkButton"] a,
    button[kind="primary"],
    button[kind="secondary"],
    button[data-testid^="baseButton"],
    a[data-testid^="baseLinkButton"] {
        transform: translateY(0) scale(1) !important;
        transform-origin: center center !important;
        transition: transform 0.09s ease-out, box-shadow 0.09s ease-out, background-color 0.09s ease-out, filter 0.09s ease-out, border-color 0.09s ease-out !important;
        box-shadow: 0 3px 0 rgba(0, 0, 0, 0.18), 0 4px 10px rgba(0, 0, 0, 0.10) !important;
        cursor: pointer !important;
        touch-action: manipulation !important;
        -webkit-tap-highlight-color: transparent !important;
        will-change: transform, box-shadow, background-color, filter !important;
    }

    .stButton button:active:not(:disabled),
    .stDownloadButton button:active:not(:disabled),
    [data-testid="stFormSubmitButton"] button:active:not(:disabled),
    [data-testid="stLinkButton"] a:active,
    button[kind="primary"]:active:not(:disabled),
    button[kind="secondary"]:active:not(:disabled),
    button[data-testid^="baseButton"]:active:not(:disabled),
    a[data-testid^="baseLinkButton"]:active {
        transform: translateY(3px) scale(0.97) !important;
        box-shadow: none !important;
        filter: brightness(0.92) !important;
        background-color: #e0e0e0 !important;
        border-color: #9e9e9e !important;
    }

    .stButton button[kind="primary"],
    .stButton button[data-testid="baseButton-primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"],
    button[kind="primary"],
    button[data-testid="baseButton-primary"] {
        box-shadow: 0 3px 0 rgba(120, 24, 24, 0.28), 0 4px 10px rgba(0, 0, 0, 0.12) !important;
    }

    .stButton button[kind="primary"]:active:not(:disabled),
    .stButton button[data-testid="baseButton-primary"]:active:not(:disabled),
    [data-testid="stFormSubmitButton"] button[kind="primary"]:active:not(:disabled),
    button[kind="primary"]:active:not(:disabled),
    button[data-testid="baseButton-primary"]:active:not(:disabled) {
        background-color: #d93f3f !important;
        border-color: #c73636 !important;
    }

    .stButton button:disabled,
    .stDownloadButton button:disabled,
    [data-testid="stFormSubmitButton"] button:disabled,
    button[data-testid^="baseButton"]:disabled {
        transform: none !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
        will-change: auto !important;
    }

    [data-testid="stSidebar"] {
        min-width: 340px !important;
    }

    .mobile-toggle-bar {
        display: none;
    }

    /* iPad・スマホのサイドバー文字色対策 */
    [data-testid="stSidebar"] {
        background-color: #262730 !important;
    }

    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label {
        color: #f5f5f5 !important;
    }

    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea {
        color: #111111 !important;
        background-color: #ffffff !important;
    }

    [data-testid="stSidebar"] button,
    [data-testid="stSidebar"] button *,
    [data-testid="stSidebar"] [role="button"],
    [data-testid="stSidebar"] [role="button"] * {
        color: #111111 !important;
        background-color: #ffffff !important;
    }

    [data-testid="stSidebar"] small {
        color: #dddddd !important;
    }

    /* =========================
       iPad Safari フォーム強制ライト化
       ========================= */

    /* input */
    input,
    textarea,
    select,
    option {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    input[type="date"],
    input[type="text"],
    input[type="file"],
    textarea,
    select {
        color: #111111 !important;
        background-color: #ffffff !important;
        -webkit-text-fill-color: #111111 !important;
        color-scheme: light !important;
    }

    select option {
        color: #111111 !important;
        background-color: #ffffff !important;
    }

    div[data-baseweb="select"] *,
    div[data-baseweb="input"] *,
    div[data-baseweb="textarea"] * {
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    .stDateInput input,
    .stTextInput input,
    .stTextArea textarea,
    .stSelectbox div,
    .stFileUploader,
    .stFileUploader * {
        color: #111111 !important;
        background-color: #ffffff !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* Streamlit text input */
    [data-baseweb="input"] input {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* selectbox */
    div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    div[data-baseweb="select"] span {
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* date input */
    input[type="date"] {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* Streamlit date_input calendar popup 強制ライト化 */
    [data-baseweb="calendar"],
    [data-baseweb="calendar"] *,
    [data-baseweb="datepicker"],
    [data-baseweb="datepicker"] *,
    [data-baseweb="popover"],
    [data-baseweb="popover"] * {
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    [data-baseweb="calendar"],
    [data-baseweb="datepicker"],
    [data-baseweb="popover"],
    [data-baseweb="popover"] > div {
        background-color: #ffffff !important;
    }

    [data-baseweb="calendar"] div,
    [data-baseweb="calendar"] button,
    [data-baseweb="calendar"] span {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* 選択中の日付だけは見やすく */
    [data-baseweb="calendar"] button[aria-selected="true"],
    [data-baseweb="calendar"] [aria-selected="true"] {
        background-color: #ff4b4b !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }

    /* 月・年・曜日 */
    [data-baseweb="calendar"] [role="heading"],
    [data-baseweb="calendar"] [role="gridcell"],
    [data-baseweb="calendar"] [role="columnheader"] {
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* dropdown item */
    li[role="option"],
    div[role="option"] {
        background-color: #ffffff !important;
        color: #111111 !important;
        -webkit-text-fill-color: #111111 !important;
    }

    /* hover */
    li[role="option"]:hover,
    div[role="option"]:hover {
        background-color: #e6f0ff !important;
        color: #111111 !important;
    }

    /* selected */
    [aria-selected="true"] {
        background-color: #dbeafe !important;
        color: #111111 !important;
    }

    /* iOS Safari auto dark mode 防止 */
    html {
        color-scheme: light !important;
    }

    /* placeholder */
    ::placeholder {
        color: #666666 !important;
    }

    /* button */
    button {
        color: #111111 !important;
    }

    /* Googleカレンダー登録リンクをiPad/Safariでも読みやすいライト配色に固定 */
    [data-testid="stLinkButton"] a[href*="calendar.google.com"],
    a[href*="calendar.google.com"][role="button"],
    a[href*="calendar.google.com"][data-testid="baseLinkButton-secondary"] {
        background-color: #e5e7eb !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border: 1px solid #d1d5db !important;
        box-shadow: 0 3px 0 rgba(0, 0, 0, 0.16), 0 4px 10px rgba(0, 0, 0, 0.10) !important;
        color-scheme: light !important;
    }

    [data-testid="stLinkButton"] a[href*="calendar.google.com"] *,
    a[href*="calendar.google.com"][role="button"] *,
    a[href*="calendar.google.com"][data-testid="baseLinkButton-secondary"] * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        fill: #111827 !important;
        stroke: #111827 !important;
    }

    [data-testid="stLinkButton"] a[href*="calendar.google.com"]:hover,
    [data-testid="stLinkButton"] a[href*="calendar.google.com"]:focus-visible,
    a[href*="calendar.google.com"][role="button"]:hover,
    a[href*="calendar.google.com"][role="button"]:focus-visible,
    a[href*="calendar.google.com"][data-testid="baseLinkButton-secondary"]:hover,
    a[href*="calendar.google.com"][data-testid="baseLinkButton-secondary"]:focus-visible {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border-color: #d1d5db !important;
    }

    [data-testid="stLinkButton"] a[href*="calendar.google.com"]:active,
    a[href*="calendar.google.com"][role="button"]:active,
    a[href*="calendar.google.com"][data-testid="baseLinkButton-secondary"]:active {
        transform: translateY(3px) scale(0.97) !important;
        box-shadow: none !important;
        filter: brightness(0.92) !important;
        background-color: #d1d5db !important;
        border-color: #9ca3af !important;
    }

    /* =========================
       音声メモ: 録音ウィジェット全体をライト配色に固定
       ========================= */
    [data-testid="stAudioInput"] {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        border: 1px solid #d1d5db !important;
        border-radius: 12px !important;
        padding: 12px !important;
        color-scheme: light !important;
    }

    [data-testid="stAudioInput"] *,
    [data-testid="stAudioInput"] label,
    [data-testid="stAudioInput"] p,
    [data-testid="stAudioInput"] span,
    [data-testid="stAudioInput"] div {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    [data-testid="stAudioInput"] svg,
    [data-testid="stAudioInput"] svg * {
        color: #111827 !important;
        fill: currentColor !important;
        stroke: currentColor !important;
    }

    [data-testid="stAudioInput"] audio,
    [data-testid="stAudioInput"] [data-testid="stAudioInputFile"],
    [data-testid="stAudioInput"] [data-testid="stAudioInputDropzone"] {
        background-color: #e5e7eb !important;
        color: #111827 !important;
        border-color: #d1d5db !important;
        color-scheme: light !important;
    }

    /* =========================
       音声メモ: マイクボタンのSafari強制スタイル
       ========================= */
    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"] {
        width: 48px !important;
        min-width: 48px !important;
        height: 48px !important;
        min-height: 48px !important;
        padding: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 50% !important;
        border: 1px solid #CCCCCC !important;
        box-shadow: 0 3px 0 rgba(0, 0, 0, 0.16), 0 4px 10px rgba(0, 0, 0, 0.10) !important;
        transform: translateY(0) scale(1) !important;
        transition: transform 0.09s ease-out, box-shadow 0.09s ease-out, background-color 0.09s ease-out, filter 0.09s ease-out, border-color 0.09s ease-out !important;
        touch-action: manipulation !important;
        appearance: none !important;
        -webkit-appearance: none !important;
        -webkit-tap-highlight-color: transparent !important;
        color-scheme: light !important;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"]:active:not(:disabled) {
        transform: translateY(3px) scale(0.96) !important;
        box-shadow: none !important;
        filter: brightness(0.90) !important;
        animation: none !important;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"] svg,
    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"] svg * {
        color: inherit !important;
        fill: currentColor !important;
        stroke: currentColor !important;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Record"] {
        background: #E5E5E5 !important;
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Record"]:hover,
    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Record"]:focus-visible {
        background: #D6D6D6 !important;
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Stop recording"] {
        background: #FF4D4F !important;
        border-color: #FF4D4F !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        animation: voice-recording-pulse 1.2s ease-in-out infinite;
    }

    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Stop recording"]:hover,
    [data-testid="stAudioInput"] [data-testid="stAudioInputActionButton"][aria-label="Stop recording"]:focus-visible {
        background: #E03133 !important;
        border-color: #E03133 !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }

    [data-testid="stAudioInput"]:has([data-testid="stAudioInputActionButton"][aria-label="Stop recording"])::after {
        content: "🔴 録音を開始しました / 録音中...";
        display: inline-flex;
        align-items: center;
        margin-top: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        background: #FFF1F0;
        color: #CF1322 !important;
        -webkit-text-fill-color: #CF1322 !important;
        border: 1px solid #FFA39E;
        font-weight: 700;
        line-height: 1.2;
    }

    [data-testid="stAudioInput"]:has([data-testid="stAudioInputActionButton"][aria-label="Stop recording"]) [data-testid="stAudioInputWaveformTimeCode"] {
        color: #CF1322 !important;
        -webkit-text-fill-color: #CF1322 !important;
        font-weight: 700 !important;
    }

    @keyframes voice-recording-pulse {
        0%, 100% {
            box-shadow: 0 0 0 0 rgba(255, 77, 79, 0.45);
        }
        50% {
            box-shadow: 0 0 0 8px rgba(255, 77, 79, 0);
        }
    }

    /* Streamlit popover */
    [data-baseweb="popover"] {
        background-color: #ffffff !important;
        color: #111111 !important;
    }


    /* toast / status messages: force readable light colors on iPhone, iPad, and PC */
    [data-testid="stToast"],
    [data-testid="stToast"] *,
    [data-testid="stAlert"],
    [data-testid="stAlert"] * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    [data-testid="stToast"],
    [data-testid="stToast"] > div,
    [data-testid="stAlert"] {
        background-color: #ffffff !important;
        border-color: #d1d5db !important;
        color-scheme: light !important;
    }

    [data-testid="stSpinner"],
    [data-testid="stSpinner"] * {
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
    }

    @media screen and (max-width: 1024px) {
        [data-testid="stSidebar"] {
            min-width: 320px !important;
        }

        .stButton button, .stDownloadButton button, button[kind="secondary"] {
            background-color: #f5f5f5 !important;
            color: #111111 !important;
            border: 1px solid #9e9e9e !important;
            font-size: 16px !important;
            min-height: 46px !important;
        }
    }

    @media screen and (max-width: 768px) {
        html, body, [class*="css"] {
            font-size: 20px !important;
        }

        .block-container {
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
            padding-top: 1rem !important;
        }

        input, textarea, button {
            font-size: 20px !important;
        }

        .stButton button, .stDownloadButton button {
            width: 100% !important;
            min-height: 48px !important;
        }

        .mobile-toggle-bar {
            display: block !important;
            margin-bottom: 0.6rem !important;
        }

        [data-testid="stSidebar"] {
            display: none !important;
        }

        [data-testid="stSidebarNav"] {
            display: none !important;
        }

        .mobile-toggle-bar button {
            min-height: 50px !important;
        }

        .mobile-panel {
            padding-top: 0.3rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

calendar_url = "https://calendar.google.com/"

st.title("📁 物件管理アプリ")

if "project_keyword_search" not in st.session_state:
    st.session_state["project_keyword_search"] = ""

header_col1, header_col2, header_col3 = st.columns([1, 1, 2])
with header_col1:
    if st.button("📅 カレンダー", key="show_google_calendar_link", use_container_width=True):
        notify_action_start("カレンダーを開く準備をしています")
        st.session_state["show_google_calendar_link"] = True
        st.toast("カレンダーを開くリンクを表示しました")
    if st.session_state.get("show_google_calendar_link"):
        st.link_button("Googleカレンダーを開く", calendar_url, use_container_width=True)
with header_col2:
    if st.button("📅 スケジュール", key="show_schedule_list", use_container_width=True):
        notify_action_start("スケジュール一覧を表示します")
        st.session_state["page_mode"] = "schedule"
        queue_feedback("success", "スケジュール一覧を表示しました")
        rerun_app()
with header_col3:
    st.text_input(
        "キーワード検索",
        key="project_keyword_search",
        placeholder="物件名・メモ・やり取り・状態・重要度・期限から検索",
        help="空白区切りで複数キーワードを入力すると、すべてを含む物件だけを表示します。",
    )


if "selected_project_id" not in st.session_state:
    st.session_state["selected_project_id"] = None

if "selected_property_id" not in st.session_state:
    st.session_state["selected_property_id"] = st.session_state.get("selected_project_id")

if "folder_path_temp" not in st.session_state:
    st.session_state["folder_path_temp"] = ""

if "pdf_path_temp" not in st.session_state:
    st.session_state["pdf_path_temp"] = ""

if "new_attachment_path" not in st.session_state:
    st.session_state["new_attachment_path"] = ""

if "editing_log_id" not in st.session_state:
    st.session_state["editing_log_id"] = None

if "show_structural_memo_editor" not in st.session_state:
    st.session_state["show_structural_memo_editor"] = False

if "filter_mode" not in st.session_state:
    st.session_state["filter_mode"] = "すべて"

if "page_mode" not in st.session_state:
    st.session_state["page_mode"] = "main"

if "current_view" not in st.session_state:
    st.session_state["current_view"] = "list"

if "data" not in st.session_state:
    st.session_state["data"] = load_initial_data()

data = st.session_state["data"]
if st.session_state.pop("_auto_loaded_local_data", False):
    st.caption("前回保存データを自動読み込みしました")
show_queued_feedback()

keyword_search_query = st.session_state.get("project_keyword_search", "")
if data.get("projects"):
    keyword_result_count = len(filter_projects_by_keyword(data["projects"], keyword_search_query))
    st.caption(f"検索結果：{keyword_result_count}件")


def render_project_management_panel(panel_prefix="sidebar"):
    # 上部：日常利用の中心（一覧・フィルタ・選択）
    st.header("📌 物件一覧")

    if data["projects"]:
        st.caption("表示フィルタ")
        radio_key = "filter_mode" if panel_prefix == "sidebar" else f"{panel_prefix}_filter_mode"
        default_index = ["すべて", "未対応あり", "重要度高あり"].index(st.session_state.get("filter_mode", "すべて"))
        filter_mode = st.radio("表示", ["すべて", "未対応あり", "重要度高あり"], index=default_index, key=radio_key)
        save_app_state()

        keyword_query = st.session_state.get("project_keyword_search", "")
        keyword_matched_projects = filter_projects_by_keyword(data["projects"], keyword_query)
        visible_projects = []
        for p in keyword_matched_projects:
            open_count = count_open_logs(p)
            high_count = count_high_logs(p)

            if filter_mode == "未対応あり" and open_count == 0:
                continue

            if filter_mode == "重要度高あり" and high_count == 0:
                continue

            visible_projects.append(p)

        st.caption(f"検索結果：{len(visible_projects)}件")
        st.caption("物件選択一覧")

        if not visible_projects:
            st.info("検索条件に一致する物件はありません。検索欄を空にすると全件表示に戻ります。")

        for p in visible_projects:
            open_count = count_open_logs(p)
            high_count = count_high_logs(p)
            label = f"{p.get('name', '')}｜未{open_count}｜高{high_count}"

            if st.button(label, key=f"{panel_prefix}_select_{p['id']}", use_container_width=True):
                notify_action_start("物件を選択しています")
                st.session_state["selected_project_id"] = p["id"]
                st.session_state["selected_property_id"] = p["id"]
                st.session_state["current_view"] = "detail"
                st.session_state["mobile_view"] = "detail"
                save_app_state()
                queue_feedback("success", "物件を選択しました")
                rerun_app()

    else:
        st.info("物件がありません。")

    st.divider()

    # 中段：日常的によく使う編集系
    st.header("➕ 新規物件登録")

    st.write("物件フォルダ")
    st.session_state["folder_path_temp"] = st.text_input(
        "新規物件フォルダパス",
        value=st.session_state["folder_path_temp"],
        key=f"{panel_prefix}_new_folder_path",
        label_visibility="collapsed",
    )

    st.write("工程表PDF")
    st.session_state["pdf_path_temp"] = st.text_input(
        "新規工程表PDFパス",
        value=st.session_state["pdf_path_temp"],
        key=f"{panel_prefix}_new_pdf_path",
        label_visibility="collapsed",
    )

    with st.form(f"{panel_prefix}_add_project_form"):
        name = st.text_input("物件名", key=f"{panel_prefix}_project_name")
        client = st.text_input("相手先・担当", key=f"{panel_prefix}_project_client")
        submitted = st.form_submit_button("物件を追加")

        if submitted:
            notify_action_start("物件追加を開始しました")
            if not name.strip():
                st.error("物件追加に失敗しました。物件名を入力してください。")
            else:
                try:
                    with st.spinner("物件を追加中です..."):
                        new_project = {
                            "id": str(uuid.uuid4()),
                            "name": name.strip(),
                            "client": client.strip(),
                            "folder_path": st.session_state["folder_path_temp"].strip(),
                            "schedule_pdf_path": st.session_state["pdf_path_temp"].strip(),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "logs": [],
                        }
                        data["projects"].append(new_project)
                        persist_data(data)

                        st.session_state["selected_project_id"] = new_project["id"]
                        st.session_state["selected_property_id"] = new_project["id"]
                        st.session_state["current_view"] = "detail"
                        st.session_state["mobile_view"] = "detail"
                        st.session_state["folder_path_temp"] = ""
                        st.session_state["pdf_path_temp"] = ""

                    queue_feedback("success", "物件を追加しました。")
                    rerun_app()
                except Exception:
                    st.error("物件追加に失敗しました。もう一度確認してください。")

    st.divider()

    # 最下部：読込・保存関連
    st.header("📂 読込・保存")
    st.info(
        "このアプリはサーバー内部にはデータを保存しません。\n\n"
        "編集後は必ず「最新JSONをダウンロード」を実行し、\n"
        "OneDrive または iCloud Drive に保存してください。\n\n"
        "iPhone・iPad・Windows PCで同じデータを使用する場合は、"
        "同じJSONファイルを読み込んでください。"
    )
    with st.expander("📱 アプリ共有QRコード", expanded=True):
        st.image(build_app_qr_code_bytes(), caption="物件管理アプリを開くQRコード", width=240)
        st.markdown(f"[アプリを開く]({APP_PUBLIC_URL})")

    if st.button("➕ 新規データ作成", key=f"{panel_prefix}_new_data", use_container_width=True):
        notify_action_start("新規データ作成を開始しました")
        st.session_state["data"] = {"projects": []}
        st.session_state["selected_project_id"] = None
        st.session_state["selected_property_id"] = None
        st.session_state["current_view"] = "list"
        st.session_state["mobile_view"] = "list"
        persist_data(st.session_state["data"])
        queue_feedback("success", "新規データを作成しました。")
        rerun_app()

    uploaded_json = st.file_uploader(
        "Upload",
        type=["json"],
        accept_multiple_files=False,
        help="bukken_data.json を選択してください。",
    )
    if st.button("JSON読込", key=f"{panel_prefix}_json_load", use_container_width=True):
        notify_action_start("JSON読み込みを開始しました")
        if uploaded_json is None:
            st.error("JSONの読み込みに失敗しました。先にJSONファイルを選択してください。")
        else:
            try:
                with st.spinner("JSONを読み込み中です..."):
                    raw_json = uploaded_json.getvalue()
                    try:
                        uploaded_data = json.loads(raw_json.decode("utf-8"))
                    except UnicodeDecodeError:
                        uploaded_data = json.loads(raw_json.decode("utf-8-sig"))

                    st.session_state["data"] = normalize_data(uploaded_data)
                    if st.session_state["data"]["projects"]:
                        first_project_id = st.session_state["data"]["projects"][0]["id"]
                        st.session_state["selected_project_id"] = first_project_id
                        st.session_state["selected_property_id"] = first_project_id
                        st.session_state["current_view"] = "detail"
                    else:
                        st.session_state["selected_project_id"] = None
                        st.session_state["selected_property_id"] = None
                        st.session_state["current_view"] = "list"

                    # 読込直後にアプリ内保存済みJSONとして即時登録
                    persist_data(st.session_state["data"])

                queue_feedback("success", "JSONを読み込みました。")
                rerun_app()
            except Exception:
                st.error("JSONの読み込みに失敗しました。形式を確認してください。")

    st.download_button(
        "最新JSONをダウンロード",
        data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="bukken_data.json",
        mime="application/json",
        use_container_width=True,
        key=f"{panel_prefix}_json_save",
        on_click=notify_json_download_complete,
    )
    if st.session_state.get("json_download_notice", False):
        st.success(
            "✅ ダウンロード完了\n\n"
            "OneDrive または iCloud Drive に保存してください。\n\n"
            "保存した JSON を次回読み込むことで、"
            "iPhone・iPad・PC 間で同じデータを利用できます。"
        )


def render_project_list_view():
    """メイン領域に表示する物件一覧。既存の検索・表示フィルタ条件を使う。"""
    st.header("📌 物件一覧")
    st.caption("左側の一覧と同じ検索条件・表示フィルタで絞り込まれています。物件ボタンを押すと詳細画面を開きます。")

    keyword_query = st.session_state.get("project_keyword_search", "")
    filter_mode = normalize_filter_mode(st.session_state.get("filter_mode", "すべて"))
    visible_projects = []
    for p in filter_projects_by_keyword(data["projects"], keyword_query):
        open_count = count_open_logs(p)
        high_count = count_high_logs(p)
        if filter_mode == "未対応あり" and open_count == 0:
            continue
        if filter_mode == "重要度高あり" and high_count == 0:
            continue
        visible_projects.append(p)

    st.caption(f"表示フィルタ：{filter_mode} / 検索結果：{len(visible_projects)}件")
    if not visible_projects:
        st.info("検索条件に一致する物件はありません。検索欄を空にするか、表示フィルタを変更してください。")
        return

    for p in visible_projects:
        open_count = count_open_logs(p)
        high_count = count_high_logs(p)
        label = f"{p.get('name', '')}｜未{open_count}｜高{high_count}"
        if st.button(label, key=f"main_list_select_{p['id']}", use_container_width=True):
            notify_action_start("物件を選択しています")
            st.session_state["selected_project_id"] = p["id"]
            st.session_state["selected_property_id"] = p["id"]
            st.session_state["current_view"] = "detail"
            st.session_state["mobile_view"] = "detail"
            save_app_state()
            queue_feedback("success", "物件詳細を表示しました")
            rerun_app()


with st.sidebar:
    render_project_management_panel("sidebar")

if "mobile_view" not in st.session_state:
    st.session_state["mobile_view"] = "detail"

st.markdown('<div class="mobile-toggle-bar">', unsafe_allow_html=True)
mv1, mv2 = st.columns(2)
with mv1:
    if st.button("物件一覧", key="mobile_show_list", use_container_width=True):
        notify_action_start("物件一覧を表示します")
        st.session_state["mobile_view"] = "list"
        st.session_state["current_view"] = "list"
        queue_feedback("success", "物件一覧を表示しました")
        rerun_app()
with mv2:
    if st.button("物件詳細", key="mobile_show_detail", use_container_width=True):
        notify_action_start("物件詳細を表示します")
        st.session_state["mobile_view"] = "detail"
        if st.session_state.get("selected_project_id") is None and data.get("projects"):
            first_project_id = data["projects"][0]["id"]
            st.session_state["selected_project_id"] = first_project_id
            st.session_state["selected_property_id"] = first_project_id
        st.session_state["current_view"] = "detail"
        queue_feedback("success", "物件詳細を表示しました")
        rerun_app()
st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.get("mobile_view") == "list":
    st.markdown('<div class="mobile-panel">', unsafe_allow_html=True)
    render_project_management_panel("mobile")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

if st.session_state.get("page_mode") == "schedule":
    st.subheader("📅 スケジュール一覧（全物件）")
    schedule_logs = get_schedule_logs(data)

    if st.button("← 物件詳細に戻る", key="back_to_main_from_schedule"):
        notify_action_start("物件詳細に戻ります")
        st.session_state["page_mode"] = "main"
        st.session_state["current_view"] = "detail"
        queue_feedback("success", "物件詳細を表示しました")
        rerun_app()

    if not schedule_logs:
        st.info("重要度が『スケジュール』のデータはありません。")
    else:
        st.caption("表示順：期限が近い順（期限未設定は最後）→ 日付が古い順")
        for row in schedule_logs:
            render_schedule_card(row)
    st.stop()


if not data["projects"]:
    st.info("左側から物件を登録してください。")
    st.stop()


if st.session_state.get("current_view", "list") != "detail":
    render_project_list_view()
    st.stop()


selected_project_id = st.session_state.get("selected_property_id") or st.session_state.get("selected_project_id")
if selected_project_id is None:
    selected_project_id = data["projects"][0]["id"]
    st.session_state["selected_project_id"] = selected_project_id
    st.session_state["selected_property_id"] = selected_project_id
    save_app_state()
else:
    st.session_state["selected_project_id"] = selected_project_id
    st.session_state["selected_property_id"] = selected_project_id


project = get_project(data, selected_project_id)

if project is None:
    st.warning("選択された物件が見つかりません。")
    if st.button("← 物件一覧へ戻る", key="back_to_list_from_missing_project"):
        notify_action_start("物件一覧に戻ります")
        st.session_state["current_view"] = "list"
        st.session_state["selected_project_id"] = None
        st.session_state["selected_property_id"] = None
        save_app_state()
        queue_feedback("success", "物件一覧を表示しました")
        rerun_app()
    st.stop()


if st.button("← 物件一覧へ戻る", key=f"back_to_list_from_detail_{project['id']}"):
    notify_action_start("物件一覧に戻ります")
    st.session_state["current_view"] = "list"
    st.session_state["selected_project_id"] = None
    st.session_state["selected_property_id"] = None
    save_app_state()
    queue_feedback("success", "物件一覧を表示しました")
    rerun_app()


current_folder_key = f"current_folder_{project['id']}"
current_pdf_key = f"current_pdf_{project['id']}"

if current_folder_key not in st.session_state:
    st.session_state[current_folder_key] = project.get("folder_path", "")

if current_pdf_key not in st.session_state:
    st.session_state[current_pdf_key] = project.get("schedule_pdf_path", "")


st.subheader("🔥 今日やること一覧")

today_tasks = get_today_tasks(data)

if not today_tasks:
    st.success("本日期限・期限超過・重要度高の未対応項目はありません。")
else:
    for row in today_tasks:
        bg_color, border_color, label = due_style(row)
        st.markdown(card_html(row, bg_color, border_color, label), unsafe_allow_html=True)

st.divider()

col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

with col1:
    st.subheader(f"🏢 {project['name']}")
    st.write(f"相手先・担当：{project.get('client', '')}")
    st.write(f"登録日：{project.get('created_at', '')}")
    st.write(
        f"未対応・対応中：{count_open_logs(project)} 件　｜　重要度高：{count_high_logs(project)} 件"
    )

with col2:
    st.write("")
    st.write("")
    if st.button("📄 工程表PDFを開く", key=f"open_schedule_pdf_{project['id']}"):
        notify_action_start("工程表PDFを開いています")
        with st.spinner("工程表PDFを確認中です..."):
            open_path(project.get("schedule_pdf_path", ""))
        st.toast("工程表PDFを開く処理が完了しました")

with col3:
    st.write("")
    st.write("")
    if st.button("📂 物件フォルダを開く", key=f"open_project_folder_{project['id']}"):
        notify_action_start("物件フォルダを開いています")
        with st.spinner("物件フォルダを確認中です..."):
            open_path(project.get("folder_path", ""))
        st.toast("物件フォルダを開く処理が完了しました")

with col4:
    st.write("")
    st.write("")
    memo_text_for_download = build_structural_memo_text(project)
    safe_project_name = sanitize_windows_filename(project.get("name", "project"))
    st.download_button(
        "📄 履歴txt出力",
        data=memo_text_for_download.encode("utf-8-sig"),
        file_name=f"{safe_project_name}_やり取り履歴.txt",
        mime="text/plain",
        key=f"download_history_text_{project['id']}",
        use_container_width=True,
        on_click=notify_download_start,
        args=("履歴txt出力を開始しました",),
    )

    history_pdf_bytes = build_structural_memo_pdf(project)
    st.download_button(
        "📄 履歴PDF出力",
        data=history_pdf_bytes,
        file_name=f"{safe_project_name}_やり取り履歴.pdf",
        mime="application/pdf",
        key=f"download_history_pdf_{project['id']}",
        use_container_width=True,
        on_click=notify_download_start,
        args=("履歴PDF出力を開始しました",),
    )

    if st.button("📝 構造設計メモ", key=f"open_structural_memo_{project['id']}", use_container_width=True):
        notify_action_start("構造設計メモの表示を切り替えます")
        st.session_state["show_structural_memo_editor"] = not st.session_state["show_structural_memo_editor"]
        st.toast("構造設計メモの表示を切り替えました")


if st.session_state["show_structural_memo_editor"]:
    st.markdown("### 📝 構造設計メモ")
    st.caption("A4印刷向けのメモ欄です。ここに構造設計上の確認事項、計算メモ、図面修正方針などを自由に記入できます。")

    memo_key = f"structural_memo_text_{project['id']}"
    if memo_key not in st.session_state:
        st.session_state[memo_key] = project.get("structural_memo", "")

    structural_memo_text = st.text_area(
        "構造設計メモ本文",
        value=st.session_state[memo_key],
        height=520,
        key=memo_key,
        placeholder="""例：
【構造設計メモ】
・架構方針
・荷重条件
・基礎、杭、地盤条件
・意匠、設備との調整事項
・次回確認事項
""",
    )

    memo_col1, memo_col2, memo_col3 = st.columns([1, 1, 3])

    with memo_col1:
        if st.button("💾 メモを保存", key=f"save_structural_memo_body_{project['id']}"):
            notify_action_start("構造設計メモの保存を開始しました")
            try:
                with st.spinner("構造設計メモを保存中です..."):
                    project["structural_memo"] = structural_memo_text
                    project["structural_memo_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    persist_data(data)
                queue_feedback("success", "構造設計メモを保存しました。")
                rerun_app()
            except Exception:
                st.error("構造設計メモの保存に失敗しました。もう一度確認してください。")

    with memo_col2:
        structural_memo_a4_text = f"""構造設計メモ
============================================================
物件名：{project.get('name', '')}
相手先・担当：{project.get('client', '')}
更新日：{datetime.now().strftime('%Y-%m-%d %H:%M')}

{structural_memo_text}

# END
"""
        st.download_button(
            "📄 メモtxt出力",
            data=structural_memo_a4_text.encode("utf-8-sig"),
            file_name=f"{safe_project_name}_構造設計メモ.txt",
            mime="text/plain",
            key=f"download_structural_memo_body_{project['id']}",
            on_click=notify_download_start,
            args=("メモtxt出力を開始しました",),
        )

    st.divider()

st.divider()

st.subheader("🎙 音声メモ")

voice_memo_key = f"voice_memo_text_{project['id']}"
voice_memo_label = "音声メモ"
if voice_memo_key not in st.session_state:
    st.session_state[voice_memo_key] = ""

render_audio_memo_recorder(project["id"], voice_memo_key)

voice_memo_text = st.text_area(
    voice_memo_label,
    value=st.session_state[voice_memo_key],
    height=150,
    key=voice_memo_key,
    placeholder="文字起こしされた文章がここに入ります",
)

if st.button("音声メモを履歴に追加", key=f"add_voice_memo_{project['id']}", type="primary"):
    notify_action_start("音声メモの追加を開始しました")
    if not voice_memo_text.strip():
        st.error("音声メモの追加に失敗しました。テキストを入力してください。")
    else:
        try:
            with st.spinner("音声メモを履歴に追加中です..."):
                now_text = datetime.now().strftime("%Y-%m-%d %H:%M")
                project["logs"].append(
                    {
                        "id": str(uuid.uuid4()),
                        "date": str(date.today()),
                        "person": "音声メモ",
                        "content": f"【音声メモ {now_text}】\n{voice_memo_text.strip()}",
                        "status": "対応中",
                        "priority": "中",
                        "due_date": str(date.today()),
                        "attachment_path": "",
                        "created_at": now_text,
                    }
                )
                persist_data(data)
            queue_feedback("success", "音声メモを日時付きで履歴に追加しました。")
            rerun_app()
        except Exception:
            st.error("音声メモの追加に失敗しました。もう一度確認してください。")

st.divider()

st.subheader("📋 選択物件のやり取り履歴")

show_only_open = st.checkbox("未対応・対応中だけ表示")

logs = project.get("logs", [])

if show_only_open:
    logs = [x for x in logs if x.get("status") in ["未対応", "対応中"]]

logs = sorted(logs, key=lambda x: x.get("date", ""), reverse=True)

if not logs:
    st.info("表示するやり取りはありません。")

else:
    for log in logs:
        bg_color, border_color, due_label = due_style(log)
        attach_path = log.get("attachment_path", "")
        is_editing = st.session_state["editing_log_id"] == log["id"]

        if is_editing:
            bg_color = "#fffde8"
            border_color = "#d6b800"
            due_label = "編集中"

        st.markdown(card_html(log, bg_color, border_color, due_label), unsafe_allow_html=True)

        if is_editing:
            ec1, ec2, ec3 = st.columns([1, 1, 1])

            with ec1:
                edit_date = st.date_input(
                    "日付",
                    value=parse_date_safe(log.get("date", "")) or date.today(),
                    key=f"edit_date_{log['id']}",
                )

            with ec2:
                edit_status = st.selectbox(
                    "状態",
                    STATUSES,
                    index=STATUSES.index(log.get("status", "未対応")),
                    key=f"edit_status_{log['id']}",
                )

            with ec3:
                edit_priority = st.selectbox(
                    "重要度",
                    PRIORITIES,
                    index=PRIORITIES.index(log.get("priority", "中")),
                    key=f"edit_priority_{log['id']}",
                )

            edit_due = st.date_input(
                "期限",
                value=parse_date_safe(log.get("due_date", "")) or date.today(),
                key=f"edit_due_{log['id']}",
            )

            edit_person = st.text_input(
                "相手先",
                value=log.get("person", ""),
                key=f"edit_person_{log['id']}",
            )

            edit_content = st.text_area(
                "内容",
                value=log.get("content", ""),
                height=120,
                key=f"edit_content_{log['id']}",
            )

            edit_attach = st.text_input(
                "添付ファイル",
                value=log.get("attachment_path", ""),
                key=f"edit_attach_{log['id']}",
            )

            bc1, bc2, bc3, bc4 = st.columns([1, 1, 1, 5])

            with bc1:
                if st.button("💾保存", key=f"edit_save_{log['id']}"):
                    notify_action_start("修正内容の保存を開始しました")
                    try:
                        with st.spinner("修正内容を保存中です..."):
                            log["date"] = str(edit_date)
                            log["status"] = edit_status
                            log["priority"] = edit_priority
                            log["due_date"] = str(edit_due)
                            log["person"] = edit_person.strip()
                            log["content"] = edit_content.strip()
                            log["attachment_path"] = edit_attach.strip()
                            persist_data(data)
                            st.session_state["editing_log_id"] = None

                        queue_feedback("success", "修正を保存しました。")
                        rerun_app()
                    except Exception:
                        st.error("修正の保存に失敗しました。もう一度確認してください。")

            with bc2:
                if st.button("❌取消", key=f"cancel_edit_{log['id']}"):
                    notify_action_start("編集を取り消します")
                    st.session_state["editing_log_id"] = None
                    queue_feedback("success", "編集を取り消しました")
                    rerun_app()

            with bc3:
                if st.button("📎開く", key=f"open_edit_attach_{log['id']}"):
                    notify_action_start("添付ファイルを開いています")
                    with st.spinner("添付ファイルを確認中です..."):
                        open_path(edit_attach)
                    st.toast("添付ファイルを開く処理が完了しました")

        else:
            c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 4])

            with c1:
                if st.button("✏編集", key=f"edit_{log['id']}"):
                    notify_action_start("編集画面を表示します")
                    st.session_state["editing_log_id"] = log["id"]
                    queue_feedback("success", "編集画面を表示しました")
                    rerun_app()

            with c2:
                if st.button("✔保存", key=f"save_{log['id']}"):
                    notify_action_start("保存を開始しました")
                    try:
                        with st.spinner("保存中です..."):
                            persist_data(data)
                        queue_feedback("success", "保存しました。")
                        rerun_app()
                    except Exception:
                        st.error("保存に失敗しました。もう一度確認してください。")

            with c3:
                if st.button("🗑削除", key=f"delete_{log['id']}"):
                    notify_action_start("削除を開始しました")
                    try:
                        with st.spinner("削除中です..."):
                            project["logs"] = [
                                x for x in project["logs"] if x["id"] != log["id"]
                            ]
                            persist_data(data)
                        queue_feedback("warning", "物件を削除しました")
                        rerun_app()
                    except Exception:
                        st.error("削除に失敗しました。もう一度確認してください。")

            with c4:
                if attach_path:
                    if st.button("📎添付", key=f"open_attach_{log['id']}"):
                        notify_action_start("添付ファイルを開いています")
                        with st.spinner("添付ファイルを確認中です..."):
                            open_path(attach_path)
                        st.toast("添付ファイルを開く処理が完了しました")

            with c5:
                calendar_url = build_google_calendar_url(project, log)
                if st.button("📅予定登録", key=f"show_calendar_link_{log['id']}", use_container_width=True):
                    notify_action_start("カレンダー予定登録を開始しました")
                    st.session_state[f"show_calendar_link_{log['id']}"] = True
                    st.toast("カレンダー予定登録リンクを表示しました")
                if st.session_state.get(f"show_calendar_link_{log['id']}"):
                    st.link_button(
                        "Googleカレンダーで予定を作成",
                        calendar_url,
                        use_container_width=True,
                    )

        st.divider()


st.subheader("📝 やり取りを追加")

st.session_state["new_attachment_path"] = st.text_input(
    "添付ファイルパス",
    value=st.session_state["new_attachment_path"],
)


with st.form("add_log_form"):
    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        log_date = st.date_input("日付", value=date.today())

    with c2:
        status = st.selectbox("状態", STATUSES)

    with c3:
        priority = st.selectbox("重要度", PRIORITIES, index=1)

    person = st.text_input("相手先・担当者")
    content = st.text_area("内容・メモ", height=90)
    due_date = st.date_input("期限", value=date.today())

    add_log = st.form_submit_button("やり取りを追加")

    if add_log:
        notify_action_start("やり取り追加を開始しました")
        if not content.strip():
            st.error("やり取り追加に失敗しました。内容を入力してください。")
        else:
            try:
                with st.spinner("やり取りを追加中です..."):
                    project["logs"].append(
                        {
                            "id": str(uuid.uuid4()),
                            "date": str(log_date),
                            "person": person.strip(),
                            "content": content.strip(),
                            "status": status,
                            "priority": priority,
                            "due_date": str(due_date),
                            "attachment_path": st.session_state["new_attachment_path"].strip(),
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }
                    )
                    persist_data(data)
                    st.session_state["new_attachment_path"] = ""

                queue_feedback("success", "やり取りを追加しました。")
                rerun_app()
            except Exception:
                st.error("やり取り追加に失敗しました。もう一度確認してください。")

st.divider()

st.subheader("🤖 ファイル要約")

uploaded_file = st.file_uploader("要約したいPDFまたはtxtをドロップ", type=["pdf", "txt"])

if uploaded_file:
    if st.button("要約する"):
        notify_action_start("ファイル要約を開始しました")
        try:
            with st.spinner("ファイルを要約中です..."):
                text = read_uploaded_text(uploaded_file)
                st.session_state["summary_result"] = simple_summary(text)
            st.toast("ファイル要約が完了しました")
            st.success("ファイル要約が完了しました")
        except Exception:
            st.error("ファイル要約に失敗しました。ファイル形式を確認してください。")

if "summary_result" in st.session_state:
    st.text_area(
        "要約結果",
        value=st.session_state["summary_result"],
        height=260,
    )
    st.caption("保存したい場合は、この要約結果をコピーして、やり取りメモに貼り付けてください。")


st.divider()

with st.expander("物件名・相手先を編集"):
    with st.form("edit_project_name_form"):
        edit_name = st.text_input("物件名", value=project.get("name", ""))
        edit_client = st.text_input("相手先・担当", value=project.get("client", ""))

        update_project = st.form_submit_button("物件名・相手先を保存")

        if update_project:
            notify_action_start("物件情報の保存を開始しました")
            try:
                with st.spinner("物件情報を保存中です..."):
                    project["name"] = edit_name.strip()
                    project["client"] = edit_client.strip()
                    persist_data(data)
                queue_feedback("success", "物件情報を保存しました")
                rerun_app()
            except Exception:
                st.error("物件情報の保存に失敗しました。もう一度確認してください。")


st.divider()

with st.expander("🔗 現在の物件のパス設定"):
    st.write("物件フォルダ")
    st.session_state[current_folder_key] = st.text_input(
        "現在の物件フォルダパス",
        value=st.session_state[current_folder_key],
        label_visibility="collapsed",
    )

    st.write("工程表PDF")
    st.session_state[current_pdf_key] = st.text_input(
        "現在の工程表PDFパス",
        value=st.session_state[current_pdf_key],
        label_visibility="collapsed",
    )

    save_col, open_folder_col, open_pdf_col = st.columns([1, 1, 1])

    with save_col:
        if st.button("💾 現在の物件にパスを保存", type="primary"):
            notify_action_start("パス設定の保存を開始しました")
            try:
                with st.spinner("パス設定を保存中です..."):
                    project["folder_path"] = st.session_state[current_folder_key].strip()
                    project["schedule_pdf_path"] = st.session_state[current_pdf_key].strip()
                    persist_data(data)
                queue_feedback("success", "現在の物件にパスを保存しました。")
                rerun_app()
            except Exception:
                st.error("パス設定の保存に失敗しました。もう一度確認してください。")

    with open_folder_col:
        if st.button("📂 このフォルダを開く"):
            notify_action_start("フォルダを開いています")
            with st.spinner("フォルダを確認中です..."):
                open_path(st.session_state[current_folder_key])
            st.toast("フォルダを開く処理が完了しました")

    with open_pdf_col:
        if st.button("📄 このPDFを開く"):
            notify_action_start("PDFを開いています")
            with st.spinner("PDFを確認中です..."):
                open_path(st.session_state[current_pdf_key])
            st.toast("PDFを開く処理が完了しました")


# END
