import os
import sqlite3
import urllib.parse
from contextlib import closing
from pathlib import Path
from typing import Optional, List, Tuple

DB_PATH = Path(__file__).parent / "victini_levels.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))


def _get_conn():
    """Abre conexión a PostgreSQL (si DATABASE_URL está configurado en Render) o SQLite local."""
    if USE_POSTGRES:
        import pg8000.dbapi
        parsed = urllib.parse.urlparse(DATABASE_URL)
        use_ssl = "sslmode=disable" not in DATABASE_URL and parsed.hostname not in ("localhost", "127.0.0.1")
        ssl_ctx = None
        if use_ssl:
            import ssl
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        return pg8000.dbapi.connect(
            user=urllib.parse.unquote(parsed.username or ""),
            password=urllib.parse.unquote(parsed.password or ""),
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            database=(parsed.path or "").lstrip("/"),
            ssl_context=ssl_ctx,
        )
    return sqlite3.connect(DB_PATH)


def _sql(query: str) -> str:
    """Adapta placeholders `?` a `%s` cuando se usa PostgreSQL."""
    if USE_POSTGRES:
        return query.replace("?", "%s")
    return query


def init_db() -> None:
    """Inicializa las tablas de niveles, Pokéballs y equipos Pokémon en PostgreSQL o SQLite."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_levels (
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT NOT NULL DEFAULT 'Miembro',
                    xp INTEGER NOT NULL DEFAULT 0,
                    level INTEGER NOT NULL DEFAULT 1,
                    last_xp_timestamp DOUBLE PRECISION NOT NULL DEFAULT 0,
                    pokeballs INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_pokemon (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    pokedex_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    ptype TEXT NOT NULL,
                    is_shiny INTEGER NOT NULL DEFAULT 0,
                    caught_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                    poke_level INTEGER NOT NULL DEFAULT 1,
                    poke_xp INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute("ALTER TABLE user_pokemon ADD COLUMN IF NOT EXISTS poke_level INTEGER NOT NULL DEFAULT 1")
            cursor.execute("ALTER TABLE user_pokemon ADD COLUMN IF NOT EXISTS poke_xp INTEGER NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE user_levels ADD COLUMN IF NOT EXISTS gym_badges INTEGER NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE user_levels ADD COLUMN IF NOT EXISTS league_stage INTEGER NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE user_levels ADD COLUMN IF NOT EXISTS league_wins INTEGER NOT NULL DEFAULT 0")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tcg_cards (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    card_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    set_name TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    pulled_at DOUBLE PRECISION NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
        else:
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
            cursor.execute("PRAGMA table_info(user_levels)")
            columns = [col[1] for col in cursor.fetchall()]
            if "username" not in columns:
                cursor.execute("ALTER TABLE user_levels ADD COLUMN username TEXT NOT NULL DEFAULT 'Miembro'")
            if "pokeballs" not in columns:
                cursor.execute("ALTER TABLE user_levels ADD COLUMN pokeballs INTEGER NOT NULL DEFAULT 0")
            if "gym_badges" not in columns:
                cursor.execute("ALTER TABLE user_levels ADD COLUMN gym_badges INTEGER NOT NULL DEFAULT 0")
            if "league_stage" not in columns:
                cursor.execute("ALTER TABLE user_levels ADD COLUMN league_stage INTEGER NOT NULL DEFAULT 0")
            if "league_wins" not in columns:
                cursor.execute("ALTER TABLE user_levels ADD COLUMN league_wins INTEGER NOT NULL DEFAULT 0")

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
                    caught_at REAL NOT NULL DEFAULT 0,
                    poke_level INTEGER NOT NULL DEFAULT 1,
                    poke_xp INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute("PRAGMA table_info(user_pokemon)")
            p_cols = [col[1] for col in cursor.fetchall()]
            if "poke_level" not in p_cols:
                cursor.execute("ALTER TABLE user_pokemon ADD COLUMN poke_level INTEGER NOT NULL DEFAULT 1")
            if "poke_xp" not in p_cols:
                cursor.execute("ALTER TABLE user_pokemon ADD COLUMN poke_xp INTEGER NOT NULL DEFAULT 0")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_tcg_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    card_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    set_name TEXT NOT NULL,
                    rarity TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    pulled_at REAL NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
        conn.commit()


def get_bot_state(key: str) -> Optional[str]:
    """Obtiene un valor persistente de configuración/estado (ej. último video de YouTube anunciado)."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(_sql("SELECT value FROM bot_state WHERE key = ?"), (key,))
        row = cursor.fetchone()
        return str(row[0]) if row else None


def set_bot_state(key: str, value: str) -> None:
    """Guarda o actualiza un valor persistente de estado en PostgreSQL o SQLite."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(_sql("SELECT key FROM bot_state WHERE key = ?"), (key,))
        if cursor.fetchone() is None:
            cursor.execute(
                _sql("INSERT INTO bot_state (key, value) VALUES (?, ?)"),
                (key, str(value)),
            )
        else:
            cursor.execute(
                _sql("UPDATE bot_state SET value = ? WHERE key = ?"),
                (str(value), key),
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
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT xp, level, last_xp_timestamp, pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        row = cursor.fetchone()

        if row is None:
            xp, level, last_ts, pokeballs = 0, 1, 0.0, 0
            cursor.execute(
                _sql(
                    """
                    INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                ),
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
            _sql(
                """
                UPDATE user_levels
                SET username = ?, xp = ?, level = ?, last_xp_timestamp = ?, pokeballs = ?
                WHERE guild_id = ? AND user_id = ?
                """
            ),
            (username, xp, level, new_ts, pokeballs, guild_id, user_id),
        )
        conn.commit()
        return leveled_up, level, xp, True


def get_user_stats(guild_id: int, user_id: int) -> Tuple[int, int, Optional[int]]:
    """
    Obtiene (level, xp, rank_position) de un usuario en el servidor.
    rank_position es 1-indexed (1 = primer lugar).
    """
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT level, xp FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            level, xp = 1, 0
        else:
            level, xp = row

        cursor.execute(
            _sql(
                """
                SELECT COUNT(*) + 1
                FROM user_levels
                WHERE guild_id = ?
                  AND (level > ? OR (level = ? AND xp > ?))
                """
            ),
            (guild_id, level, level, xp),
        )
        rank = cursor.fetchone()[0]
        return level, xp, rank


def get_pokeballs(guild_id: int, user_id: int) -> int:
    """Retorna la cantidad de Pokéballs disponibles que tiene el usuario."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def consume_pokeball(guild_id: int, user_id: int) -> Tuple[bool, int]:
    """
    Descuenta 1 Pokéball al usuario si tiene al menos 1.
    Retorna (exito, pokeballs_restantes).
    """
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        current = int(row[0]) if row else 0
        if current <= 0:
            return False, 0

        remaining = current - 1
        cursor.execute(
            _sql("UPDATE user_levels SET pokeballs = ? WHERE guild_id = ? AND user_id = ?"),
            (remaining, guild_id, user_id),
        )
        conn.commit()
        return True, remaining


def add_pokeballs(guild_id: int, user_id: int, amount: int, username: str = "Miembro") -> int:
    """Suma `amount` Pokéballs al usuario (crea la fila si no existe). Retorna el nuevo total."""
    if amount <= 0:
        return get_pokeballs(guild_id, user_id)

    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT pokeballs FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            new_total = amount
            cursor.execute(
                _sql(
                    """
                    INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs)
                    VALUES (?, ?, ?, 0, 1, 0, ?)
                    """
                ),
                (guild_id, user_id, username, new_total),
            )
        else:
            new_total = int(row[0]) + amount
            cursor.execute(
                _sql("UPDATE user_levels SET pokeballs = ? WHERE guild_id = ? AND user_id = ?"),
                (new_total, guild_id, user_id),
            )
        conn.commit()
        return new_total


def get_trainer_progress(guild_id: int, user_id: int) -> dict:
    """Retorna el progreso de Medallas de Gimnasio y Liga Pokémon del usuario."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                "SELECT gym_badges, league_stage, league_wins FROM user_levels WHERE guild_id = ? AND user_id = ?"
            ),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return {"gym_badges": 0, "league_stage": 0, "league_wins": 0}
        return {
            "gym_badges": int(row[0] or 0),
            "league_stage": int(row[1] or 0),
            "league_wins": int(row[2] or 0),
        }


def update_trainer_progress(
    guild_id: int,
    user_id: int,
    gym_badges: Optional[int] = None,
    league_stage: Optional[int] = None,
    league_wins: Optional[int] = None,
    username: str = "Miembro",
) -> dict:
    """Actualiza el progreso de Medallas de Gimnasio y Liga Pokémon del usuario."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                "SELECT gym_badges, league_stage, league_wins FROM user_levels WHERE guild_id = ? AND user_id = ?"
            ),
            (guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            cur_badges, cur_stage, cur_wins = 0, 0, 0
            cursor.execute(
                _sql(
                    """
                    INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs, gym_badges, league_stage, league_wins)
                    VALUES (?, ?, ?, 0, 1, 0, 0, 0, 0, 0)
                    """
                ),
                (guild_id, user_id, username),
            )
        else:
            cur_badges = int(row[0] or 0)
            cur_stage = int(row[1] or 0)
            cur_wins = int(row[2] or 0)

        new_badges = cur_badges if gym_badges is None else gym_badges
        new_stage = cur_stage if league_stage is None else league_stage
        new_wins = cur_wins if league_wins is None else league_wins

        cursor.execute(
            _sql(
                """
                UPDATE user_levels
                SET gym_badges = ?, league_stage = ?, league_wins = ?
                WHERE guild_id = ? AND user_id = ?
                """
            ),
            (new_badges, new_stage, new_wins, guild_id, user_id),
        )
        conn.commit()
        return {
            "gym_badges": new_badges,
            "league_stage": new_stage,
            "league_wins": new_wins,
        }


def get_pokemon_team(guild_id: int, user_id: int) -> List[dict]:
    """Retorna la lista de Pokémon (máximo 6) en el equipo del usuario con su nivel y XP."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                """
                SELECT id, pokedex_id, name, rarity, ptype, is_shiny, caught_at, poke_level, poke_xp
                FROM user_pokemon
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id ASC
                """
            ),
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
                "poke_level": int(r[7] if r[7] is not None else 1),
                "poke_xp": int(r[8] if r[8] is not None else 0),
            }
            for r in cursor.fetchall()
        ]


def poke_xp_for_next_level(poke_level: int) -> int:
    """Experiencia necesaria para que un Pokémon suba al siguiente nivel."""
    return 40 * max(1, poke_level)


def add_pokemon_xp(
    row_id: int,
    guild_id: int,
    user_id: int,
    xp_gain: int,
    evolution_table: Optional[dict] = None,
) -> Optional[dict]:
    """
    Suma XP a un Pokémon del equipo tras un combate, sube su nivel si corresponde
    y verifica si alcanza el nivel necesario para evolucionar (incluso múltiples etapas).
    Retorna un dict con el resultado o None si no existe.
    """
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                """
                SELECT pokedex_id, name, rarity, ptype, is_shiny, poke_level, poke_xp
                FROM user_pokemon
                WHERE id = ? AND guild_id = ? AND user_id = ?
                """
            ),
            (row_id, guild_id, user_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        pid, name, rarity, ptype, is_shiny, p_level, p_xp = row
        old_level = int(p_level or 1)
        p_level = old_level
        p_xp = int(p_xp or 0) + xp_gain

        while p_xp >= poke_xp_for_next_level(p_level):
            p_xp -= poke_xp_for_next_level(p_level)
            p_level += 1

        old_name = name
        evolved = False
        if evolution_table:
            while pid in evolution_table:
                evo = evolution_table[pid]
                if p_level >= evo["min_level"]:
                    pid = evo["to_id"]
                    name = evo["to_name"]
                    ptype = evo["to_type"]
                    if evo.get("to_rarity"):
                        rarity = evo["to_rarity"]
                    evolved = True
                else:
                    break

        cursor.execute(
            _sql(
                """
                UPDATE user_pokemon
                SET pokedex_id = ?, name = ?, rarity = ?, ptype = ?, poke_level = ?, poke_xp = ?
                WHERE id = ? AND guild_id = ? AND user_id = ?
                """
            ),
            (pid, name, rarity, ptype, p_level, p_xp, row_id, guild_id, user_id),
        )
        conn.commit()
        return {
            "id": row_id,
            "pokedex_id": pid,
            "name": name,
            "old_name": old_name,
            "rarity": rarity,
            "ptype": ptype,
            "is_shiny": bool(is_shiny),
            "old_level": old_level,
            "new_level": p_level,
            "new_xp": p_xp,
            "next_xp": poke_xp_for_next_level(p_level),
            "leveled_up": p_level > old_level,
            "evolved": evolved,
        }


def add_pokemon_to_team(
    guild_id: int,
    user_id: int,
    pokedex_id: int,
    name: str,
    rarity: str,
    ptype: str,
    is_shiny: bool,
    caught_at: float,
    poke_level: int = 1,
) -> bool:
    """Agrega un Pokémon al equipo si hay espacio (< 6) conservando su nivel de captura."""
    lvl = max(1, int(poke_level))
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT COUNT(*) FROM user_pokemon WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        count = cursor.fetchone()[0]
        if count >= 6:
            return False
        cursor.execute(
            _sql(
                """
                INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at, poke_level, poke_xp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """
            ),
            (guild_id, user_id, pokedex_id, name, rarity, ptype, 1 if is_shiny else 0, caught_at, lvl),
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
    poke_level: int = 1,
) -> bool:
    """Libera el Pokémon indicado (`release_row_id`) y añade el nuevo al equipo con su nivel de captura."""
    lvl = max(1, int(poke_level))
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("DELETE FROM user_pokemon WHERE id = ? AND guild_id = ? AND user_id = ?"),
            (release_row_id, guild_id, user_id),
        )
        if cursor.rowcount == 0:
            return False
        cursor.execute(
            _sql(
                """
                INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at, poke_level, poke_xp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """
            ),
            (guild_id, user_id, pokedex_id, name, rarity, ptype, 1 if is_shiny else 0, caught_at, lvl),
        )
        conn.commit()
        return True


def get_leaderboard(guild_id: int, limit: int = 10, offset: int = 0) -> Tuple[List[Tuple[int, str, int, int]], int]:
    """
    Retorna una lista de (user_id, username, level, xp) ordenada por nivel y XP descendente,
    junto con el total de usuarios registrados en el ranking del servidor.
    """
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT COUNT(*) FROM user_levels WHERE guild_id = ?"),
            (guild_id,),
        )
        total_users = cursor.fetchone()[0]

        cursor.execute(
            _sql(
                """
                SELECT user_id, username, level, xp
                FROM user_levels
                WHERE guild_id = ?
                ORDER BY level DESC, xp DESC, user_id ASC
                LIMIT ? OFFSET ?
                """
            ),
            (guild_id, limit, offset),
        )
        rows = cursor.fetchall()
        return rows, total_users


def get_global_web_leaderboard(limit: int = 50) -> List[dict]:
    """
    Retorna el ranking en formato diccionario para mostrar en la WebApp de SNAP! en Render,
    incluyendo nivel, XP, Pokéballs y el equipo Pokémon de cada jugador.
    """
    init_db()
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                """
                SELECT guild_id, user_id, username, level, xp, pokeballs
                FROM user_levels
                ORDER BY level DESC, xp DESC, user_id ASC
                LIMIT ?
                """
            ),
            (limit,),
        )
        rows = cursor.fetchall()

        cursor.execute(
            _sql(
                """
                SELECT guild_id, user_id, pokedex_id, name, rarity, is_shiny, poke_level
                FROM user_pokemon
                ORDER BY id ASC
                """
            )
        )
        teams_map: dict[tuple[int, int], List[dict]] = {}
        for gid, uid, pid, pname, rarity, is_shiny, p_level in cursor.fetchall():
            teams_map.setdefault((gid, uid), []).append(
                {
                    "pokedex_id": pid,
                    "name": pname,
                    "rarity": rarity,
                    "is_shiny": bool(is_shiny),
                    "poke_level": int(p_level if p_level is not None else 1),
                }
            )

        cursor.execute(
            _sql(
                """
                SELECT guild_id, user_id, COUNT(*), COUNT(DISTINCT card_id)
                FROM user_tcg_cards
                GROUP BY guild_id, user_id
                """
            )
        )
        tcg_counts_map: dict[tuple[int, int], tuple[int, int]] = {}
        for gid, uid, total_c, uniq_c in cursor.fetchall():
            tcg_counts_map[(gid, uid)] = (int(total_c), int(uniq_c))

        result = []
        for idx, (gid, uid, username, level, xp, pokeballs) in enumerate(rows, start=1):
            tcg_total, tcg_unique = tcg_counts_map.get((gid, uid), (0, 0))
            result.append(
                {
                    "rank": idx,
                    "guild_id": str(gid),
                    "user_id": str(uid),
                    "username": username,
                    "level": level,
                    "xp": xp,
                    "next_xp": xp_for_next_level(level),
                    "pokeballs": pokeballs,
                    "team": teams_map.get((gid, uid), [])[:6],
                    "tcg_total": tcg_total,
                    "tcg_unique": tcg_unique,
                }
            )
        return result


TCG_RARITY_ORDER = {
    "Secreta / SIR": 6,
    "Ilustración Rara": 5,
    "Ultra Rara": 4,
    "Rara": 3,
    "Infrecuente": 2,
    "Común": 1,
}


def add_tcg_cards(guild_id: int, user_id: int, cards: List[dict], pulled_at: float) -> int:
    """Guarda las cartas Pokémon TCG obtenidas en un Booster Pack en la colección del usuario."""
    if not cards:
        return 0
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        for c in cards:
            cursor.execute(
                _sql(
                    """
                    INSERT INTO user_tcg_cards (guild_id, user_id, card_id, name, set_name, rarity, image_url, pulled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """
                ),
                (
                    guild_id,
                    user_id,
                    str(c["card_id"]),
                    str(c["name"]),
                    str(c["set_name"]),
                    str(c["rarity"]),
                    str(c["image_url"]),
                    float(pulled_at),
                ),
            )
        conn.commit()
    return len(cards)


def get_user_tcg_cards(guild_id: int, user_id: int) -> dict:
    """Retorna la colección de cartas Pokémon TCG de un entrenador agrupada por carta con cantidades."""
    init_db()
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql("SELECT username, level FROM user_levels WHERE guild_id = ? AND user_id = ?"),
            (guild_id, user_id),
        )
        u_row = cursor.fetchone()
        username = str(u_row[0]) if u_row else "Entrenador"
        level = int(u_row[1]) if u_row else 1

        cursor.execute(
            _sql(
                """
                SELECT card_id, name, set_name, rarity, image_url, COUNT(*) as qty, MAX(pulled_at) as last_pulled
                FROM user_tcg_cards
                WHERE guild_id = ? AND user_id = ?
                GROUP BY card_id, name, set_name, rarity, image_url
                """
            ),
            (guild_id, user_id),
        )
        raw_rows = cursor.fetchall()

        cards = [
            {
                "card_id": r[0],
                "name": r[1],
                "set_name": r[2],
                "rarity": r[3],
                "image_url": r[4],
                "qty": int(r[5]),
                "last_pulled": float(r[6] or 0),
            }
            for r in raw_rows
        ]
        cards.sort(
            key=lambda c: (-TCG_RARITY_ORDER.get(c["rarity"], 0), -c["qty"], c["name"])
        )
        total_cards = sum(c["qty"] for c in cards)
        return {
            "guild_id": str(guild_id),
            "user_id": str(user_id),
            "username": username,
            "level": level,
            "total_cards": total_cards,
            "unique_cards": len(cards),
            "cards": cards,
        }


def export_guild_levels(guild_id: int) -> dict:
    """Exporta niveles, Pokéballs y equipos Pokémon del servidor."""
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            _sql(
                """
                SELECT user_id, username, level, xp, pokeballs
                FROM user_levels
                WHERE guild_id = ?
                ORDER BY level DESC, xp DESC
                """
            ),
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
            _sql(
                """
                SELECT user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at
                FROM user_pokemon
                WHERE guild_id = ?
                ORDER BY id ASC
                """
            ),
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
    Importa niveles, Pokéballs y equipos Pokémon sin sobreescribir datos más avanzados.
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
    with closing(_get_conn()) as conn:
        cursor = conn.cursor()
        for rec in level_records:
            uid = int(rec["user_id"])
            uname = str(rec.get("username") or "Miembro")
            lvl = int(rec.get("level") or 1)
            xp = int(rec.get("xp") or 0)
            balls = int(rec.get("pokeballs") if "pokeballs" in rec else max(0, lvl - 1))

            cursor.execute(
                _sql("SELECT level, xp FROM user_levels WHERE guild_id = ? AND user_id = ?"),
                (guild_id, uid),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    _sql(
                        """
                        INSERT INTO user_levels (guild_id, user_id, username, xp, level, last_xp_timestamp, pokeballs)
                        VALUES (?, ?, ?, ?, ?, 0, ?)
                        """
                    ),
                    (guild_id, uid, uname, xp, lvl, balls),
                )
                restored += 1
            elif lvl > existing[0] or (lvl == existing[0] and xp > existing[1]):
                cursor.execute(
                    _sql(
                        """
                        UPDATE user_levels
                        SET username = ?, level = ?, xp = ?, pokeballs = ?
                        WHERE guild_id = ? AND user_id = ?
                        """
                    ),
                    (uname, lvl, xp, balls, guild_id, uid),
                )
                restored += 1

        teams_by_user: dict[int, List[dict]] = {}
        for t in team_records:
            teams_by_user.setdefault(int(t["user_id"]), []).append(t)

        for uid, mons in teams_by_user.items():
            cursor.execute(
                _sql("SELECT COUNT(*) FROM user_pokemon WHERE guild_id = ? AND user_id = ?"),
                (guild_id, uid),
            )
            if cursor.fetchone()[0] == 0:
                for m in mons[:6]:
                    cursor.execute(
                        _sql(
                            """
                            INSERT INTO user_pokemon (guild_id, user_id, pokedex_id, name, rarity, ptype, is_shiny, caught_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """
                        ),
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
