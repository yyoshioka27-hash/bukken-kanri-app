# app_bkanri.py

import streamlit as st
import json
import os
import shutil
import uuid
import html
import urllib.parse
import base64
import requests
from datetime import datetime, date
from pathlib import Path

try:
    from streamlit_local_storage import LocalStorage
except Exception:
    LocalStorage = None

APP_TITLE = "物件管理アプリ"
DEFAULT_DATA_DIR = Path(r"C:\構造設計メモ管理データ")
LOCAL_DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_FILE_NAME = "bukken_data.json"
GITHUB_DATA_PATH = f"data/{DATA_FILE_NAME}"

STATUSES = ["未対応", "対応中", "対応済", "連絡待ち","保留"]
PRIORITIES = ["低", "中", "高"]

LOCAL_STORAGE_KEY = "bukken_kanri_data_v1"
APP_STATE_STORAGE_KEY = "bukken_kanri_app_state_v1"
APP_SETTINGS_FILE = Path(__file__).resolve().parent / "app_settings.json"


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
    normalized = normalize_data(data)
    st.session_state["data"] = normalized
    save_data(normalized)
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
            "filter_mode": normalize_filter_mode(payload.get("filter_mode", "すべて")),
        }
    except Exception:
        return None


def normalize_app_settings(settings):
    if not isinstance(settings, dict):
        return None
    data_file_path = str(settings.get("data_file_path", "")).strip()
    if not data_file_path:
        return None
    return {"data_file_path": data_file_path}


def load_app_settings():
    if not APP_SETTINGS_FILE.exists():
        return None
    try:
        with open(APP_SETTINGS_FILE, "r", encoding="utf-8") as f:
            return normalize_app_settings(json.load(f))
    except Exception:
        return None


def save_app_settings(data_file_path):
    settings = normalize_app_settings({"data_file_path": data_file_path})
    if settings is None:
        return
    try:
        with open(APP_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    st.session_state["app_settings"] = settings
    st.session_state["data_file_path"] = settings["data_file_path"]


def clear_app_settings():
    st.session_state.pop("app_settings", None)
    st.session_state.pop("data_file_path", None)
    if APP_SETTINGS_FILE.exists():
        try:
            APP_SETTINGS_FILE.unlink()
        except Exception:
            pass


def resolve_data_file_path(path_text):
    if not path_text:
        return None
    p = Path(str(path_text).strip().strip('"').strip("'"))
    if p.suffix.lower() == ".json":
        return p
    return p / DATA_FILE_NAME


def restore_app_settings():
    if "app_settings" in st.session_state:
        settings = normalize_app_settings(st.session_state["app_settings"])
        if settings:
            st.session_state["data_file_path"] = settings["data_file_path"]
            return settings

    settings = load_app_settings()
    if settings:
        st.session_state["app_settings"] = settings
        st.session_state["data_file_path"] = settings["data_file_path"]
        return settings
    return None

def load_initial_data():
    app_state = load_app_state()
    if app_state is not None:
        st.session_state["selected_project_id"] = app_state.get("selected_project_id")
        st.session_state["filter_mode"] = app_state.get("filter_mode", "すべて")

    return load_data()


def get_data_file():
    if "data_file_path" in st.session_state:
        return Path(st.session_state["data_file_path"])
    return LOCAL_DATA_DIR / DATA_FILE_NAME


def get_data_dir():
    return get_data_file().parent


def get_backup_dir():
    return get_data_dir() / "backup"


def get_export_text_dir():
    return get_data_dir() / "export_text"


def init_dirs():
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    get_backup_dir().mkdir(parents=True, exist_ok=True)
    get_export_text_dir().mkdir(parents=True, exist_ok=True)


def normalize_data(data):
    if not isinstance(data, dict):
        return {"projects": []}
    if "projects" not in data or not isinstance(data["projects"], list):
        data["projects"] = []
    return data


def load_data():
    init_dirs()
    github_data, github_error = load_data_from_github()
    if github_data is not None:
        return github_data
    if github_error:
        st.error(f"GitHubからのデータ読み込みに失敗したためローカル保存を使用します。原因: {github_error}")

    data_file = get_data_file()
    if not data_file.exists():
        return {"projects": []}
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return normalize_data(data)
    except Exception:
        return {"projects": []}


def save_data(data):
    init_dirs()
    data = normalize_data(data)
    github_error = save_data_to_github(data)
    if github_error:
        st.error(f"GitHubへの保存に失敗したためローカル保存のみ実行しました。原因: {github_error}")

    data_file = get_data_file()
    backup_dir = get_backup_dir()
    if data_file.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(data_file, backup_dir / f"bukken_data_{ts}.json")
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

    /* calendar popup */
    div[role="dialog"],
    div[role="listbox"],
    ul[role="listbox"] {
        background-color: #ffffff !important;
        color: #111111 !important;
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

    /* Streamlit popover */
    [data-baseweb="popover"] {
        background-color: #ffffff !important;
        color: #111111 !important;
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
st.link_button("📅 カレンダー", calendar_url, use_container_width=False)


if "selected_project_id" not in st.session_state:
    st.session_state["selected_project_id"] = None

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

if "data" not in st.session_state:
    app_settings = restore_app_settings()
    if app_settings is not None:
        st.session_state["data"] = load_initial_data()
    else:
        st.session_state["data"] = {"projects": []}

data = st.session_state["data"]


def render_project_management_panel(panel_prefix="sidebar"):
    # 上部：日常利用の中心（一覧・フィルタ・選択）
    st.header("📌 物件一覧")

    if data["projects"]:
        st.caption("表示フィルタ")
        radio_key = "filter_mode" if panel_prefix == "sidebar" else f"{panel_prefix}_filter_mode"
        default_index = ["すべて", "未対応あり", "重要度高あり"].index(st.session_state.get("filter_mode", "すべて"))
        filter_mode = st.radio("表示", ["すべて", "未対応あり", "重要度高あり"], index=default_index, key=radio_key)
        save_app_state()
        st.caption("物件選択一覧")

        for p in data["projects"]:
            open_count = count_open_logs(p)
            high_count = count_high_logs(p)

            if filter_mode == "未対応あり" and open_count == 0:
                continue

            if filter_mode == "重要度高あり" and high_count == 0:
                continue

            label = f"{p.get('name', '')}｜未{open_count}｜高{high_count}"

            if st.button(label, key=f"{panel_prefix}_select_{p['id']}", use_container_width=True):
                st.session_state["selected_project_id"] = p["id"]
                save_app_state()
                st.rerun()

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
            if not name.strip():
                st.warning("物件名を入力してください。")
            else:
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
                st.session_state["folder_path_temp"] = ""
                st.session_state["pdf_path_temp"] = ""

                st.success("物件を追加しました。")
                st.rerun()

    st.divider()

    st.header("📂 現在の保存先")
    st.caption(str(get_data_file()))

    if "show_storage_selector" not in st.session_state:
        st.session_state["show_storage_selector"] = st.session_state.get("app_settings") is None

    if st.session_state.get("app_settings") is not None:
        if st.button("保存先を変更", key=f"{panel_prefix}_change_storage", use_container_width=True):
            st.session_state["show_storage_selector"] = True

    if st.session_state.get("show_storage_selector", False):
        with st.form(f"{panel_prefix}_storage_settings_form"):
            storage_path = st.text_input(
                "JSONファイルまたは保存フォルダ",
                value=str(get_data_file()),
                help="例: C:\\構造設計メモ管理データ\\bukken_data.json または C:\\構造設計メモ管理データ",
            )
            if st.form_submit_button("保存先を確定", use_container_width=True):
                resolved = resolve_data_file_path(storage_path)
                if resolved is None:
                    st.error("保存先を入力してください。")
                else:
                    save_app_settings(str(resolved))
                    st.session_state["show_storage_selector"] = False
                    st.session_state["data"] = load_initial_data()
                    st.success("保存先を保存しました。次回起動時も自動で読み込みます。")
                    st.rerun()

    st.divider()

    # 最下部：読込・保存関連
    st.header("💾 読込・保存")
    uploaded_json = st.file_uploader(
        "JSON読込",
        type=["json"],
        accept_multiple_files=False,
        help="bukken_data.json を選択してください。",
    )
    if st.button("JSON読込", key=f"{panel_prefix}_json_load", use_container_width=True):
        if uploaded_json is None:
            st.warning("先にJSONファイルを選択してください。")
        else:
            try:
                raw_json = uploaded_json.getvalue()
                try:
                    uploaded_data = json.loads(raw_json.decode("utf-8"))
                except UnicodeDecodeError:
                    uploaded_data = json.loads(raw_json.decode("utf-8-sig"))

                st.session_state["data"] = normalize_data(uploaded_data)
                if st.session_state["data"]["projects"]:
                    st.session_state["selected_project_id"] = st.session_state["data"]["projects"][0]["id"]
                else:
                    st.session_state["selected_project_id"] = None

                # 読込直後に保存済みJSONとして即時登録（JOINボタン不要）
                save_data(st.session_state["data"])
                save_local_storage_data(st.session_state["data"])
                save_app_state()

                st.success("JSONを読み込み、保存済みJSONとして登録しました。次回起動時は自動復元されます。")
                st.rerun()
            except Exception:
                st.error("JSONの読み込みに失敗しました。形式を確認してください。")

    st.download_button(
        "JSON保存",
        data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="bukken_data.json",
        mime="application/json",
        use_container_width=True,
        key=f"{panel_prefix}_json_save",
    )


with st.sidebar:
    render_project_management_panel("sidebar")

if "mobile_view" not in st.session_state:
    st.session_state["mobile_view"] = "detail"

st.markdown('<div class="mobile-toggle-bar">', unsafe_allow_html=True)
mv1, mv2 = st.columns(2)
with mv1:
    if st.button("物件一覧", key="mobile_show_list", use_container_width=True):
        st.session_state["mobile_view"] = "list"
        st.rerun()
with mv2:
    if st.button("物件詳細", key="mobile_show_detail", use_container_width=True):
        st.session_state["mobile_view"] = "detail"
        st.rerun()
st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.get("mobile_view") == "list":
    st.markdown('<div class="mobile-panel">', unsafe_allow_html=True)
    render_project_management_panel("mobile")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


if not data["projects"]:
    st.info("左側から物件を登録してください。")
    st.stop()


if st.session_state["selected_project_id"] is None:
    st.session_state["selected_project_id"] = data["projects"][0]["id"]
    save_app_state()


project = get_project(data, st.session_state["selected_project_id"])

if project is None:
    project = data["projects"][0]
    st.session_state["selected_project_id"] = project["id"]
    save_app_state()


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
        open_path(project.get("schedule_pdf_path", ""))

with col3:
    st.write("")
    st.write("")
    if st.button("📂 物件フォルダを開く", key=f"open_project_folder_{project['id']}"):
        open_path(project.get("folder_path", ""))

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
    )

    if st.button("📝 構造設計メモ", key=f"open_structural_memo_{project['id']}", use_container_width=True):
        st.session_state["show_structural_memo_editor"] = not st.session_state["show_structural_memo_editor"]


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
            project["structural_memo"] = structural_memo_text
            project["structural_memo_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            persist_data(data)
            st.success("構造設計メモを保存しました。")
            st.rerun()

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
        )

    st.divider()

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
                    log["date"] = str(edit_date)
                    log["status"] = edit_status
                    log["priority"] = edit_priority
                    log["due_date"] = str(edit_due)
                    log["person"] = edit_person.strip()
                    log["content"] = edit_content.strip()
                    log["attachment_path"] = edit_attach.strip()

                    persist_data(data)

                    st.session_state["editing_log_id"] = None

                    st.success("修正を保存しました。")
                    st.rerun()

            with bc2:
                if st.button("❌取消", key=f"cancel_edit_{log['id']}"):
                    st.session_state["editing_log_id"] = None
                    st.rerun()

            with bc3:
                if st.button("📎開く", key=f"open_edit_attach_{log['id']}"):
                    open_path(edit_attach)

        else:
            c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 4])

            with c1:
                if st.button("✏編集", key=f"edit_{log['id']}"):
                    st.session_state["editing_log_id"] = log["id"]
                    st.rerun()

            with c2:
                if st.button("✔保存", key=f"save_{log['id']}"):
                    persist_data(data)
                    st.success("保存しました。")
                    st.rerun()

            with c3:
                if st.button("🗑削除", key=f"delete_{log['id']}"):
                    project["logs"] = [
                        x for x in project["logs"] if x["id"] != log["id"]
                    ]
                    persist_data(data)
                    st.warning("削除しました。")
                    st.rerun()

            with c4:
                if attach_path:
                    if st.button("📎添付", key=f"open_attach_{log['id']}"):
                        open_path(attach_path)

            with c5:
                calendar_url = build_google_calendar_url(project, log)
                st.link_button(
                    "📅予定登録",
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
        if not content.strip():
            st.warning("内容を入力してください。")
        else:
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

            st.success("やり取りを追加しました。")
            st.rerun()


st.divider()

st.subheader("🤖 ファイル要約")

uploaded_file = st.file_uploader("要約したいPDFまたはtxtをドロップ", type=["pdf", "txt"])

if uploaded_file:
    if st.button("要約する"):
        text = read_uploaded_text(uploaded_file)
        st.session_state["summary_result"] = simple_summary(text)

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
            project["name"] = edit_name.strip()
            project["client"] = edit_client.strip()
            persist_data(data)
            st.success("物件情報を保存しました。")
            st.rerun()


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
            project["folder_path"] = st.session_state[current_folder_key].strip()
            project["schedule_pdf_path"] = st.session_state[current_pdf_key].strip()
            persist_data(data)
            st.success("現在の物件にパスを保存しました。")
            st.rerun()

    with open_folder_col:
        if st.button("📂 このフォルダを開く"):
            open_path(st.session_state[current_folder_key])

    with open_pdf_col:
        if st.button("📄 このPDFを開く"):
            open_path(st.session_state[current_pdf_key])


# END
