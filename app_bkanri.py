# app_bkanri.py

import streamlit as st
import json
import os
import shutil
import uuid
import html
import urllib.parse
from datetime import datetime, date
from pathlib import Path

APP_TITLE = "物件管理アプリ"
DATA_DIR = Path(r"C:\構造設計メモ管理データ")
DATA_FILE = DATA_DIR / "bukken_data.json"
BACKUP_DIR = DATA_DIR / "backup"
EXPORT_TEXT_DIR = DATA_DIR / "export_text"

STATUSES = ["未対応", "対応中", "対応済", "連絡待ち","保留"]
PRIORITIES = ["低", "中", "高"]


def init_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_TEXT_DIR.mkdir(parents=True, exist_ok=True)


def load_data():
    init_dirs()
    if not DATA_FILE.exists():
        return {"projects": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "projects" not in data:
            data["projects"] = []
        return data
    except Exception:
        return {"projects": []}


def save_data(data):
    init_dirs()
    if DATA_FILE.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(DATA_FILE, BACKUP_DIR / f"bukken_data_{ts}.json")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
    file_path = EXPORT_TEXT_DIR / f"{safe_name}_構造設計メモ_{today}.txt"

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

calendar_url = "https://calendar.google.com/"

title_col, button_col = st.columns([6, 1])

with title_col:
    st.title("📁 物件管理アプリ")

with button_col:
    st.write("")
    st.link_button("📅 カレンダー", calendar_url, use_container_width=True)

data = load_data()

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


with st.sidebar:
    st.header("📌 物件一覧")

    if data["projects"]:
        filter_mode = st.radio("表示", ["すべて", "未対応あり", "重要度高あり"])

        for p in data["projects"]:
            open_count = count_open_logs(p)
            high_count = count_high_logs(p)

            if filter_mode == "未対応あり" and open_count == 0:
                continue

            if filter_mode == "重要度高あり" and high_count == 0:
                continue

            label = f"{p.get('name', '')}｜未{open_count}｜高{high_count}"

            if st.button(label, key=f"select_{p['id']}", use_container_width=True):
                st.session_state["selected_project_id"] = p["id"]
                st.rerun()

    else:
        st.info("物件がありません。")

    st.divider()

    st.header("➕ 新規物件登録")

    st.write("物件フォルダ")
    st.session_state["folder_path_temp"] = st.text_input(
        "新規物件フォルダパス",
        value=st.session_state["folder_path_temp"],
        label_visibility="collapsed",
    )

    st.write("工程表PDF")
    st.session_state["pdf_path_temp"] = st.text_input(
        "新規工程表PDFパス",
        value=st.session_state["pdf_path_temp"],
        label_visibility="collapsed",
    )

    with st.form("add_project_form"):
        name = st.text_input("物件名")
        client = st.text_input("相手先・担当")
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
                save_data(data)

                st.session_state["selected_project_id"] = new_project["id"]
                st.session_state["folder_path_temp"] = ""
                st.session_state["pdf_path_temp"] = ""

                st.success("物件を追加しました。")
                st.rerun()

    st.divider()
    st.caption(f"保存先：{DATA_FILE}")


if not data["projects"]:
    st.info("左側から物件を登録してください。")
    st.stop()


if st.session_state["selected_project_id"] is None:
    st.session_state["selected_project_id"] = data["projects"][0]["id"]


project = get_project(data, st.session_state["selected_project_id"])

if project is None:
    project = data["projects"][0]
    st.session_state["selected_project_id"] = project["id"]


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
            save_data(data)
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

                    save_data(data)

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
                    save_data(data)
                    st.success("保存しました。")
                    st.rerun()

            with c3:
                if st.button("🗑削除", key=f"delete_{log['id']}"):
                    project["logs"] = [
                        x for x in project["logs"] if x["id"] != log["id"]
                    ]
                    save_data(data)
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

            save_data(data)

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
            save_data(data)
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
            save_data(data)
            st.success("現在の物件にパスを保存しました。")
            st.rerun()

    with open_folder_col:
        if st.button("📂 このフォルダを開く"):
            open_path(st.session_state[current_folder_key])

    with open_pdf_col:
        if st.button("📄 このPDFを開く"):
            open_path(st.session_state[current_pdf_key])


# END
