import logging
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

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数の読み込みとOpenAIクライアント初期化
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

DB_PATH = "game.db"

########################################
# DB関連関数（コンテキストマネージャーで管理）
########################################
def init_db():
    """DBとテーブルの初期化を行う"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        with conn:
            cursor = conn.cursor()
            # ユーザーテーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            # 問題テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS problems (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    problem TEXT,
                    answer TEXT,
                    hint TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            # チャット履歴テーブル
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
        return conn
    except Exception as e:
        logger.error(f"DB初期化エラー: {e}")
        raise

def insert_chat_history(problem_id, user_id, question, answer):
    """チャット履歴をDBに挿入する"""
    try:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chat_history (problem_id, user_id, question, answer) VALUES (?, ?, ?, ?)",
                (problem_id, user_id, question, answer)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"チャット履歴挿入エラー: {e}")

########################################
# OpenAI API 関連関数
########################################
def call_api(messages, model="gpt-4-turbo"):
    """OpenAI APIを呼び出して返答メッセージを返す"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"API呼び出しエラー: {e}")
        return ""

def generate_problem():
    """水平思考クイズの問題を生成する"""
    system_prompt = (
        "あなたはウミガメのスープ、水平思考クイズの生成に長けたAIです。"
        "以下の条件を満たす水平思考クイズの問題を生成してください。\n"
        "1. 問題文は現実的な設定（例：レストラン、旅行、日常の出来事など）を背景にし、参加者が「YES」「NO」「関係ありません」で答えながら真相に迫る形式にすること。\n"
        "2. 問題は理不尽すぎず、論理性を保ちながらも少しの発想の転換が必要なひねりを含むものとする。\n"
        "3. 出力は、問題文、正解の要点、解答に近づくためのヒントを含むJSON形式で行い、キーは 'problem', 'answer', 'hint' とすること。\n"
        "【例】\n"
        "{\n"
        "  \"problem\": \"ある男が、とある海の見えるレストランで『ウミガメのスープ』を注文し、一口飲んだ後に自殺した。なぜでしょうか？\",\n"
        "  \"answer\": \"男はかつて遭難し、生き延びるために仲間の肉を食べさせられた経験があり、レストランで本物のウミガメのスープの味と、自分がかつて食べた味の違いに気づいたことで絶望したため。\",\n"
        "  \"hint\": \"男はその過去の体験から味に敏感になっており、スープの味の微妙な違いが取り返しのつかない意味を持っていた。\"\n"
        "}\n"
        "上記の条件に沿った水平思考クイズを生成してください。"
        "正解はある程度導きやすいものにしてください。"
    )
    messages = [{"role": "system", "content": system_prompt}]
    response_text = call_api(messages)
    try:
        problem_data = json.loads(response_text)
        if not all(key in problem_data for key in ["problem", "answer", "hint"]):
            raise ValueError("必要なキーが不足しています。")
        return problem_data
    except Exception as e:
        logger.error(f"問題生成エラー: {e}")
        return {"problem": f"問題生成に失敗しました。{e}", "answer": "", "hint": ""}

def get_answer(problem_text, problem_answer, user_question):
    """ユーザーの質問に対して回答（はい/いいえ/わからない）を返す"""
    system_msg = (
        "あなたは水平思考ゲームの出題者です。次の問題とその正解を把握しています。\n"
        f"【問題】 {problem_text}\n【正解】 {problem_answer}\n"
        "ユーザーからの質問に対して、「はい」「いいえ」「わからない」で答えてください。"
        "もし、ユーザーの発言が正解に近い場合には、「正解」と答えてください。"
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
    except Exception as e:
        logger.error(f"回答取得エラー: {e}")
        return "わからない"

########################################
# バックグラウンド処理（非同期）
########################################
def process_question(user_question, problem_id, problem_text, problem_answer, user_id):
    """ユーザーの質問処理をスレッド内で実行する"""
    try:
        answer = get_answer(problem_text, problem_answer, user_question)
        insert_chat_history(problem_id, user_id, user_question, answer)
    except Exception as e:
        logger.error(f"質問処理エラー: {e}")

def process_regenerate():
    """問題再生成処理"""
    generated = generate_problem()
    try:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO problems (problem, answer, hint) VALUES (?, ?, ?)",
                (generated["problem"], generated["answer"], generated["hint"])
            )
            conn.commit()
            new_problem_id = cursor.lastrowid
        st.session_state.new_problem = {
            "id": new_problem_id,
            "problem": generated["problem"],
            "answer": generated["answer"],
            "hint": generated["hint"]
        }
        st.session_state.regenerate_done = True
    except Exception as e:
        logger.error(f"問題再生成エラー: {e}")

########################################
# ユーザー登録・問題取得・表示関連
########################################
def display_name_input():
    """ユーザー登録画面の表示"""
    st.title("ユーザー登録")
    user_name = st.text_input("名前を入力してください:")
    if st.button("登録"):
        if not user_name.strip():
            st.error("名前を入力してください。")
        else:
            try:
                with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO users (name) VALUES (?)", (user_name.strip(),))
                    conn.commit()
                    st.session_state.user_id = cursor.lastrowid
                    st.session_state.user_name = user_name.strip()
                st.experimental_rerun()
            except Exception as e:
                st.error(f"ユーザー登録に失敗しました: {e}")
                logger.error(f"ユーザー登録エラー: {e}")

def get_current_problem():
    """現在の問題を取得または生成しセッションに保存"""
    try:
        if "current_problem_id" not in st.session_state:
            with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
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
        logger.error(f"問題取得エラー: {e}")
        return None, {}

def display_problem_area():
    """問題と操作ボタンの表示"""
    st.title("ウミガメのスープ・水平思考クイズ")
    st.header("【問題】")
    st.markdown(f"<div style='font-size:18px;'>{st.session_state.current_problem['problem']}</div>",
                unsafe_allow_html=True)
    cols = st.columns(4)
    with cols[0]:
        if st.button("問題を再生成する"):
            st.session_state.regenerate_done = False
            with st.spinner("問題再生成中..."):
                process_regenerate()
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
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
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
        logger.error(f"チャット履歴表示エラー: {e}")

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

########################################
# メイン処理
########################################
def main():
    st_autorefresh(interval=500, key="chatrefresh")
    conn = init_db()

    # ユーザー登録：未登録の場合は登録画面を表示
    if "user_id" not in st.session_state:
        display_name_input()
        st.stop()

    # 現在の問題を取得または生成
    get_current_problem()

    # 問題再生成が完了している場合、セッション状態を更新して再描画
    if st.session_state.get("regenerate_done", False):
        st.session_state.current_problem_id = st.session_state.new_problem["id"]
        st.session_state.current_problem = {
            "problem": st.session_state.new_problem["problem"],
            "answer": st.session_state.new_problem["answer"],
            "hint": st.session_state.new_problem["hint"]
        }
        st.session_state.pop("new_problem", None)
        st.experimental_rerun()

    # メインエリアの表示
    display_problem_area()
    st.markdown("---")
    display_chat_history()
    st.markdown("---")
    display_question_input()

if __name__ == "__main__":
    main()
