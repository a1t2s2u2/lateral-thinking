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

# 環境変数の読み込みとOpenAIクライアント初期化
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

DB_PATH = "game.db"

########################################
# DB関連関数
########################################
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    # ユーザーテーブル作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # 問題テーブル作成
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem TEXT,
            answer TEXT,
            hint TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # チャット履歴テーブル作成
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

def insert_chat_history(problem_id, user_id, question, answer):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
        (problem_id, user_id, question, answer)
    )
    conn.commit()
    conn.close()

########################################
# OpenAI API 関連関数
########################################
def call_api(messages, model="gpt-4-turbo"):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return response.choices[0].message.content.strip()

def generate_problem():
    system_msg = (
        "あなたはウミガメのスープ、水平思考クイズの生成に長けたAIです。"
        "創造的で興味深いウミガメのスープの問題を生成してください。"
        "正解に辿り着くには、発想が必要なものが好ましいです。"
        "出力は、問題文、答え、ヒントを含むJSON形式で、キーは 'problem', 'answer', 'hint' としてください。"
    )
    messages = [{"role": "system", "content": system_msg}]
    response_text = call_api(messages)
    try:
        problem_data = json.loads(response_text)
        if not all(key in problem_data for key in ["problem", "answer", "hint"]):
            raise ValueError("必要なキーが不足しています。")
        return problem_data
    except Exception as e:
        return {"problem": f"問題生成に失敗しました。{e}", "answer": "", "hint": ""}

def get_answer(problem_text, problem_answer, user_question):
    system_msg = (
        "あなたは水平思考ゲームの回答者です。次の問題とその正解を把握しています。\n"
        f"【問題】 {problem_text}\n【正解】 {problem_answer}\n"
        "ユーザーからの質問に対して、必ず「はい」「いいえ」「わからない」のみで答えてください。"
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_question}
    ]
    try:
        answer_text = call_api(messages)
        for valid in ["はい", "いいえ", "わからない"]:
            if answer_text.startswith(valid):
                return valid
        return "わからない"
    except Exception:
        return "わからない"

def check_final_answer_via_api(submitted, correct):
    system_msg = (
        "あなたはウミガメのスープ・水平思考クイズの審判です。"
        "ユーザーの最終回答と正解を比較して、正解の場合は必ず「正解」、不正解の場合は必ず「不正解」とだけ答えてください。"
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": f"正解は「{correct}」です。ユーザーの回答は「{submitted}」です。"}
    ]
    result = call_api(messages)
    return result if result in ["正解", "不正解"] else "不正解"

########################################
# バックグラウンド処理（非同期）
########################################
def process_question(user_question, problem_id, problem_text, problem_answer, user_id):
    answer = get_answer(problem_text, problem_answer, user_question)
    insert_chat_history(problem_id, user_id, user_question, answer)

def process_regenerate():
    generated = generate_problem()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
        (generated["problem"], generated["answer"], generated["hint"])
    )
    conn.commit()
    new_problem_id = cursor.lastrowid
    conn.close()
    st.session_state.new_problem = {
        "id": new_problem_id,
        "problem": generated["problem"],
        "answer": generated["answer"],
        "hint": generated["hint"]
    }
    st.session_state.regenerate_done = True

def process_final_answer(final_answer, problem_id, user_id, problem_answer):
    # 最終回答のチェック処理を実行し、結果をチャット履歴に登録
    result = check_final_answer_via_api(final_answer, problem_answer)
    insert_chat_history(problem_id, user_id, f"回答提出: {final_answer}", result)

########################################
# UI描画関数
########################################
def display_sidebar(cursor, conn):
    st.sidebar.title("ユーザー登録＆操作説明")
    if "user_id" not in st.session_state:
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
    else:
        st.sidebar.info(f"ようこそ、{st.session_state.user_name}さん！")
    st.sidebar.markdown("---")
    st.sidebar.subheader("操作説明")
    st.sidebar.markdown(
        """
        - 質問を入力し「送信」を押すと、回答（「はい」「いいえ」「わからない」）が生成され、チャット履歴に表示されます。  
        - 「ヒントを表示する」ボタンでヒントが表示され、チャット履歴に記録されます。  
        - 「降参する」ボタンで答えが表示されます。  
        - 最終回答を入力して提出すると、正解か不正解かの判定が OpenAI API により行われます。  
        """
    )

def get_current_problem(cursor, conn):
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
    return st.session_state.current_problem_id, st.session_state.current_problem

def display_problem_area():
    st.title("ウミガメのスープ・水平思考クイズ")
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
                insert_chat_history(
                    st.session_state.current_problem_id,
                    st.session_state.user_id,
                    "ヒントを表示",
                    st.session_state.current_problem["hint"]
                )
                st.session_state.hint_recorded = True

    if st.session_state.get("show_answer"):
        st.markdown("<h3>【答え】</h3>", unsafe_allow_html=True)
        st.write(st.session_state.current_problem["answer"])
    if st.session_state.get("show_hint"):
        st.markdown("<h3>【ヒント】</h3>", unsafe_allow_html=True)
        st.write(st.session_state.current_problem["hint"])

def display_chat_history(cursor):
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

def display_question_input():
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

def display_final_answer_submission():
    st.subheader("最終回答の提出")
    final_answer = st.text_input("あなたの最終回答を入力してください:", key="final_answer")
    if st.button("回答を送信する", key="submit_final_answer"):
        if final_answer.strip():
            threading.Thread(
                target=process_final_answer,
                args=(
                    final_answer.strip(),
                    st.session_state.current_problem_id,
                    st.session_state.user_id,
                    st.session_state.current_problem["answer"].strip()
                )
            ).start()
            st.success("最終回答を送信しました。結果がチャット履歴に反映されるまでお待ちください。")
        else:
            st.error("回答を入力してください。")

########################################
# メイン処理
########################################
def main():
    st_autorefresh(interval=500, key="chatrefresh")
    conn = init_db()
    cursor = conn.cursor()

    # サイドバー：ユーザー登録と説明
    display_sidebar(cursor, conn)

    if "user_id" not in st.session_state:
        st.warning("サイドバーからユーザー登録をしてください。")
        st.stop()

    # 現在の問題の取得または生成
    get_current_problem(cursor, conn)

    # 問題再生成が完了している場合、セッションの問題を更新して再描画
    if st.session_state.get("regenerate_done", False):
        st.session_state.current_problem_id = st.session_state.new_problem["id"]
        st.session_state.current_problem = {
            "problem": st.session_state.new_problem["problem"],
            "answer": st.session_state.new_problem["answer"],
            "hint": st.session_state.new_problem["hint"]
        }
        st.rerun()

    # メインエリアの描画
    display_problem_area()
    st.markdown("---")
    display_chat_history(cursor)
    st.markdown("---")
    display_question_input()
    st.markdown("---")
    display_final_answer_submission()

    conn.close()

if __name__ == "__main__":
    main()
