import asyncio
import io
import os
import re
import sys
import time
import json
import random
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from database import (
    init_db,
    add_xp,
    get_user_stats,
    get_pokeballs,
    get_leaderboard,
    xp_for_next_level,
    export_guild_levels,
    import_guild_levels,
    get_bot_state,
    set_bot_state,
    add_rare_candy,
)
from music import setup_music_commands
from pokemon_game import (
    setup_pokemon_commands,
    build_welcome_card_png,
    CATCH_CHANNEL_NAME,
    RareCandyGiftView,
)
from promo_cards import build_entreturnos_card_png, build_snap_card_png
from tcg_booster import BoosterPackView
from youtube_notifier import check_entreturnos_updates

# Forzar salida sin buffer en Render para que todos los print() aparezcan al instante en los Logs
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Nombres exactos de los canales del servidor SNAP!
WELCOME_CHANNEL_NAME = "🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺"
LEVEL_CHANNEL_NAME = "🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀"
UPDATES_CHANNEL_NAME = "🔥𝑽𝑰𝑪𝑻𝑰𝑵𝑰-𝑼𝑷𝑫𝑨𝑻𝑬𝑺🔥"
CHAT_GENERAL_CHANNEL_NAME = "🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳"
BACKUP_CHANNEL_NAME = "victini-db-backup"

# Zona horaria de Argentina (UTC-3)
ARG_TZ = timezone(timedelta(hours=-3))

# Configuración de experiencia por mensaje de texto y por minuto activo en voz
XP_MIN = 15
XP_MAX = 25
XP_COOLDOWN_SECONDS = 45  # Cooldown anti-spam en canales de texto

VOICE_XP_MIN = 10
VOICE_XP_MAX = 15
BACKUP_THROTTLE_SECONDS = 30.0


def get_latest_commit_time_str() -> str:
    """
    Obtiene la fecha y hora exacta del último commit en GitHub (lucascardaccione-hub/victinibot)
    convertida a hora de Argentina (UTC-3). Si falla la consulta, usa la hora actual del deploy.
    """
    try:
        commit_sha = os.environ.get("RENDER_GIT_COMMIT", "main")
        url = f"https://api.github.com/repos/lucascardaccione-hub/victinibot/commits/{commit_sha}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "VictiniBot-SNAP/1.0",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            iso_date = data["commit"]["committer"]["date"]
            dt_utc = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
            dt_arg = dt_utc.astimezone(ARG_TZ)
            return dt_arg.strftime("%d/%m/%Y %H:%M:%S (Hora ARG)")
    except Exception as e:
        print(f"⚠️ No se pudo consultar fecha de commit en GitHub API: {e}", flush=True)
        now_arg = datetime.now(ARG_TZ)
        return now_arg.strftime("%d/%m/%Y %H:%M:%S (Hora ARG)")


def normalize_channel_name(name: str) -> str:
    """Normaliza caracteres matemáticos/estilizados Unicode a ASCII básico para comparación segura."""
    return unicodedata.normalize("NFKC", name).lower().strip()


def clean_alnum(name: str) -> str:
    """Extrae solo letras y números ASCII tras normalizar Unicode (ignora emojis, guiones y espacios)."""
    norm = normalize_channel_name(name)
    return "".join(ch for ch in norm if ch.isascii() and ch.isalnum())


def find_target_channel(guild: discord.Guild, target_name: str) -> Optional[discord.TextChannel]:
    """
    Busca un canal de texto por:
    1. Nombre exacto (ej. '🔥𝑽𝑰𝑪𝑻𝑰𝑵𝑰-𝑼𝑷𝑫𝑨𝑻𝑬𝑺🔥')
    2. Nombre normalizado NFKC
    3. Letras alfanuméricas limpias (ej. 'victiniupdates')
    """
    for channel in guild.text_channels:
        if channel.name == target_name:
            return channel

    normalized_target = normalize_channel_name(target_name)
    for channel in guild.text_channels:
        if normalize_channel_name(channel.name) == normalized_target:
            return channel

    alnum_target = clean_alnum(target_name)
    if alnum_target:
        for channel in guild.text_channels:
            if clean_alnum(channel.name) == alnum_target:
                return channel

    return None


def is_snap_level_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    """Verifica que el canal donde se ejecutó el comando sea exclusivamente 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀."""
    if channel is None or not hasattr(channel, "name"):
        return False
    if channel.name == LEVEL_CHANNEL_NAME:
        return True
    if normalize_channel_name(channel.name) == normalize_channel_name(LEVEL_CHANNEL_NAME):
        return True
    return clean_alnum(channel.name) == clean_alnum(LEVEL_CHANNEL_NAME)


def is_chat_general_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    """Verifica que el canal donde se ejecutó el comando sea exclusivamente 🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳."""
    if channel is None or not hasattr(channel, "name"):
        return False
    if channel.name == CHAT_GENERAL_CHANNEL_NAME:
        return True
    if normalize_channel_name(channel.name) == normalize_channel_name(CHAT_GENERAL_CHANNEL_NAME):
        return True
    return clean_alnum(channel.name) == clean_alnum(CHAT_GENERAL_CHANNEL_NAME)


# ==========================================
# PERSISTENCIA EXTERNA SEGURA (CERO CANALES EN DISCORD)
# Soporta PostgreSQL (DATABASE_URL) o GitHub Gist privado (GITHUB_BACKUP_TOKEN + BACKUP_GIST_ID).
# Además, si quedó el canal antiguo `victini-db-backup`, migra sus datos y lo elimina automáticamente.
# ==========================================
_last_backup_ts: dict[int, float] = {}
_backup_locks: dict[int, asyncio.Lock] = {}


def _get_backup_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _backup_locks:
        _backup_locks[guild_id] = asyncio.Lock()
    return _backup_locks[guild_id]


async def cleanup_legacy_discord_backup_channel(guild: discord.Guild) -> None:
    """
    Si existe el canal antiguo `victini-db-backup`, recupera sus datos a la base actual
    y lo elimina automáticamente para mantener limpio el servidor Discord.
    """
    ch = discord.utils.get(guild.text_channels, name=BACKUP_CHANNEL_NAME)
    if ch is None:
        return

    try:
        async for msg in ch.history(limit=10):
            if msg.author.id != guild.me.id:
                continue
            if msg.attachments:
                for att in msg.attachments:
                    if att.filename.endswith(".json"):
                        raw = await att.read()
                        records = json.loads(raw.decode("utf-8"))
                        restored = import_guild_levels(guild.id, records)
                        print(
                            f"♻️ Migrados {restored} registros desde '{BACKUP_CHANNEL_NAME}' en '{guild.name}'.",
                            flush=True,
                        )
                        break
    except Exception as e:
        print(f"⚠️ Error leyendo '{BACKUP_CHANNEL_NAME}' antes de borrarlo: {e}", flush=True)

    try:
        await ch.delete(reason="Eliminando canal temporal de respaldo para mantener limpio el servidor SNAP!")
        print(f"🧹 Canal '{BACKUP_CHANNEL_NAME}' eliminado de '{guild.name}'.", flush=True)
    except Exception as e:
        print(f"⚠️ No se pudo eliminar '{BACKUP_CHANNEL_NAME}': {e}", flush=True)


async def restore_levels_from_external(guild: discord.Guild) -> None:
    """Restaura niveles desde GitHub Gist privado si está configurado (cuando no se usa PostgreSQL)."""
    gist_id = os.getenv("BACKUP_GIST_ID", "").strip()
    gh_token = os.getenv("GITHUB_BACKUP_TOKEN", "").strip()
    if not gist_id or not gh_token:
        return

    def _fetch_gist():
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers={
                "Authorization": f"Bearer {gh_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "VictiniBot-SNAP/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            files = data.get("files") or {}
            fname = f"victini_snap_{guild.id}.json"
            if fname in files and files[fname].get("content"):
                return json.loads(files[fname]["content"])
        return None

    try:
        payload = await asyncio.to_thread(_fetch_gist)
        if payload:
            restored = import_guild_levels(guild.id, payload)
            print(f"♻️ Respaldo externo restaurado para '{guild.name}': {restored} usuarios.", flush=True)
    except Exception as e:
        print(f"⚠️ No se pudo restaurar respaldo externo: {e}", flush=True)


async def sync_levels_backup(guild: discord.Guild, force: bool = False) -> None:
    """
    Si está configurado un GitHub Gist privado (GITHUB_BACKUP_TOKEN + BACKUP_GIST_ID),
    respalda allí de forma segura sin crear ningún canal en Discord.
    (Si se usa DATABASE_URL de PostgreSQL, los datos ya persisten directo en la nube).
    """
    gist_id = os.getenv("BACKUP_GIST_ID", "").strip()
    gh_token = os.getenv("GITHUB_BACKUP_TOKEN", "").strip()
    if not gist_id or not gh_token:
        return

    now = time.time()
    if not force and (now - _last_backup_ts.get(guild.id, 0.0) < BACKUP_THROTTLE_SECONDS):
        return

    async with _get_backup_lock(guild.id):
        now = time.time()
        if not force and (now - _last_backup_ts.get(guild.id, 0.0) < BACKUP_THROTTLE_SECONDS):
            return

        records = export_guild_levels(guild.id)
        if not (records.get("levels") or []) and not (records.get("teams") or []):
            return

        body = json.dumps(
            {
                "files": {
                    f"victini_snap_{guild.id}.json": {
                        "content": json.dumps(records, ensure_ascii=False, separators=(",", ":"))
                    }
                }
            }
        ).encode("utf-8")

        def _patch_gist():
            req = urllib.request.Request(
                f"https://api.github.com/gists/{gist_id}",
                data=body,
                method="PATCH",
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "User-Agent": "VictiniBot-SNAP/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status

        try:
            await asyncio.to_thread(_patch_gist)
            _last_backup_ts[guild.id] = time.time()
        except Exception as e:
            print(f"⚠️ Error guardando respaldo externo: {e}", flush=True)


async def notify_level_up(guild: discord.Guild, member: discord.Member, new_level: int) -> None:
    """Envía el aviso oficial de subida de nivel + Booster Pack Misterioso únicamente por 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀."""
    level_channel = find_target_channel(guild, LEVEL_CHANNEL_NAME)
    if level_channel is not None:
        pokeballs = get_pokeballs(guild.id, member.id)
        if new_level == 20:
            level_up_msg = (
                f"🎉🔥 **¡HITO DESBLOQUEADO, {member.mention}!** 🔥🎉\n"
                f"¡Llegaste al **Nivel 20** en **SNAP!** y *Victini te entrega un objeto legendario*: "
                f"🎒 **¡Desbloqueaste el *Repartir Experiencia* para utilizar en `CATCH`!**\n"
                f"*A partir de ahora, en cada combate (`/catch`, `/battle`, `/gymchallenge` y `/pokemonleague`), **todos tus Pokémon del equipo acumularán XP automáticamente**, no solo el que elijas para luchar!* ⚡✌️\n"
                f"🎱 ¡Además recibiste **+1 Pokéball**! *(Tenés **{pokeballs}** disponibles)*\n\n"
                f"🎁 **¡Y podés abrir un *Booster Pack Misterioso* de 10 cartas reales de Pokémon TCG!** 🎴✨"
            )
        elif new_level == 30:
            level_up_msg = (
                f"💻🔥 **¡HITO DESBLOQUEADO, {member.mention}!** 🔥💻\n"
                f"¡Llegaste al **Nivel 30** en **SNAP!** y *Victini te conecta con Bill*: "
                f"📦 **¡Desbloqueaste la *PC de Bill* para tener hasta 36 Pokémon en total!** *(6 en tu equipo activo + 30 guardados en tus cajas)*\n"
                f"*Usá `/pc` en `CATCH` para mover, guardar o liberar tus Pokémon.* ⚡✌️\n"
                f"🎱 ¡Además recibiste **+1 Pokéball**! *(Tenés **{pokeballs}** disponibles)*\n\n"
                f"🎁 **¡Y podés abrir un *Booster Pack Misterioso* de 10 cartas reales de Pokémon TCG!** 🎴✨"
            )
        else:
            level_up_msg = (
                f"🎉 {member.mention} ha subido al **nivel {new_level}**, *¡felicitaciones!* 🔥 "
                f"*Espero que haya sido de forma legal* 👀 o **mis llamas actuarán rápidamente con severas consecuencias** 😈\n"
                f"🎱 ¡Recibiste **+1 Pokéball**! *(Tenés **{pokeballs}** para usar en `/catch`)*\n\n"
                f"🎁 **¡Podés abrir un *Booster Pack Misterioso* de 10 cartas reales de Pokémon TCG!** 🎴✨"
            )
        view = BoosterPackView(
            guild_id=guild.id,
            author_id=member.id,
            author_name=member.display_name,
            new_level=new_level,
            on_backup=sync_levels_backup,
        )
        await level_channel.send(level_up_msg, view=view)
    else:
        print(
            f"⚠️ {member} subió a nivel {new_level}, pero no se encontró el canal '{LEVEL_CHANNEL_NAME}'.",
            flush=True,
        )


WEB_PORTAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://victini.onrender.com").rstrip("/")


def build_ranking_embed(
    guild: discord.Guild,
    page: int,
    per_page: int = 10,
) -> tuple[discord.Embed, int]:
    """
    Construye el Embed estilizado con negrita/cursiva y enlace a la tabla web de SNAP!
    Retorna (embed, total_users).
    """
    offset = page * per_page
    rows, total_users = get_leaderboard(guild.id, limit=per_page, offset=offset)

    title = "🏆 Ranking de Niveles - SNAP! 🔥"
    if page == 0:
        subtitle = (
            "Top 10 de la comunidad en **SNAP!** 🔥\n"
            f"🌐 *[Ver tabla completa, puntos y Pokémon en la Web]({WEB_PORTAL_URL})*"
        )
    else:
        start_pos = offset + 1
        end_pos = min(offset + per_page, total_users)
        subtitle = (
            f"Posiciones **#{start_pos}** a **#{end_pos}** de la comunidad **SNAP!** 🔥\n"
            f"🌐 *[Ver tabla completa, puntos y Pokémon en la Web]({WEB_PORTAL_URL})*"
        )

    embed = discord.Embed(
        title=title,
        description=subtitle,
        color=discord.Color.orange(),
    )

    if not rows:
        embed.add_field(
            name="📊 Tabla de Posiciones",
            value="*Todavía no hay miembros con experiencia registrada. ¡Empiecen a charlar!* 🔥",
            inline=False,
        )
        return embed, total_users

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = []

    for idx, (user_id, stored_username, level, xp) in enumerate(rows, start=offset + 1):
        member = guild.get_member(user_id)
        display_name = member.display_name if member else (stored_username or f"ID:{user_id}")
        if len(display_name) > 22:
            display_name = display_name[:21] + "…"

        pos_str = medals.get(idx, f"**#{idx}**")
        next_xp = xp_for_next_level(level)
        lines.append(
            f"{pos_str} **{display_name}** — **Nivel {level}** *(`{xp}/{next_xp}` XP)*"
        )

    embed.add_field(name="📊 Tabla de Posiciones", value="\n".join(lines), inline=False)

    total_pages = max(1, (total_users + per_page - 1) // per_page)
    embed.set_footer(
        text=f"Victini Bot • Mascota oficial de SNAP! • Página {page + 1}/{total_pages} ({total_users} miembros)"
    )
    return embed, total_users


class RankingPaginationView(discord.ui.View):
    """Vista interactiva con botón 'Ver más...', 'Anterior' y enlace a la Web de Victini."""

    def __init__(self, guild: discord.Guild, author_id: int, page: int = 0, per_page: int = 10):
        super().__init__(timeout=180)
        self.guild = guild
        self.author_id = author_id
        self.page = page
        self.per_page = per_page
        self.add_item(
            discord.ui.Button(
                label="🌐 Ver tabla y Pokémon",
                style=discord.ButtonStyle.link,
                url=WEB_PORTAL_URL,
            )
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        _, total_users = get_leaderboard(self.guild.id, limit=1, offset=0)
        max_page = max(0, (total_users - 1) // self.per_page)

        self.prev_button.disabled = self.page <= 0
        self.more_button.disabled = self.page >= max_page

    @discord.ui.button(label="⬅️ Anterior", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._update_buttons()
        embed, _ = build_ranking_embed(self.guild, page=self.page, per_page=self.per_page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Ver más... 🔥", style=discord.ButtonStyle.danger)
    async def more_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._update_buttons()
        embed, _ = build_ranking_embed(self.guild, page=self.page, per_page=self.per_page)
        await interaction.response.edit_message(embed=embed, view=self)


class VictiniBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True          # Necesario para detectar nuevos miembros (on_member_join)
        intents.message_content = True  # Necesario para procesar mensajes y otorgar XP
        intents.voice_states = True     # Necesario para música y XP por tiempo activo en canales de voz

        super().__init__(command_prefix="!", intents=intents)
        self._boot_notified = False

    async def setup_hook(self):
        init_db()
        setup_music_commands(self)
        setup_pokemon_commands(self, sync_levels_backup, find_target_channel, notify_level_up)
        print("🔥 Inicializando base de datos y árbol de comandos slash...", flush=True)

    async def on_ready(self):
        print(f"✅ Victini Bot conectado como {self.user} (ID: {self.user.id})", flush=True)
        if not self._boot_notified:
            self._boot_notified = True
            commit_time_str = get_latest_commit_time_str()

            for guild in self.guilds:
                # 1. Migrar y eliminar el canal antiguo `victini-db-backup` si existe + restaurar respaldo externo
                await cleanup_legacy_discord_backup_channel(guild)
                await restore_levels_from_external(guild)

                # 2. Limpiar comandos duplicados de servidor
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    print(
                        f"🧹 Comandos duplicados de servidor limpiados en '{guild.name}' ({guild.id})",
                        flush=True,
                    )
                except Exception as e:
                    print(f"⚠️ Error limpiando comandos de guild en {guild.name}: {e}", flush=True)

                # 3. Enviar aviso de actualización al canal "🔥𝑽𝑰𝑪𝑻𝑰𝑵𝑰-𝑼𝑷𝑫𝑨𝑻𝑬𝑺🔥"
                updates_channel = find_target_channel(guild, UPDATES_CHANNEL_NAME)
                if updates_channel is not None:
                    update_msg = (
                        "Estoy actualizado y online 🔥\n"
                        "Al servicio de SNAP!\n\n"
                        f"Horario último commit: {commit_time_str}"
                    )
                    try:
                        await updates_channel.send(update_msg)
                        print(f"📢 Aviso de actualización enviado a '{updates_channel.name}'.", flush=True)
                    except Exception as e:
                        print(f"⚠️ No se pudo enviar aviso a '{updates_channel.name}': {e}", flush=True)
                else:
                    print(
                        f"⚠️ No se encontró el canal '{UPDATES_CHANNEL_NAME}' en '{guild.name}'.",
                        flush=True,
                    )

            # 4. Sincronizar comandos globales
            try:
                await self.tree.sync()
                print(
                    "🔥 Comandos globales (/nivel, /ranking, /victiniplay, /victiniskip, /victinistop, /victinicola) sincronizados.",
                    flush=True,
                )
            except Exception as e:
                print(f"⚠️ Error en sync global: {e}", flush=True)

        # 5. Iniciar bucle de experiencia por tiempo activo en canales de voz (cada 60s)
        if not voice_xp_loop.is_running():
            voice_xp_loop.start()

        # 6. Iniciar bucle promocional en 🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳 (cada 12 horas)
        if not promo_loop.is_running():
            promo_loop.start()

        # 7. Iniciar monitor de YouTube (@EntreTurnosLIVE: directos y nuevos videos cada 3 min)
        if not youtube_notifier_loop.is_running():
            youtube_notifier_loop.start()

        # 8. Iniciar regalo diario de Rare Candy en 🎮𝑪𝑨𝑻𝑪𝑯
        if not daily_rare_candy_loop.is_running():
            daily_rare_candy_loop.start()

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="todo en SNAP! 👀🔥",
            )
        )


bot = VictiniBot()


# ==========================================
# 1. BIENVENIDA A NUEVOS MIEMBROS
# ==========================================
@bot.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    welcome_channel = find_target_channel(member.guild, WELCOME_CHANNEL_NAME)
    if welcome_channel is None:
        print(
            f"⚠️ No se encontró el canal '{WELCOME_CHANNEL_NAME}' en el servidor '{member.guild.name}'.",
            flush=True,
        )
        return

    welcome_msg = (
        f"🔥 **Bienvenido/a {member.mention}**, acá vas a poder hacer *muchas cosas* y conocer gente **muy copada**, "
        f"pero **no te pases de vivo/a** porque *estoy viendo todo* 👀"
    )

    avatar_bytes: Optional[bytes] = None
    try:
        avatar_bytes = await member.display_avatar.with_size(256).read()
    except Exception:
        pass

    try:
        png_bytes = await asyncio.to_thread(
            build_welcome_card_png,
            member.display_name,
            member.guild.member_count or 1,
            avatar_bytes,
        )
        welcome_file = discord.File(io.BytesIO(png_bytes), filename=f"bienvenida_{member.id}.png")
        await welcome_channel.send(content=welcome_msg, file=welcome_file)
    except Exception as e:
        print(f"⚠️ Error generando imagen de bienvenida: {e}", flush=True)
        await welcome_channel.send(welcome_msg)


# ==========================================
# 2A. INTERACCIÓN DE VICTINI EN EL CHAT + NIVELES EN TEXTO
# ==========================================
_last_chat_reply: dict[int, float] = {}

INSULT_WORDS = (
    "boludo", "boluda", "pelotudo", "pelotuda", "idiota", "tonto", "tonta",
    "estupido", "estupida", "forro", "forra", "gil", "bobo", "boba",
    "inutil", "mierda", "basura", "poronga", "puto", "puta", "concha",
    "mogolico", "mogolica", "salame", "tarado", "tarada", "imbecil",
    "cagon", "cagona", "feo", "horrible", "inservible", "chupala",
    "cagar", "hdp", "culiado", "culiada", "pajero", "pajera", "petizo", "petiso",
)

MOCKING_INSULT_REPLIES = [
    "Jajaja mirá quién habla, tremendo fantasma 👻😂. **Ubicate o te baneo, pancho** 🔥😈",
    "¿En serio me venís a bardear a mí que soy la mascota de SNAP!? JAJAJA qué atrevido 💀. **Ubicate o te baneo, pancho** 🔥😈",
    "Uff, cuidado con el teclado que se te va a gastar, crack 🤣. **Ubicate o te baneo, pancho** 🔥😈",
    "¿Todo bien en casa? Venís a picantearla con un Pokémon legendario 😂🔥. **Ubicate o te baneo, pancho** 🔥😈",
    "JAJAJA seguí hablando así y mis llamas te dejan en Nivel 0 👀😂. **Ubicate o te baneo, pancho** 🔥😈",
]

VICTINI_FRIENDLY_REPLIES = [
    "¡Acá estoy! 🔥✌️ Siempre vigilando que nadie se pase de vivo en **SNAP!** 👀",
    "¿Alguien me invocó? ✌️🔥 ¡Estoy al 100% al servicio de **SNAP!**",
    "¡Presente! 🔥 Si querés música usá `/victiniplay`, y si querés atrapar Pokémon pasate por `🎮𝑪𝑨𝑻𝑪𝑯` 👀",
    "¡Buenas! ✌️🔥 Recordá que cada nivel que subís te da **+1 Pokéball** para usar en `/catch` 🎱",
    "¿Qué onda? 👀🔥 Seguí charlando o activo en voz para subir en el `/ranking` de **SNAP!**",
]


def _normalize_plain(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _mentions_victini_name(text: str) -> bool:
    plain = _normalize_plain(text)
    return bool(re.search(r"v\W*i\W*c\W*t\W*i\W*n\W*i", plain))


def _contains_insult(text: str) -> bool:
    plain = _normalize_plain(text)
    tokens = re.findall(r"[a-z0-9]+", plain)
    for word in INSULT_WORDS:
        if word in tokens or (len(word) >= 5 and word in plain):
            return True
    return False


async def _maybe_reply_as_victini(message: discord.Message) -> None:
    if bot.user is None:
        return

    mentioned_bot = bot.user in message.mentions
    named_victini = _mentions_victini_name(message.content)
    replied_to_bot = False

    if message.reference and message.reference.message_id:
        ref_msg = message.reference.resolved
        if isinstance(ref_msg, discord.Message) and ref_msg.author.id == bot.user.id:
            replied_to_bot = True
        elif ref_msg is None:
            try:
                fetched = await message.channel.fetch_message(message.reference.message_id)
                if fetched.author.id == bot.user.id:
                    replied_to_bot = True
            except Exception:
                pass

    if not (mentioned_bot or named_victini or replied_to_bot):
        return

    now = time.time()
    if now - _last_chat_reply.get(message.channel.id, 0.0) < 4.0:
        return
    _last_chat_reply[message.channel.id] = now

    if _contains_insult(message.content):
        reply_text = random.choice(MOCKING_INSULT_REPLIES)
    else:
        plain = _normalize_plain(message.content)
        if any(g in plain for g in ("hola", "buenas", "buen dia", "buenas tardes", "buenas noches")):
            reply_text = f"¡Hola {message.author.mention}! 🔥✌️ Acá **Victini** vigilando todo en **SNAP!** 👀"
        elif any(g in plain for g in ("gracias", "crack", "idolo", "genio", "capo")):
            reply_text = f"¡De nada {message.author.mention}! 🔥✌️ Para eso está la mascota oficial de **SNAP!**"
        else:
            reply_text = random.choice(VICTINI_FRIENDLY_REPLIES)

    try:
        await message.reply(reply_text, mention_author=False)
    except Exception:
        pass


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    # 1. Interacción de Victini si lo arroban, le responden o dicen "Victini"
    await _maybe_reply_as_victini(message)

    # 2. Sumar XP únicamente por mensajes enviados en canales de texto (o hilos de canales de texto)
    is_text_channel = isinstance(message.channel, (discord.TextChannel, discord.Thread))
    if is_text_channel:
        xp_gained = random.randint(XP_MIN, XP_MAX)
        leveled_up, new_level, _, applied = add_xp(
            guild_id=message.guild.id,
            user_id=message.author.id,
            amount=xp_gained,
            now_ts=time.time(),
            username=message.author.display_name,
            cooldown=XP_COOLDOWN_SECONDS,
            update_timestamp=True,
        )

        if leveled_up and isinstance(message.author, discord.Member):
            await notify_level_up(message.guild, message.author, new_level)

        if applied:
            asyncio.create_task(sync_levels_backup(message.guild, force=leveled_up))

    await bot.process_commands(message)


# ==========================================
# 2B. SISTEMA DE NIVELES: TIEMPO ACTIVO EN CANALES DE VOZ
# (No suma si el usuario está muteado o ensordecido, aunque transmita pantalla)
# ==========================================
@tasks.loop(seconds=60)
async def voice_xp_loop():
    now_ts = time.time()
    for guild in bot.guilds:
        any_awarded = False
        any_leveled = False

        voice_channels = list(guild.voice_channels) + list(guild.stage_channels)
        for vc in voice_channels:
            # Ignorar canal AFK del servidor
            if guild.afk_channel and vc.id == guild.afk_channel.id:
                continue

            for member in vc.members:
                if member.bot:
                    continue

                vs = member.voice
                if vs is None:
                    continue

                # Regla estricta: NO computar si está muteado o ensordecido (propio o del servidor),
                # incluso si está transmitiendo pantalla (vs.self_stream)
                if vs.self_mute or vs.mute or vs.self_deaf or vs.deaf:
                    continue

                xp_gained = random.randint(VOICE_XP_MIN, VOICE_XP_MAX)
                leveled_up, new_level, _, applied = add_xp(
                    guild_id=guild.id,
                    user_id=member.id,
                    amount=xp_gained,
                    now_ts=now_ts,
                    username=member.display_name,
                    cooldown=0,
                    update_timestamp=False,
                )

                if applied:
                    any_awarded = True
                if leveled_up:
                    any_leveled = True
                    await notify_level_up(guild, member, new_level)

        if any_awarded:
            await sync_levels_backup(guild, force=any_leveled)


@voice_xp_loop.before_loop
async def before_voice_xp_loop():
    await bot.wait_until_ready()


# ==========================================
# 2C. CHIVOS AUTOMÁTICOS CADA 12 HORAS EN 🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳 Y COMANDO /chivo
# ==========================================
_promo_next_idx = 0


def build_promo_payload(choice_idx: Optional[int] = None) -> tuple[str, discord.File]:
    """Construye el texto con estilo Victini y la tarjeta PNG adjunta para Mensaje 1 (EntreTurnos) o Mensaje 2 (SNAP!)."""
    global _promo_next_idx
    if choice_idx in (0, 1):
        idx = choice_idx
    else:
        idx = _promo_next_idx % 2
        _promo_next_idx = (idx + 1) % 2

    if idx == 0:
        text = (
            "🔥 **¡Hey! Recuerden suscribirse al canal de *EntreTurnos* en YouTube** ✌️🎥\n"
            "*¡Prendete al mejor **Streaming de Pokémon TCG** con Victini!* ⚡🎴\n\n"
            "👉 https://www.youtube.com/@EntreTurnosLIVE"
        )
        png_bytes = build_entreturnos_card_png()
        return text, discord.File(io.BytesIO(png_bytes), filename="entreturnos_tcg.png")

    text = (
        "🃏 **¡Atención entrenadores de *SNAP!* 🔥✌️**\n"
        "*Podés comprarnos **cartón jugable y brillante** en **SNAP! Stock*** 🛒✨\n"
        "👉 https://catalogo.snap-stock.com/snap/catalogo\n\n"
        "*O también en **TCG Fans*** 🎴🔥\n"
        "👉 https://tcg.fans/pokemon/profile/SNAP%21/products\n\n"
        "📍 ***¡También estamos todos los Sábados en Lo de Charly (`Chaco 21`)!*** *¡Te esperamos!* 🙌"
    )
    png_bytes = build_snap_card_png()
    return text, discord.File(io.BytesIO(png_bytes), filename="snap_tcg.png")


@tasks.loop(hours=12)
async def promo_loop():
    # Evitar spamear inmediatamente al reiniciar/desplegar en Render; espera las primeras 12 horas
    if promo_loop.current_loop == 0:
        return

    for guild in bot.guilds:
        target_ch = find_target_channel(guild, CHAT_GENERAL_CHANNEL_NAME)
        if target_ch is None:
            continue
        try:
            text, card_file = await asyncio.to_thread(build_promo_payload, None)
            await target_ch.send(content=text, file=card_file)
            print(f"📢 Chivo automático enviado a '{target_ch.name}' en {guild.name}.", flush=True)
        except Exception as e:
            print(f"⚠️ Error enviando chivo automático en {guild.name}: {e}", flush=True)


@promo_loop.before_loop
async def before_promo_loop():
    await bot.wait_until_ready()


# ==========================================
# 2D. AVISOS AUTOMÁTICOS DE YOUTUBE (@EntreTurnosLIVE) EN 🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳
# ==========================================
@tasks.loop(minutes=3)
async def youtube_notifier_loop():
    events = await asyncio.to_thread(check_entreturnos_updates)
    if not events:
        return

    for guild in bot.guilds:
        target_ch = find_target_channel(guild, CHAT_GENERAL_CHANNEL_NAME)
        if target_ch is None:
            continue
        for ev in events:
            try:
                if ev["kind"] == "live":
                    msg = (
                        f"🔴 **¡`@EntreTurnosLIVE` ESTÁ EN VIVO AHORA MISMO!** 🔥🎥\n"
                        f"*¡Victini te avisa que arrancó el streaming! ¡Sumate ya!* ⚡✌️\n\n"
                        f"📺 **{ev['title']}**\n"
                        f"👉 {ev['url']}"
                    )
                else:
                    msg = (
                        f"🆕 **¡NUEVO CONTENIDO EN `@EntreTurnosLIVE`!** 🎬🔥\n"
                        f"*¡Victini detectó un nuevo video recién publicado en el canal!* 👀✌️\n\n"
                        f"📺 **{ev['title']}**\n"
                        f"👉 {ev['url']}"
                    )
                await target_ch.send(msg)
                print(
                    f"📺 Aviso de YouTube ({ev['kind']}) enviado a '{target_ch.name}' en {guild.name}: {ev['video_id']}",
                    flush=True,
                )
            except Exception as e:
                print(f"⚠️ Error enviando aviso de YouTube en {guild.name}: {e}", flush=True)


@youtube_notifier_loop.before_loop
async def before_youtube_notifier_loop():
    await bot.wait_until_ready()


# ==========================================
# 2E. REGALO DIARIO DE RARE CANDY EN 🎮𝑪𝑨𝑻𝑪𝑯
# ==========================================
@tasks.loop(minutes=30)
async def daily_rare_candy_loop():
    today_str = datetime.now(ARG_TZ).strftime("%Y-%m-%d")
    for guild in bot.guilds:
        date_key = f"rare_candy_date_{guild.id}"
        last_uid_key = f"rare_candy_last_uid_{guild.id}"
        if get_bot_state(date_key) == today_str:
            continue

        catch_ch = find_target_channel(guild, CATCH_CHANNEL_NAME)
        if catch_ch is None:
            continue

        eligible = [m for m in catch_ch.members if not m.bot]
        if not eligible:
            continue

        last_uid_raw = get_bot_state(last_uid_key)
        if last_uid_raw and len(eligible) > 1:
            pool = [m for m in eligible if str(m.id) != last_uid_raw] or eligible
        else:
            pool = eligible

        chosen = random.choice(pool)
        set_bot_state(date_key, today_str)
        set_bot_state(last_uid_key, str(chosen.id))
        total_candies = add_rare_candy(guild.id, chosen.id, amount=1, username=chosen.display_name)

        try:
            embed = discord.Embed(
                title="🍬✨ ¡CARAMELO RARO DIARIO DE VICTINI! 🔥",
                description=(
                    f"¡Felicitaciones {chosen.mention}! *Victini eligió tu suerte hoy en **`{catch_ch.name}`*** ✌️🎉\n\n"
                    f"🎁 **Regalo:** **+1 Rare Candy** *(Tenés **{total_candies}** en tu mochila)*\n"
                    f"⚡ **Efecto:** Subí **+10 niveles** a uno de tus Pokémon del equipo *(¡en Pokémon con ramas como Eevee podés elegir evolución!)* y sumá **+1 nivel de servidor**.\n\n"
                    f"*Tocá el botón de abajo o usá `/rarecandy` cuando quieras.*"
                ),
                color=discord.Color.gold(),
            )
            embed.set_footer(text="Victini Bot • Rare Candy Diario 🔥✌️")
            view = RareCandyGiftView(
                guild=guild,
                author_id=chosen.id,
                on_backup=sync_levels_backup,
                on_level_up=notify_level_up,
            )
            await catch_ch.send(content=chosen.mention, embed=embed, view=view)
            print(f"🍬 Rare Candy diario entregado a {chosen.display_name} en {guild.name}.", flush=True)
        except Exception as e:
            print(f"⚠️ Error entregando Rare Candy diario en {guild.name}: {e}", flush=True)


@daily_rare_candy_loop.before_loop
async def before_daily_rare_candy_loop():
    await bot.wait_until_ready()


@bot.tree.command(
    name="chivo",
    description="Fuerza uno de los mensajes promocionales de EntreTurnos o SNAP! (Solo en 🛗𝑪𝑯𝑨𝑻-𝑮𝑬𝑵𝑬𝑹𝑨𝑳)",
)
@app_commands.describe(mensaje="(Opcional) Elegí cuál chivo mandar; si no elegís ninguno, va alternando")
@app_commands.choices(
    mensaje=[
        app_commands.Choice(name="EntreTurnos (YouTube Streaming de Pokémon TCG)", value=0),
        app_commands.Choice(name="SNAP! Stock / TCG Fans / Lo de Charly", value=1),
    ]
)
async def chivo_command(
    interaction: discord.Interaction,
    mensaje: Optional[app_commands.Choice[int]] = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
            ephemeral=True,
        )
        return

    if not is_chat_general_channel(interaction.channel):
        chat_ch = find_target_channel(interaction.guild, CHAT_GENERAL_CHANNEL_NAME)
        ch_mention = chat_ch.mention if chat_ch else f"**{CHAT_GENERAL_CHANNEL_NAME}**"
        await interaction.response.send_message(
            f"📢 ¡Ey! El comando `/chivo` solo se puede usar en el canal {ch_mention} 👀🔥",
            ephemeral=True,
        )
        return

    await interaction.response.defer()
    try:
        choice_val = mensaje.value if mensaje is not None else None
        text, card_file = await asyncio.to_thread(build_promo_payload, choice_val)
        await interaction.followup.send(content=text, file=card_file)
    except Exception as e:
        print(f"⚠️ Error ejecutando /chivo: {e}", flush=True)
        await interaction.followup.send(
            "❌ Ocurrió un error al generar la tarjeta del chivo. Revisá los logs.",
            ephemeral=True,
        )


# ==========================================
# 3. COMANDO /nivel (EXCLUSIVO DE 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀)
# ==========================================
@bot.tree.command(
    name="nivel",
    description="Consultá tu nivel actual y tu posición en el ranking de SNAP! (Solo en 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀)",
)
@app_commands.describe(usuario="(Opcional) Miembro del que querés consultar el nivel")
async def nivel_command(
    interaction: discord.Interaction,
    usuario: Optional[discord.Member] = None,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
            ephemeral=True,
        )
        return

    if not is_snap_level_channel(interaction.channel):
        level_ch = find_target_channel(interaction.guild, LEVEL_CHANNEL_NAME)
        ch_mention = level_ch.mention if level_ch else f"**{LEVEL_CHANNEL_NAME}**"
        await interaction.response.send_message(
            f"🔥 ¡Ojo! El comando `/nivel` solo se puede usar en el canal {ch_mention} 👀",
            ephemeral=True,
        )
        return

    target = usuario or interaction.user
    level, xp, rank = get_user_stats(interaction.guild.id, target.id)
    pokeballs = get_pokeballs(interaction.guild.id, target.id)
    next_xp = xp_for_next_level(level)

    if rank is not None and rank <= 10:
        frase = (
            f"Tu nivel es **{level}**, ¡felicitaciones! Estás entre los primeros 10 🔥 "
            f"*(Puesto #{rank} • {xp}/{next_xp} XP • 🎱 {pokeballs} Pokéballs)*"
        )
    else:
        frase = (
            f"Tu nivel es **{level}**, aún te queda mucho camino por recorrer. "
            f"*(Puesto #{rank} • {xp}/{next_xp} XP • 🎱 {pokeballs} Pokéballs)*"
        )

    if target.id != interaction.user.id:
        frase = f"📊 **{target.display_name}**: " + frase

    await interaction.response.send_message(frase)


# ==========================================
# 4. COMANDO /ranking (EXCLUSIVO DE 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀)
# ==========================================
@bot.tree.command(
    name="ranking",
    description="Muestra la tabla de posiciones con el Top 10 de niveles y experiencia (Solo en 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀)",
)
async def ranking_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
            ephemeral=True,
        )
        return

    if not is_snap_level_channel(interaction.channel):
        level_ch = find_target_channel(interaction.guild, LEVEL_CHANNEL_NAME)
        ch_mention = level_ch.mention if level_ch else f"**{LEVEL_CHANNEL_NAME}**"
        await interaction.response.send_message(
            f"🔥 ¡Ojo! El comando `/ranking` solo se puede usar en el canal {ch_mention} 👀",
            ephemeral=True,
        )
        return

    embed, _ = build_ranking_embed(interaction.guild, page=0, per_page=10)
    view = RankingPaginationView(
        guild=interaction.guild,
        author_id=interaction.user.id,
        page=0,
        per_page=10,
    )

    await interaction.response.send_message(embed=embed, view=view)


if __name__ == "__main__":
    if not TOKEN or TOKEN == "TU_TOKEN_DE_DISCORD_AQUI":
        print(
            "❌ ERROR: No se encontró DISCORD_TOKEN en las variables de entorno o en el archivo .env.\n"
            "Configurá DISCORD_TOKEN en Render o en tu archivo .env local.",
            flush=True,
        )
    else:
        from keep_alive import keep_alive

        keep_alive()
        print("🚀 Iniciando Portal Web + Victini Bot en Discord...", flush=True)
        bot.run(TOKEN)
