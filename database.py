import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional, List, Tuple

DB_PATH = Path(__file__).parent / "victini_levels.db"


def init_db() -> None:
    """Inicializa la base de datos SQLite para el sistema de niveles de SNAP!"""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT 'Miembro',
                xp INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                last_xp_timestamp REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        cursor.execute("PRAGMA table_info(user_levels)")
        columns = [col[1] for col in cursor.fetchall()]
        if "username" not in columns:
            cursor.execute("ALTER TABLE user_levels ADD COLUMN username TEXT NOT NULL DEFAULT 'Miembro'")
        conn.commit()


def xp_for_next_level(level: int) -> int:
    """
    Calcula la experiencia necesaria para pasar del `level` actual al siguiente.
    Fórmula progresiva: 100 * (level ^ 1.5) redondeado.
    """
    return int(100 * (level ** 1.5))


def add_xp(
    guild_id: int,
    user_id: int,
    amount: int,
    now_ts: float,
    username: str = "Miembro",
    cooldown: int = 45,
    update_timestamp: bool = True,
) -> Tuple[bool, int, int, bool]:
    """
    Suma XP a un usuario respetando el cooldown anti-spam (cuando cooldown > 0).
    Retorna: (subio_de_nivel, nuevo_nivel, xp_actual, xp_aplicada)
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT xp, level, last_xp_timestamp FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()

        if row is None:
            xp, level, last_ts = 0, 1, 0.0
            cursor.execute(
                """
                INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, username, 0, 1, 0.0),
            )
        else:
            xp, level, last_ts = row

        # Verificar cooldown anti-spam (si cooldown > 0)
        if cooldown > 0 and (now_ts - last_ts < cooldown):
            return False, level, xp, False

        xp += amount
        leveled_up = False

        while xp >= xp_for_next_level(level):
            xp -= xp_for_next_level(level)
            level += 1
            leveled_up = True

        new_ts = now_ts if update_timestamp else last_ts
        cursor.execute(
            """
            UPDATE user_levels
            SET username = ?, xp = ?, level = ?, last_xp_timestamp = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (username, xp, level, new_ts, guild_id, user_id),
        )
        conn.commit()
        return leveled_up, level, xp, True


def get_user_stats(guild_id: int, user_id: int) -> Tuple[int, int, Optional[int]]:
    """
    Obtiene (level, xp, rank_position) de un usuario en el servidor.
    rank_position es 1-indexed (1 = primer lugar).
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT level, xp FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            level, xp = 1, 0
        else:
            level, xp = row

        cursor.execute(
            """
            SELECT COUNT(*) + 1
            FROM user_levels
            WHERE guild_id = ?
              AND (level > ? OR (level = ? AND xp > ?))
            """,
            (guild_id, level, level, xp),
        )
        rank = cursor.fetchone()[0]
        return level, xp, rank


def get_leaderboard(guild_id: int, limit: int = 10, offset: int = 0) -> Tuple[List[Tuple[int, str, int, int]], int]:
    """
    Retorna una lista de (user_id, username, level, xp) ordenada por nivel y XP descendente,
    junto con el total de usuarios registrados en el ranking del servidor.
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_levels WHERE guild_id = ?",
            (guild_id,),
        )
        total_users = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT user_id, username, level, xp
            FROM user_levels
            WHERE guild_id = ?
            ORDER BY level DESC, xp DESC, user_id ASC
            LIMIT ? OFFSET ?
            """,
            (guild_id, limit, offset),
        )
        rows = cursor.fetchall()
        return rows, total_users


def get_global_web_leaderboard(limit: int = 25) -> List[dict]:
    """
    Retorna el ranking en formato diccionario para mostrar en la WebApp de SNAP! en Render.
    """
    init_db()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT username, level, xp
            FROM user_levels
            ORDER BY level DESC, xp DESC, user_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        result = []
        for idx, (username, level, xp) in enumerate(rows, start=1):
            result.append(
                {
                    "rank": idx,
                    "username": username,
                    "level": level,
                    "xp": xp,
                    "next_xp": xp_for_next_level(level),
                }
            )
        return result


def export_guild_levels(guild_id: int) -> List[dict]:
    """Exporta todos los niveles y experiencia del servidor para respaldo persistente."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id, username, level, xp
            FROM user_levels
            WHERE guild_id = ?
            ORDER BY level DESC, xp DESC
            """,
            (guild_id,),
        )
        return [
            {"user_id": uid, "username": uname, "level": lvl, "xp": xp}
            for uid, uname, lvl, xp in cursor.fetchall()
        ]


def import_guild_levels(guild_id: int, records: List[dict]) -> int:
    """
    Restaura los niveles y experiencia desde el respaldo sin sobreescribir datos más avanzados.
    Retorna la cantidad de usuarios restaurados/actualizados.
    """
    if not records:
        return 0
    restored = 0
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        for rec in records:
            uid = int(rec["user_id"])
            uname = str(rec.get("username") or "Miembro")
            lvl = int(rec.get("level") or 1)
            xp = int(rec.get("xp") or 0)

            cursor.execute(
                "SELECT level, xp FROM user_levels WHERE guild_id = ? AND user_id = ?",
                (guild_id, uid),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (guild_id, uid, uname, xp, lvl),
                )
                restored += 1
            elif lvl > existing[0] or (lvl == existing[0] and xp > existing[1]):
                cursor.execute(
                    """
                    UPDATE user_levels
                    SET username = ?, level = ?, xp = ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (uname, lvl, xp, guild_id, uid),
                )
                restored += 1
        conn.commit()
    return restored
