import asyncio
import io
import os
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
    get_leaderboard,
    xp_for_next_level,
    export_guild_levels,
    import_guild_levels,
)
from music import setup_music_commands

# Forzar salida sin buffer en Render para que todos los print() aparezcan al instante en los Logs
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Nombres exactos de los canales del servidor SNAP!
WELCOME_CHANNEL_NAME = "🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺"
LEVEL_CHANNEL_NAME = "🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀"
UPDATES_CHANNEL_NAME = "🔥𝑽𝑰𝑪𝑻𝑰𝑵𝑰-𝑼𝑷𝑫𝑨𝑻𝑬𝑺🔥"
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


# ==========================================
# PERSISTENCIA EN LA NUBE (RESPALDO OCULTO EN DISCORD)
# Evita que se pierdan los niveles cuando Render reinicia o hace deploy
# ==========================================
_backup_messages: dict[int, discord.Message] = {}
_last_backup_ts: dict[int, float] = {}
_backup_locks: dict[int, asyncio.Lock] = {}


def _get_backup_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in _backup_locks:
        _backup_locks[guild_id] = asyncio.Lock()
    return _backup_locks[guild_id]


async def get_or_create_backup_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    """Obtiene o crea el canal privado oculto `victini-db-backup` (solo visible para Admins)."""
    existing = discord.utils.get(guild.text_channels, name=BACKUP_CHANNEL_NAME)
    if existing is not None:
        return existing
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
        }
        channel = await guild.create_text_channel(
            name=BACKUP_CHANNEL_NAME,
            overwrites=overwrites,
            reason="Canal oculto de respaldo automático para no perder niveles/XP de SNAP! al reiniciar Render",
        )
        print(f"💾 Canal oculto de respaldo '{BACKUP_CHANNEL_NAME}' creado en '{guild.name}'.", flush=True)
        return channel
    except Exception as e:
        print(f"⚠️ No se pudo crear canal de respaldo en {guild.name}: {e}", flush=True)
        return None


async def restore_levels_from_discord(guild: discord.Guild) -> None:
    """Restaura automáticamente la tabla de niveles desde el último respaldo en `victini-db-backup`."""
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
                        _backup_messages[guild.id] = msg
                        print(
                            f"♻️ Niveles restaurados en '{guild.name}': {restored} usuarios recuperados.",
                            flush=True,
                        )
                        return
    except Exception as e:
        print(f"⚠️ Error restaurando respaldo en {guild.name}: {e}", flush=True)


async def sync_levels_backup(guild: discord.Guild, force: bool = False) -> None:
    """Guarda el JSON actualizado de niveles en el canal oculto `victini-db-backup`."""
    now = time.time()
    if not force and (now - _last_backup_ts.get(guild.id, 0.0) < BACKUP_THROTTLE_SECONDS):
        return

    async with _get_backup_lock(guild.id):
        now = time.time()
        if not force and (now - _last_backup_ts.get(guild.id, 0.0) < BACKUP_THROTTLE_SECONDS):
            return

        ch = await get_or_create_backup_channel(guild)
        if ch is None:
            return

        records = export_guild_levels(guild.id)
        if not records:
            return

        payload = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        file_obj = discord.File(io.BytesIO(payload), filename="victini_levels_backup.json")
        summary = f"💾 Respaldo automático SNAP! • {len(records)} usuarios • <t:{int(now)}:R>"

        try:
            msg = _backup_messages.get(guild.id)
            if msg is not None:
                await msg.edit(content=summary, attachments=[file_obj])
            else:
                # Buscar si ya existía un mensaje previo en el historial antes de crear uno nuevo
                existing_msg = None
                async for h_msg in ch.history(limit=5):
                    if h_msg.author.id == guild.me.id and h_msg.attachments:
                        existing_msg = h_msg
                        break
                if existing_msg is not None:
                    await existing_msg.edit(content=summary, attachments=[file_obj])
                    _backup_messages[guild.id] = existing_msg
                else:
                    new_msg = await ch.send(content=summary, file=file_obj)
                    _backup_messages[guild.id] = new_msg
            _last_backup_ts[guild.id] = time.time()
        except Exception as e:
            print(f"⚠️ Error guardando respaldo de niveles en {guild.name}: {e}", flush=True)


async def notify_level_up(guild: discord.Guild, member: discord.Member, new_level: int) -> None:
    """Envía el aviso oficial de subida de nivel únicamente por 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀."""
    level_channel = find_target_channel(guild, LEVEL_CHANNEL_NAME)
    if level_channel is not None:
        level_up_msg = (
            f"{member.mention} ha subido al nivel {new_level}. "
            f"Espero que haya sido de forma legal 👀 o mis llamas actuarán rápidamente con severas consecuencias 🔥😈"
        )
        await level_channel.send(level_up_msg)
    else:
        print(
            f"⚠️ {member} subió a nivel {new_level}, pero no se encontró el canal '{LEVEL_CHANNEL_NAME}'.",
            flush=True,
        )


def build_ranking_embed(
    guild: discord.Guild,
    page: int,
    per_page: int = 10,
) -> tuple[discord.Embed, int]:
    """
    Construye el Embed con la tabla de posiciones para la página indicada (page es 0-indexed).
    Retorna (embed, total_users).
    """
    offset = page * per_page
    rows, total_users = get_leaderboard(guild.id, limit=per_page, offset=offset)

    title = "🏆 Ranking de Niveles - SNAP! 🔥"
    if page == 0:
        subtitle = "Top 10 de la comunidad vigilados por **Victini Bot** 👀🔥"
    else:
        start_pos = offset + 1
        end_pos = min(offset + per_page, total_users)
        subtitle = f"Posiciones #{start_pos} a #{end_pos} de la comunidad **SNAP!** 🔥"

    embed = discord.Embed(
        title=title,
        description=subtitle,
        color=discord.Color.orange(),
    )

    if not rows:
        embed.add_field(
            name="Sin datos aún",
            value="Todavía no hay miembros con experiencia registrada. ¡Empiecen a charlar!",
            inline=False,
        )
        return embed, total_users

    table_lines = [
        f"{'POS':<4} | {'USUARIO':<18} | {'NIVEL':<5} | {'EXPERIENCIA'}",
        "-" * 48,
    ]

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for idx, (user_id, stored_username, level, xp) in enumerate(rows, start=offset + 1):
        member = guild.get_member(user_id)
        display_name = member.display_name if member else (stored_username or f"ID:{user_id}")
        if len(display_name) > 16:
            display_name = display_name[:15] + "…"

        pos_str = medals.get(idx, f"#{idx}")
        next_xp = xp_for_next_level(level)
        table_lines.append(
            f"{pos_str:<4} | {display_name:<18} | Nv.{level:<2} | {xp}/{next_xp} XP"
        )

    table_block = "```\n" + "\n".join(table_lines) + "\n```"
    embed.add_field(name="📊 Tabla de Posiciones", value=table_block, inline=False)

    total_pages = max(1, (total_users + per_page - 1) // per_page)
    embed.set_footer(
        text=f"Victini Bot • Mascota oficial de SNAP! • Página {page + 1}/{total_pages} ({total_users} miembros)"
    )
    return embed, total_users


class RankingPaginationView(discord.ui.View):
    """Vista interactiva con botón 'Ver más...' y 'Anterior' para explorar el ranking."""

    def __init__(self, guild: discord.Guild, author_id: int, page: int = 0, per_page: int = 10):
        super().__init__(timeout=180)
        self.guild = guild
        self.author_id = author_id
        self.page = page
        self.per_page = per_page
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
        print("🔥 Inicializando base de datos y árbol de comandos slash...", flush=True)

    async def on_ready(self):
        print(f"✅ Victini Bot conectado como {self.user} (ID: {self.user.id})", flush=True)
        if not self._boot_notified:
            self._boot_notified = True
            commit_time_str = get_latest_commit_time_str()

            for guild in self.guilds:
                # 1. Restaurar niveles y experiencia desde el canal oculto antes de nada
                await restore_levels_from_discord(guild)

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
        f"Bienvenido {member.mention}, acá vas a poder hacer muchas cosas y conocer gente muy copada, "
        f"pero no te pases de vivo/a porque estoy viendo todo"
    )
    await welcome_channel.send(welcome_msg)


# ==========================================
# 2A. SISTEMA DE NIVELES: MENSAJES EN CANALES DE TEXTO
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    # Sumar XP únicamente por mensajes enviados en canales de texto (o hilos de canales de texto)
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
    next_xp = xp_for_next_level(level)

    if rank is not None and rank <= 10:
        frase = (
            f"Tu nivel es **{level}**, ¡felicitaciones! Estás entre los primeros 10 🔥 "
            f"*(Puesto #{rank} • {xp}/{next_xp} XP)*"
        )
    else:
        frase = (
            f"Tu nivel es **{level}**, aún te queda mucho camino por recorrer. "
            f"*(Puesto #{rank} • {xp}/{next_xp} XP)*"
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
