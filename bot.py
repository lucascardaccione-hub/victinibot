import os
import time
import random
import unicodedata
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from database import (
    init_db,
    add_xp,
    get_user_stats,
    get_leaderboard,
    xp_for_next_level,
)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Nombres exactos de los canales del servidor SNAP!
WELCOME_CHANNEL_NAME = "🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺"
LEVEL_CHANNEL_NAME = "🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀"

# Configuración de experiencia por mensaje
XP_MIN = 15
XP_MAX = 25
XP_COOLDOWN_SECONDS = 45  # Tiempo mínimo entre mensajes que otorgan XP


def normalize_channel_name(name: str) -> str:
    """Normaliza caracteres matemáticos/estilizados Unicode a ASCII básico para comparación segura."""
    return unicodedata.normalize("NFKC", name).lower().strip()


def find_target_channel(guild: discord.Guild, target_name: str) -> Optional[discord.TextChannel]:
    """
    Busca un canal de texto por su nombre exacto (ej. '🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺').
    Si no hay coincidencia exacta, intenta coincidencia normalizada por seguridad.
    """
    for channel in guild.text_channels:
        if channel.name == target_name:
            return channel

    normalized_target = normalize_channel_name(target_name)
    for channel in guild.text_channels:
        if normalize_channel_name(channel.name) == normalized_target:
            return channel

    return None


def is_snap_level_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    """Verifica que el canal donde se ejecutó el comando sea exclusivamente 🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀."""
    if channel is None or not hasattr(channel, "name"):
        return False
    if channel.name == LEVEL_CHANNEL_NAME:
        return True
    return normalize_channel_name(channel.name) == normalize_channel_name(LEVEL_CHANNEL_NAME)


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

        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        init_db()
        await self.tree.sync()
        print("🔥 Comandos slash (/nivel y /ranking) sincronizados correctamente.")

    async def on_ready(self):
        print(f"✅ Victini Bot conectado como {self.user} (ID: {self.user.id})")
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
            f"⚠️ No se encontró el canal '{WELCOME_CHANNEL_NAME}' en el servidor '{member.guild.name}'."
        )
        return

    welcome_msg = (
        f"Bienvenido {member.mention}, acá vas a poder hacer muchas cosas y conocer gente muy copada, "
        f"pero no te pases de vivo/a porque estoy viendo todo"
    )
    await welcome_channel.send(welcome_msg)


# ==========================================
# 2. SISTEMA DE NIVELES (XP POR MENSAJE)
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    xp_gained = random.randint(XP_MIN, XP_MAX)
    leveled_up, new_level, _ = add_xp(
        guild_id=message.guild.id,
        user_id=message.author.id,
        amount=xp_gained,
        now_ts=time.time(),
        username=message.author.display_name,
        cooldown=XP_COOLDOWN_SECONDS,
    )

    if leveled_up:
        level_channel = find_target_channel(message.guild, LEVEL_CHANNEL_NAME)
        if level_channel is not None:
            level_up_msg = (
                f"{message.author.mention} ha subido al nivel {new_level}. "
                f"Espero que haya sido de forma legal 👀 o mis llamas actuarán rápidamente con severas consecuencias 🔥😈"
            )
            await level_channel.send(level_up_msg)
        else:
            print(
                f"⚠️ {message.author} subió a nivel {new_level}, pero no se encontró el canal '{LEVEL_CHANNEL_NAME}'."
            )

    await bot.process_commands(message)


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
            "Configurá DISCORD_TOKEN en Render o en tu archivo .env local."
        )
    else:
        from keep_alive import keep_alive

        keep_alive()
        print("🚀 Iniciando Portal Web + Victini Bot en Discord...")
        bot.run(TOKEN)
