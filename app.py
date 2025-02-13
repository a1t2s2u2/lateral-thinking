import streamlit as st
import sqlite3
import threading
import os
import json
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
from apscheduler.schedulers.background import BackgroundScheduler
from openai import OpenAI
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

# OpenAI APIの最新形式でクライアント初期化
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

########################################
# DB初期化
########################################
def init_db():
    conn = sqlite3.connect("game.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem TEXT,
            answer TEXT,
            hint TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id INTEGER,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            timestamp TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    return conn

########################################
# OpenAI API 関連関数
########################################
def call_api(messages, model):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return response.choices[0].message.content.strip()

def generate_problem():
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは水平思考問題の生成に長けたAIです。創造的で興味深い水平思考問題を生成してください。"
                "問題文、答え、ヒントを含むJSON形式で出力してください。JSONのキーは 'problem', 'answer', 'hint' としてください。"
            )
        }
    ]
    response_text = call_api(messages, model="gpt-4-turbo")
    try:
        problem_data = json.loads(response_text)
        if not all(key in problem_data for key in ["problem", "answer", "hint"]):
            raise ValueError("必要なキーが不足しています。")
        return problem_data
    except Exception as e:
        return {"problem": f"問題生成に失敗しました。{e}", "answer": "", "hint": ""}

def get_answer(problem_text, problem_answer, user_question):
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは水平思考ゲームの回答者です。次の問題とその正解を把握しています。\n"
                f"【問題】 {problem_text}\n【正解】 {problem_answer}\n"
                "ユーザーからの質問に対して、必ず「はい」「いいえ」「わからない」のみで答えてください。"
            )
        },
        {"role": "user", "content": user_question}
    ]
    try:
        answer_text = call_api(messages, model="gpt-4-turbo").strip()
        for valid in ["はい", "いいえ", "わからない"]:
            if answer_text.startswith(valid):
                return valid
        return "わからない"
    except Exception as e:
        return "わからない"

########################################
# バックグラウンドでの質問処理（非同期）
########################################
def process_question(user_question, problem_id, problem_text, problem_answer, user_id):
    # APIから回答を取得
    answer = get_answer(problem_text, problem_answer, user_question)
    # 別スレッド用に新規DB接続を確立（SQLiteはスレッド間共有に注意）
    conn_thread = init_db()
    cursor_thread = conn_thread.cursor()
    cursor_thread.execute(
        "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
        (problem_id, user_id, user_question, answer)
    )
    conn_thread.commit()
    conn_thread.close()

########################################
# 定期実行タスク（例：バックグラウンドでの処理）
########################################
INTERVAL = 5000  # ミリ秒単位（例: 5000ms=5秒）
def scheduled_market_update():
    # ダミーの定期処理
    print("Scheduled task executed at", datetime.now())

@st.cache_resource
def get_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scheduled_market_update, 'interval', seconds=INTERVAL/1000)
    scheduler.start()
    return scheduler

# アプリ起動時にスケジューラーを初期化（キャッシュにより一度だけ）
scheduler = get_scheduler()

########################################
# メインアプリ部分
########################################
st_autorefresh(interval=500, key="chatrefresh")
conn = init_db()
cursor = conn.cursor()

# ユーザー登録（セッション）
if "user_id" not in st.session_state:
    st.sidebar.header("ユーザー登録")
    user_name = st.sidebar.text_input("名前を入力してください:")
    if st.sidebar.button("登録"):
        if not user_name.strip():
            st.sidebar.error("名前を入力してください。")
        else:
            cursor.execute("INSERT INTO users (name) VALUES (?)", (user_name.strip(),))
            conn.commit()
            st.session_state.user_id = cursor.lastrowid
            st.session_state.user_name = user_name.strip()
            st.rerun()

if "user_id" not in st.session_state:
    st.warning("サイドバーからユーザー登録をしてください。")
    st.stop()

# 現在の問題取得または新規作成
if "current_problem_id" not in st.session_state:
    cursor.execute("SELECT id, problem, answer, hint FROM problems ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        problem_id, problem_text, problem_answer, problem_hint = row
    else:
        generated = generate_problem()
        problem_text = generated["problem"]
        problem_answer = generated["answer"]
        problem_hint = generated["hint"]
        cursor.execute("INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
                       (problem_text, problem_answer, problem_hint))
        conn.commit()
        problem_id = cursor.lastrowid
    st.session_state.current_problem_id = problem_id
    st.session_state.current_problem = {"problem": problem_text, "answer": problem_answer, "hint": problem_hint}

if "show_answer" not in st.session_state:
    st.session_state.show_answer = False
if "show_hint" not in st.session_state:
    st.session_state.show_hint = False

st.title("水平思考ゲーム")
st.write("【問題】")
st.write(st.session_state.current_problem["problem"])

# 問題再生成ボタン
if st.button("問題を再生成する"):
    generated = generate_problem()
    problem_text = generated["problem"]
    problem_answer = generated["answer"]
    problem_hint = generated["hint"]
    cursor.execute("INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
                   (problem_text, problem_answer, problem_hint))
    conn.commit()
    st.session_state.current_problem_id = cursor.lastrowid
    st.session_state.current_problem = {"problem": problem_text, "answer": problem_answer, "hint": problem_hint}
    st.rerun()

st.markdown("---")
st.write("【操作方法】")
st.write("・画面下部の入力欄に質問を入力してください。")
st.write("・質問に対して、OpenAI API を利用して回答（「はい」「いいえ」「わからない」）を生成し、DBに保存します。")
st.write("※複数ユーザーが同時参加しており、画面は自動更新されます。")
st.markdown("---")

# 降参、ヒント表示ボタン
col1, col2 = st.columns(2)
with col1:
    if st.button("降参する"):
       st.session_state.show_answer = True
with col2:
    if st.button("ヒントを表示する"):
       st.session_state.show_hint = True
       if "hint_recorded" not in st.session_state:
           cursor.execute("INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
                          (st.session_state.current_problem_id, st.session_state.user_id, "ヒントを表示", st.session_state.current_problem["hint"]))
           conn.commit()
           st.session_state.hint_recorded = True

if st.session_state.get("show_answer"):
    st.markdown("### 答え")
    st.write(st.session_state.current_problem["answer"])
if st.session_state.get("show_hint"):
    st.markdown("### ヒント")
    st.write(st.session_state.current_problem["hint"])

# ユーザーの質問入力（非同期バックグラウンド処理）
user_question = st.text_input("質問を入力してください:", key="user_input")
if st.button("送信", key="send_question"):
    if user_question.strip():
        threading.Thread(
            target=process_question,
            args=(
                user_question,
                st.session_state.current_problem_id,
                st.session_state.current_problem["problem"],
                st.session_state.current_problem["answer"],
                st.session_state.user_id
            )
        ).start()
        st.success("質問を送信しました。回答がチャット履歴に反映されるまでお待ちください。")
        # ※入力値のクリアは行わない（widgetのキーを直接変更できないため）
    else:
        st.error("質問を入力してください。")

# 【最終回答の提出】セクション
st.markdown("---")
st.header("最終回答の提出")
final_answer = st.text_input("あなたの最終回答を入力してください:", key="final_answer")
if st.button("回答を送信する", key="submit_final_answer"):
    if final_answer.strip():
        correct = final_answer.strip().lower() == st.session_state.current_problem["answer"].strip().lower()
        result = "正解" if correct else "不正解"
        cursor.execute("INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
                       (st.session_state.current_problem_id, st.session_state.user_id, f"回答提出: {final_answer.strip()}", result))
        conn.commit()
        st.rerun()
    else:
        st.error("回答を入力してください。")

# チャット履歴の表示
cursor.execute("SELECT question, answer, timestamp FROM chat_history WHERE problem_id = ? ORDER BY timestamp",
               (st.session_state.current_problem_id,))
chats = cursor.fetchall()
if chats:
    st.markdown("### チャット履歴")
    for idx, (question, answer, timestamp) in enumerate(chats, start=1):
        st.write(f"No. {idx}")
        st.write(f"質問: {question}")
        st.write(f"回答: {answer} （{timestamp}）")

st.markdown("---")
st.markdown("### 過去の問題一覧")
cursor.execute("SELECT id, problem, created_at FROM problems ORDER BY created_at DESC")
problems_list = cursor.fetchall()
for pid, ptext, pcreated in problems_list:
    st.write(f"ID: {pid} - {ptext} （{pcreated}）")
