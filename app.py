import streamlit as st
import sqlite3
import threading
import os
import json
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
from openai import OpenAI
from dotenv import load_dotenv
import pandas as pd

# 環境変数の読み込み
load_dotenv()

# OpenAI APIの最新形式でクライアント初期化（キーワード引数を使用）
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
    # ウミガメのスープ／水平思考クイズ用のプロンプト
    messages = [
        {
            "role": "system",
            "content": (
                "あなたはウミガメのスープ、水平思考クイズの生成に長けたAIです。"
                "創造的で興味深いウミガメのスープの問題を生成してください。"
                "出力は、問題文、答え、ヒントを含むJSON形式で、キーは 'problem', 'answer', 'hint' としてください。"
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
# 最終回答の判定（OpenAI API を利用）
########################################
def check_final_answer_via_api(submitted, correct):
    messages = [
        {
            "role": "system",
            "content": (
                "あなたはウミガメのスープ・水平思考クイズの審判です。"
                "ユーザーの最終回答と正解を比較して、正解の場合は必ず「正解」、不正解の場合は必ず「不正解」とだけ答えてください。"
            )
        },
        {
            "role": "user",
            "content": f"正解は「{correct}」です。ユーザーの回答は「{submitted}」です。"
        }
    ]
    result = call_api(messages, model="gpt-4-turbo").strip()
    if result not in ["正解", "不正解"]:
        return "不正解"
    return result

########################################
# バックグラウンドでの質問処理（非同期）
########################################
def process_question(user_question, problem_id, problem_text, problem_answer, user_id):
    answer = get_answer(problem_text, problem_answer, user_question)
    conn_thread = init_db()
    cursor_thread = conn_thread.cursor()
    cursor_thread.execute(
        "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
        (problem_id, user_id, user_question, answer)
    )
    conn_thread.commit()
    conn_thread.close()

########################################
# 問題再生成処理（バックグラウンド実行）
########################################
def process_regenerate():
    generated = generate_problem()
    conn_reg = init_db()
    cursor_reg = conn_reg.cursor()
    cursor_reg.execute("INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
                       (generated["problem"], generated["answer"], generated["hint"]))
    conn_reg.commit()
    new_problem_id = cursor_reg.lastrowid
    conn_reg.close()
    st.session_state.new_problem = {
        "id": new_problem_id,
        "problem": generated["problem"],
        "answer": generated["answer"],
        "hint": generated["hint"]
    }
    st.session_state.regenerate_done = True

########################################
# メインアプリ部分
########################################
st_autorefresh(interval=500, key="chatrefresh")
conn = init_db()
cursor = conn.cursor()

# もし再生成完了済みなら、新しい問題に更新して再描画
if st.session_state.get("regenerate_done", False):
    st.session_state.current_problem_id = st.session_state.new_problem["id"]
    st.session_state.current_problem = {
        "problem": st.session_state.new_problem["problem"],
        "answer": st.session_state.new_problem["answer"],
        "hint": st.session_state.new_problem["hint"]
    }
    st.rerun()

# サイドバー：ユーザー登録＆操作説明
with st.sidebar:
    st.title("ユーザー登録＆操作説明")
    if "user_id" not in st.session_state:
        user_name = st.text_input("名前を入力してください:")
        if st.button("登録"):
            if not user_name.strip():
                st.error("名前を入力してください。")
            else:
                cursor.execute("INSERT INTO users (name) VALUES (?)", (user_name.strip(),))
                conn.commit()
                st.session_state.user_id = cursor.lastrowid
                st.session_state.user_name = user_name.strip()
                st.rerun()
    else:
        st.info(f"ようこそ、{st.session_state.user_name}さん！")
    st.markdown("---")
    st.subheader("操作説明")
    st.markdown(
        """
        - 質問を入力し「送信」を押すと、回答（「はい」「いいえ」「わからない」）が生成され、チャット履歴に表示されます。  
        - 「ヒントを表示する」ボタンでヒントが表示され、チャット履歴に記録されます。  
        - 「降参する」ボタンで答えが表示されます。  
        - 最終回答を入力して提出すると、正解か不正解かの判定が OpenAI API により行われます。  
        """
    )

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
    st.session_state.current_problem = {
        "problem": problem_text,
        "answer": problem_answer,
        "hint": problem_hint
    }

if "show_answer" not in st.session_state:
    st.session_state.show_answer = False
if "show_hint" not in st.session_state:
    st.session_state.show_hint = False

# メインエリア上部：問題表示＆操作ボタン（横並びの3ボタン）
st.title("ウミガメのスープ・水平思考クイズ")
with st.container():
    st.header("【問題】")
    st.markdown(f"<div style='font-size:18px;'>{st.session_state.current_problem['problem']}</div>", unsafe_allow_html=True)
    cols = st.columns(3)
    with cols[0]:
        if st.button("問題を再生成する"):
            st.session_state.regenerate_done = False
            threading.Thread(target=process_regenerate).start()
            st.info("問題再生成中...")
    with cols[1]:
        if st.button("降参する"):
            st.session_state.show_answer = True
    with cols[2]:
        if st.button("ヒントを表示する"):
            st.session_state.show_hint = True
            if "hint_recorded" not in st.session_state:
                cursor.execute(
                    "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
                    (st.session_state.current_problem_id, st.session_state.user_id, "ヒントを表示", st.session_state.current_problem["hint"])
                )
                conn.commit()
                st.session_state.hint_recorded = True

if st.session_state.get("show_answer"):
    st.markdown("<h3>【答え】</h3>", unsafe_allow_html=True)
    st.write(st.session_state.current_problem["answer"])
if st.session_state.get("show_hint"):
    st.markdown("<h3>【ヒント】</h3>", unsafe_allow_html=True)
    st.write(st.session_state.current_problem["hint"])

st.markdown("---")

# チャット履歴表示（2列：時刻, 質問（[ユーザー名] 改行 質問内容）、回答）
st.subheader("チャット履歴")
cursor.execute(
    "SELECT users.name, chat_history.question, chat_history.answer, chat_history.timestamp "
    "FROM chat_history JOIN users ON chat_history.user_id = users.id "
    "WHERE chat_history.problem_id = ? ORDER BY chat_history.timestamp",
    (st.session_state.current_problem_id,)
)
rows = cursor.fetchall()
if rows:
    data = []
    for name, question, answer, timestamp in rows:
        ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
        formatted_question = f"[{name}]\n{question}"
        data.append([ts, formatted_question, answer])
    df = pd.DataFrame(data, columns=["時刻", "質問", "回答"])
    st.table(df)
else:
    st.info("まだチャット履歴はありません。")

st.markdown("---")

# 質問入力エリア（チャット履歴の下に配置、入力欄と送信ボタンを横並び）
st.subheader("質問入力")
cols_input = st.columns([3, 1])
with cols_input[0]:
    user_question = st.text_input("質問を入力してください:", key="user_input")
with cols_input[1]:
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
        else:
            st.error("質問を入力してください。")

st.markdown("---")

# 最終回答提出エリア（OpenAI API による判定）
st.subheader("最終回答の提出")
final_answer = st.text_input("あなたの最終回答を入力してください:", key="final_answer")
if st.button("回答を送信する", key="submit_final_answer"):
    if final_answer.strip():
        result = check_final_answer_via_api(final_answer.strip(), st.session_state.current_problem["answer"].strip())
        cursor.execute(
            "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
            (st.session_state.current_problem_id, st.session_state.user_id, f"回答提出: {final_answer.strip()}", result)
        )
        conn.commit()
        st.rerun()
    else:
        st.error("回答を入力してください。")
