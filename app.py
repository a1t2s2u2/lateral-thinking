import streamlit as st
from streamlit_autorefresh import st_autorefresh
from db import init_db
from openai_utils import generate_problem, get_answer

# 自動更新：5秒ごとにリフレッシュ（各ユーザーの画面に最新のチャット履歴を反映）
st_autorefresh(interval=500, key="chatrefresh")

# DB初期化
conn = init_db()
cursor = conn.cursor()

# ユーザー登録（サイドバーで名前のみ入力）
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

# 現在の問題を取得、または新規作成（最新の問題を使用）
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
        cursor.execute(
            "INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
            (problem_text, problem_answer, problem_hint)
        )
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

# タイトルと問題文の表示
st.title("水平思考ゲーム")
st.write("【問題】")
st.write(st.session_state.current_problem["problem"])

# 問題再生成ボタン（新しい問題を生成し、DBに保存）
if st.button("問題を再生成する"):
    generated = generate_problem()
    problem_text = generated["problem"]
    problem_answer = generated["answer"]
    problem_hint = generated["hint"]
    cursor.execute(
        "INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
        (problem_text, problem_answer, problem_hint)
    )
    conn.commit()
    st.session_state.current_problem_id = cursor.lastrowid
    st.session_state.current_problem = {
        "problem": problem_text,
        "answer": problem_answer,
        "hint": problem_hint
    }
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
           cursor.execute(
               "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
               (st.session_state.current_problem_id, st.session_state.user_id, "ヒントを表示", st.session_state.current_problem['hint'])
           )
           conn.commit()
           st.session_state.hint_recorded = True

if st.session_state.get("show_answer"):
    st.markdown("### 答え")
    st.write(st.session_state.current_problem["answer"])
if st.session_state.get("show_hint"):
    st.markdown("### ヒント")
    st.write(st.session_state.current_problem["hint"])

# ユーザーの質問入力
user_input = st.text_input("質問を入力してください:", key="user_input")
if st.button("送信", key="send_question"):
    if user_input.strip():
        answer = get_answer(st.session_state.current_problem["problem"], user_input)
        cursor.execute(
            "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
            (st.session_state.current_problem_id, st.session_state.user_id, user_input, answer)
        )
        conn.commit()
        st.rerun()
    else:
        st.error("質問を入力してください。")

# 【最終回答の提出】セクション
st.markdown("---")
st.header("最終回答の提出")
st.write("※あなたの提出した回答は全ユーザーに共有され、正解・不正解が表示されます。")

final_answer_input = st.text_input("あなたの最終回答を入力してください:", key="final_answer")
if st.button("回答を送信する", key="submit_final_answer"):
    if final_answer_input.strip():
        # 単純な文字列比較（前後の空白と大文字小文字の違いを無視）
        correct = final_answer_input.strip().lower() == st.session_state.current_problem["answer"].strip().lower()
        result = "正解" if correct else "不正解"
        cursor.execute(
            "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
            (st.session_state.current_problem_id, st.session_state.user_id, f"回答提出: {final_answer_input.strip()}", result)
        )
        conn.commit()
        st.rerun()
    else:
        st.error("回答を入力してください。")

# 現在の問題に対するチャット履歴の表示
cursor.execute(
    "SELECT question, answer, timestamp FROM chat_history WHERE problem_id = ? ORDER BY timestamp",
    (st.session_state.current_problem_id,)
)
chats = cursor.fetchall()
if chats:
    st.markdown("### チャット履歴")
    for idx, (question, answer, timestamp) in enumerate(chats, start=1):
        st.write(f"No. {idx}")
        st.write(f"質問: {question}")
        st.write(f"回答: {answer} （{timestamp}）")

# 過去の問題一覧の表示
st.markdown("---")
st.markdown("### 過去の問題一覧")
cursor.execute(
    "SELECT id, problem, created_at FROM problems ORDER BY created_at DESC"
)
problems_list = cursor.fetchall()
for pid, ptext, pcreated in problems_list:
    st.write(f"ID: {pid} - {ptext} （{pcreated}）")
