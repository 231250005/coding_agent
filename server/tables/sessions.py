"""sessions 表：会话。

权限是每轮对话的属性，不放在会话层（每次 chat 消息携带 permission_level）。
"""


class SessionTable:
    name = "sessions"

    create_sql = """
    CREATE TABLE IF NOT EXISTS sessions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(255) NOT NULL DEFAULT '',
        workspace VARCHAR(1024) NOT NULL,
        strategy VARCHAR(64) NOT NULL DEFAULT 'react',
        status VARCHAR(32) NOT NULL DEFAULT 'running',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """

    # ---------- CRUD ----------

    @staticmethod
    def create(conn, title: str, workspace: str, strategy: str = "react") -> int:
        """创建会话，返回 session_id。"""
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (title, workspace, strategy) VALUES (%s, %s, %s)",
                (title, workspace, strategy),
            )
            return cur.lastrowid

    @staticmethod
    def get(conn, session_id: int) -> dict | None:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE id = %s", (session_id,))
            return cur.fetchone()

    @staticmethod
    def list_all(conn) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
            return cur.fetchall()

    @staticmethod
    def update_status(conn, session_id: int, status: str) -> None:
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET status = %s WHERE id = %s", (status, session_id))

    @staticmethod
    def update_title(conn, session_id: int, title: str) -> None:
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET title = %s WHERE id = %s", (title, session_id))

    @staticmethod
    def delete(conn, session_id: int) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
