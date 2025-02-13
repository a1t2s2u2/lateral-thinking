import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# 環境変数の読み込み
load_dotenv()

# OpenAI APIキーの設定（最新の形式を利用）
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

def call_api(messages, model):
    """
    OpenAI API を呼び出し、レスポンスの本文を返す共通関数。
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    return response.choices[0].message.content.strip()

def generate_problem():
    """
    水平思考問題を日本語で1つ生成します。  
    問題文、答え、ヒントを含むJSON形式で出力してください。  
    JSON のキーは 'problem', 'answer', 'hint' としてください。
    """
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは水平思考問題の生成に長けたAIです。創造的で興味深い水平思考問題を生成してください。"
                "また、問題文に加え、答えとヒントも含めたJSON形式で出力してください。"
                "JSONのキーは 'problem', 'answer', 'hint' としてください。"
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

def get_answer(problem_text, user_question):
    """
    問題文とユーザーの質問に基づいて、  
    「はい」「いいえ」「わからない」のいずれかの回答を生成します。
    """
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは水平思考ゲームの回答者です。以下の問題に対して、"
                "ユーザーからの質問に「はい」「いいえ」「わからない」のみで答えてください。"
                "回答は必ずその3つのいずれかの単語で答えてください。"
            )
        },
        {"role": "assistant", "content": f"問題: {problem_text}"},
        {"role": "user", "content": user_question}
    ]
    try:
        answer_text = call_api(messages, model="gpt-4-turbo")
        if answer_text not in ["はい", "いいえ", "わからない"]:
            return "わからない"
        return answer_text
    except Exception as e:
        return "わからない"
