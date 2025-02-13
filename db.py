import sqlite3

def init_db():
    """
    SQLiteデータベースの初期化とテーブル作成を行います。  
    ユーザー、問題、チャット履歴のテーブルを作成します。
    """
    conn = sqlite3.connect("game.db", check_same_thread=False)
    cursor = conn.cursor()
    # ユーザーテーブル（名前のみ）
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    # 問題テーブル
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem TEXT,
            answer TEXT,
            hint TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
        """
    )
    # チャット履歴テーブル
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id INTEGER,
            user_id INTEGER,
            question TEXT,
            answer TEXT,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(problem_id) REFERENCES problems(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    
    # 既存の chat_history テーブルが旧スキーマの場合、つまり「game_id」しかない場合はマイグレーションを試みる
    cursor.execute("PRAGMA table_info(chat_history)")
    columns = [col[1] for col in cursor.fetchall()]
    if "problem_id" not in columns and "game_id" in columns:
        try:
            cursor.execute("ALTER TABLE chat_history RENAME COLUMN game_id TO problem_id")
            print("Renamed column game_id to problem_id in chat_history table.")
        except Exception as e:
            print("自動マイグレーションに失敗しました。game.db を削除して再実行してください。")
    conn.commit()
    return conn
