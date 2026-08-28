"""messages 表：对话历史。

只存 user 任务 + assistant 最终回答（过程事件运行中经 SSE 实时展示，不落库）。
每轮消息记录所用权限（permission_level），前端展示"这一轮用的什么权限"。
"""


class MessageTable:
    name = "messages"

    create_sql = """
    CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id INT NOT NULL,
        role VARCHAR(16) NOT NULL,
        content MEDIUMTEXT,
        permission_level INT NOT NULL DEFAULT 3,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_messages_session (session_id, id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """

    # ---------- CRUD ----------

    @staticmethod
    def add(conn, session_id: int, role: str, content: str, permission_level: int = 3) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content, permission_level) "
                "VALUES (%s, %s, %s, %s)",
                (session_id, role, content, permission_level),
            )
            return cur.lastrowid

    @staticmethod
    def list_by_session(conn, session_id: int, limit: int = 200) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM messages WHERE session_id = %s "
                "ORDER BY id ASC LIMIT %s",
                (session_id, limit),
            )
            return cur.fetchall()
