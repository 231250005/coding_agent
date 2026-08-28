"""file_changes 表：文件变更（三级权限系统的核心数据）。

- L1：pending → confirmed / rejected（用户确认后才真正写盘）
- L2：applied → reverted（保留 old/new 内容供对比与撤销）
- 会话级累积：同一会话先后用不同权限产生的变更都在这里，按状态分组展示
"""


class FileChangeTable:
    name = "file_changes"

    create_sql = """
    CREATE TABLE IF NOT EXISTS file_changes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id INT NOT NULL,
        file_path VARCHAR(1024) NOT NULL,
        operation VARCHAR(16) NOT NULL,
        old_content MEDIUMTEXT,
        new_content MEDIUMTEXT,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        permission_level INT NOT NULL DEFAULT 3,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        confirmed_at DATETIME NULL,
        reverted_at DATETIME NULL,
        INDEX idx_changes_session (session_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """

    # ---------- CRUD ----------

    @staticmethod
    def add(
        conn,
        session_id: int,
        file_path: str,
        operation: str,
        old_content: str,
        new_content: str,
        status: str,
        permission_level: int,
    ) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO file_changes "
                "(session_id, file_path, operation, old_content, new_content, status, permission_level) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (session_id, file_path, operation, old_content, new_content, status, permission_level),
            )
            return cur.lastrowid

    @staticmethod
    def get(conn, change_id: int) -> dict | None:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM file_changes WHERE id = %s", (change_id,))
            return cur.fetchone()

    @staticmethod
    def list_by_session(conn, session_id: int, status: str | None = None) -> list[dict]:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM file_changes WHERE session_id = %s AND status = %s "
                    "ORDER BY id ASC",
                    (session_id, status),
                )
            else:
                cur.execute(
                    "SELECT * FROM file_changes WHERE session_id = %s ORDER BY id ASC",
                    (session_id,),
                )
            return cur.fetchall()

    @staticmethod
    def update_status(conn, change_id: int, status: str, confirmed: bool = False, reverted: bool = False) -> None:
        """更新变更状态；confirmed/reverted 同时写入对应时间戳。"""
        with conn.cursor() as cur:
            if confirmed:
                cur.execute(
                    "UPDATE file_changes SET status = %s, confirmed_at = NOW() WHERE id = %s",
                    (status, change_id),
                )
            elif reverted:
                cur.execute(
                    "UPDATE file_changes SET status = %s, reverted_at = NOW() WHERE id = %s",
                    (status, change_id),
                )
            else:
                cur.execute("UPDATE file_changes SET status = %s WHERE id = %s", (status, change_id))
