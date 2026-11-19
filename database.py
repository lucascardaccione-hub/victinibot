import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional, List, Tuple

DB_PATH = Path(__file__).parent / "victini_levels.db"


def init_db() -> None:
    """Inicializa la base de datos SQLite para niveles, Pokéballs y equipos Pokémon de SNAP!"""
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
                pokeballs INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        # Migración suave de columnas en user_levels
        cursor.execute("PRAGMA table_info(user_levels)")
        columns = [col[1] for col in cursor.fetchall()]
        if "username" not in columns:
            cursor.execute("ALTER TABLE user_levels ADD COLUMN username TEXT NOT NULL DEFAULT 'Miembro'")
        if "pokeballs" not in columns:
            cursor.execute("ALTER TABLE user_levels ADD COLUMN pokeballs INTEGER NOT NULL DEFAULT 0")

        # Tabla de equipos Pokémon (máximo 6 por usuario en cada servidor)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_pokemon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                pokedex_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                rarity TEXT NOT NULL,
                ptype TEXT NOT NULL,
                is_shiny INTEGER NOT NULL DEFAULT 0,
                caught_at REAL NOT NULL DEFAULT 0
            )
            """
        )
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
    Por cada nivel que sube, otorga +1 Pokéball automáticamente.
    Retorna: (subio_de_nivel, nuevo_nivel, xp_actual, xp_aplicada)
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT xp, level, last_xp_timestamp, pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()

        if row is None:
            xp, level, last_ts, pokeballs = 0, 1, 0.0, 0
            cursor.execute(
                """
                INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, username, 0, 1, 0.0, 0),
            )
        else:
            xp, level, last_ts, pokeballs = row

        if cooldown > 0 and (now_ts - last_ts < cooldown):
            return False, level, xp, False

        xp += amount
        leveled_up = False
        levels_gained = 0

        while xp >= xp_for_next_level(level):
            xp -= xp_for_next_level(level)
            level += 1
            levels_gained += 1
            leveled_up = True

        pokeballs += levels_gained
        new_ts = now_ts if update_timestamp else last_ts
        cursor.execute(
            """
            UPDATE user_levels
            SET username = ?, xp = ?, level = ?, last_xp_timestamp = ?, pokeballs = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (username, xp, level, new_ts, pokeballs, guild_id, user_id),
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


def get_pokeballs(guild_id: int, user_id: int) -> int:
    """Retorna la cantidad de Pokéballs disponibles que tiene el usuario."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def consume_pokeball(guild_id: int, user_id: int) -> Tuple[bool, int]:
    """
    Descuenta 1 Pokéball al usuario si tiene al menos 1.
    Retorna (exito, pokeballs_restantes).
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        current = int(row[0]) if row else 0
        if current <= 0:
            return False, 0

        remaining = current - 1
        cursor.execute(
            "UPDATE user_levels SET pokeballs = ? WHERE guild_id = ? AND user_id = ?",
            (remaining, guild_id, user_id),
        )
        conn.commit()
        return True, remaining


def get_pokemon_team(guild_id: int, user_id: int) -> List[dict]:
    """Retorna la lista de Pokémon (máximo 6) en el equipo del usuario."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, pokedex_id, name, rarity, ptype, is_shiny, caught_at
            FROM user_pokemon
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id ASC
            """,
            (guild_id, user_id),
        )
        return [
            {
                "id": r[0],
                "pokedex_id": r[1],
                "name": r[2],
                "rarity": r[3],
                "ptype": r[4],
                "is_shiny": bool(r[5]),
                "caught_at": r[6],
            }
            for r in cursor.fetchall()
        ]


def add_pokemon_to_team(
    guild_id: int,
    user_id: int,
    pokedex_id: int,
    name: str,
    rarity: str,
    ptype: str,
    is_shiny: bool,
    caught_at: float,
) -> bool:
    """Agrega un Pokémon al equipo si hay espacio (< 6)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_pokemon WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        count = cursor.fetchone()[0]
        if count >= 6:
            return False
        cursor.execute(
            """
            INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, pokedex_id, name, rarity, ptype, 1 if is_shiny else 0, caught_at),
        )
        conn.commit()
        return True


def replace_pokemon_in_team(
    guild_id: int,
    user_id: int,
    release_row_id: int,
    pokedex_id: int,
    name: str,
    rarity: str,
    ptype: str,
    is_shiny: bool,
    caught_at: float,
) -> bool:
    """Libera el Pokémon indicado (`release_row_id`) y añade el nuevo al equipo."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM user_pokemon WHERE id = ? AND guild_id = ? AND user_id = ?",
            (release_row_id, guild_id, user_id),
        )
        if cursor.rowcount == 0:
            return False
        cursor.execute(
            """
            INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, pokedex_id, name, rarity, ptype, 1 if is_shiny else 0, caught_at),
        )
        conn.commit()
        return True


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


def export_guild_levels(guild_id: int) -> dict:
    """Exporta niveles, Pokéballs y equipos Pokémon del servidor para respaldo persistente."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT user_id, username, level, xp, pokeballs
            FROM user_levels
            WHERE guild_id = ?
            ORDER BY level DESC, xp DESC
            """,
            (guild_id,),
        )
        levels = [
            {
                "user_id": uid,
                "username": uname,
                "level": lvl,
                "xp": xp,
                "pokeballs": balls,
            }
            for uid, uname, lvl, xp, balls in cursor.fetchall()
        ]

        cursor.execute(
            """
            SELECT user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at
            FROM user_pokemon
            WHERE guild_id = ?
            ORDER BY id ASC
            """,
            (guild_id,),
        )
        teams = [
            {
                "user_id": r[0],
                "pokedex_id": r[1],
                "name": r[2],
                "rarity": r[3],
                "ptype": r[4],
                "is_shiny": r[5],
                "caught_at": r[6],
            }
            for r in cursor.fetchall()
        ]
        return {"levels": levels, "teams": teams}


def import_guild_levels(guild_id: int, payload) -> int:
    """
    Restaura niveles, Pokéballs y equipos Pokémon desde el respaldo sin sobreescribir datos más avanzados.
    Acepta tanto el formato nuevo {'levels': [...], 'teams': [...]} como el formato lista anterior.
    """
    if not payload:
        return 0

    if isinstance(payload, list):
        level_records = payload
        team_records = []
    else:
        level_records = payload.get("levels") or []
        team_records = payload.get("teams") or []

    restored = 0
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cursor = conn.cursor()
        for rec in level_records:
            uid = int(rec["user_id"])
            uname = str(rec.get("username") or "Miembro")
            lvl = int(rec.get("level") or 1)
            xp = int(rec.get("xp") or 0)
            balls = int(rec.get("pokeballs") if "pokeballs" in rec else max(0, lvl - 1))

            cursor.execute(
                "SELECT level, xp FROM user_levels WHERE guild_id = ? AND user_id = ?",
                (guild_id, uid),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    """
                    INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (guild_id, uid, uname, xp, lvl, balls),
                )
                restored += 1
            elif lvl > existing[0] or (lvl == existing[0] and xp > existing[1]):
                cursor.execute(
                    """
                    UPDATE user_levels
                    SET username = ?, level = ?, xp = ?, pokeballs = ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (uname, lvl, xp, balls, guild_id, uid),
                )
                restored += 1

        # Restaurar equipos Pokémon por usuario si ese usuario no tiene equipo cargado aún localmente
        teams_by_user: dict[int, List[dict]] = {}
        for t in team_records:
            teams_by_user.setdefault(int(t["user_id"]), []).append(t)

        for uid, mons in teams_by_user.items():
            cursor.execute(
                "SELECT COUNT(*) FROM user_pokemon WHERE guild_id = ? AND user_id = ?",
                (guild_id, uid),
            )
            if cursor.fetchone()[0] == 0:
                for m in mons[:6]:
                    cursor.execute(
                        """
                        INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            guild_id,
                            uid,
                            int(m["pokedex_id"]),
                            str(m["name"]),
                            str(m["rarity"]),
                            str(m["ptype"]),
                            int(m.get("is_shiny") or 0),
                            float(m.get("caught_at") or 0),
                        ),
                    )
        conn.commit()
    return restored
