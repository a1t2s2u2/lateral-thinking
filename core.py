import logging
import sqlite3
import os
import json
from openai import OpenAI
from dotenv import load_dotenv

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
        return {
            "id": new_problem_id,
            "problem": generated["problem"],
            "answer": generated["answer"],
            "hint": generated["hint"]
        }
    except Exception as e:
        logger.error(f"問題再生成エラー: {e}")
        return None
