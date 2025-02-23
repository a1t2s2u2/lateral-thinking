import logging
import streamlit as st
import sqlite3
import threading
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from core import init_db, insert_chat_history, process_question, process_regenerate, generate_problem

def get_current_problem():
    """現在の問題を取得または生成してセッションに保存する"""
    try:
        if "current_problem_id" not in st.session_state:
            with sqlite3.connect("game.db", check_same_thread=False) as conn:
                cursor = conn.cursor()
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
    except Exception as e:
        st.error(f"問題取得に失敗しました: {e}")
        return None, {}

def display_name_input():
    """ユーザー登録画面の表示"""
    st.title("ユーザー登録")
    user_name = st.text_input("名前を入力してください:")
    if st.button("登録"):
        if not user_name.strip():
            st.error("名前を入力してください。")
        else:
            try:
                with sqlite3.connect("game.db", check_same_thread=False) as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO users (name) VALUES (?)", (user_name.strip(),))
                    conn.commit()
                    st.session_state.user_id = cursor.lastrowid
                    st.session_state.user_name = user_name.strip()
                st.experimental_rerun()
            except Exception as e:
                st.error(f"ユーザー登録に失敗しました: {e}")

def display_problem_area():
    """問題と操作ボタンの表示"""
    st.title("ウミガメのスープ・水平思考クイズ")
    st.header("【問題】")
    st.markdown(f"<div style='font-size:18px;'>{st.session_state.current_problem['problem']}</div>", unsafe_allow_html=True)
    cols = st.columns(4)
    with cols[0]:
        if st.button("問題を再生成する"):
            st.session_state.regenerate_done = False
            with st.spinner("問題再生成中..."):
                new_problem = process_regenerate()
                if new_problem:
                    st.session_state.new_problem = new_problem
            st.session_state.current_problem_id = st.session_state.new_problem["id"]
            st.session_state.current_problem = {
                "problem": st.session_state.new_problem["problem"],
                "answer": st.session_state.new_problem["answer"],
                "hint": st.session_state.new_problem["hint"]
            }
            st.session_state.pop("new_problem", None)
            st.experimental_rerun()
    with cols[1]:
        if st.button("降参する"):
            st.session_state.show_answer = True
            insert_chat_history(
                st.session_state.current_problem_id,
                st.session_state.user_id,
                "降参",
                st.session_state.current_problem["answer"]
            )
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
    with cols[3]:
        if st.button("正解を表示する"):
            st.session_state.show_answer = True
            insert_chat_history(
                st.session_state.current_problem_id,
                st.session_state.user_id,
                "正解を表示",
                st.session_state.current_problem["answer"]
            )
    if st.session_state.get("show_answer"):
        st.markdown("<h3>【答え】</h3>", unsafe_allow_html=True)
        st.write(st.session_state.current_problem["answer"])
    if st.session_state.get("show_hint"):
        st.markdown("<h3>【ヒント】</h3>", unsafe_allow_html=True)
        st.write(st.session_state.current_problem["hint"])

def display_chat_history():
    """チャット履歴の表示"""
    st.subheader("チャット履歴")
    try:
        with sqlite3.connect("game.db", check_same_thread=False) as conn:
            cursor = conn.cursor()
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
    except Exception as e:
        st.error(f"チャット履歴の取得に失敗しました: {e}")

def display_question_input():
    """質問入力欄の表示"""
    st.subheader("質問入力")
    cols_input = st.columns([3, 1])
    with cols_input[0]:
        user_question = st.text_input("質問を入力してください:", key="user_input")
    with cols_input[1]:
        if st.button("送信", key="send_question"):
            if user_question.strip():
                thread = threading.Thread(
                    target=process_question,
                    args=(
                        user_question,
                        st.session_state.current_problem_id,
                        st.session_state.current_problem["problem"],
                        st.session_state.current_problem["answer"],
                        st.session_state.user_id
                    )
                )
                thread.start()
                st.success("質問を送信しました。回答がチャット履歴に反映されるまでお待ちください。")
            else:
                st.error("質問を入力してください。")

def main():
    st_autorefresh(interval=500, key="chatrefresh")
    init_db()
    if "user_id" not in st.session_state:
        display_name_input()
        st.stop()
    get_current_problem()
    if st.session_state.get("regenerate_done", False):
        st.session_state.current_problem_id = st.session_state.new_problem["id"]
        st.session_state.current_problem = {
            "problem": st.session_state.new_problem["problem"],
            "answer": st.session_state.new_problem["answer"],
            "hint": st.session_state.new_problem["hint"]
        }
        st.session_state.pop("new_problem", None)
        st.experimental_rerun()
    display_problem_area()
    st.markdown("---")
    display_chat_history()
    st.markdown("---")
    display_question_input()

if __name__ == "__main__":
    main()
