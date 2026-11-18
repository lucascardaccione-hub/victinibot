import asyncio
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import discord
from discord import app_commands
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_EXECUTABLE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXECUTABLE = "ffmpeg"

FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"
)
FFMPEG_OPTIONS = "-vn"

YDL_BASE_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "extract_flat": False,
}


@dataclass
class Song:
    title: str
    stream_url: str
    webpage_url: str
    requester: str
    duration_str: str = "En vivo / Desconocida"
    source_name: str = "Audio"
    thumbnail: Optional[str] = None


@dataclass
class GuildMusicState:
    queue: List[Song] = field(default_factory=list)
    current: Optional[Song] = None
    voice_client: Optional[discord.VoiceClient] = None
    text_channel: Optional[discord.abc.Messageable] = None


music_states: Dict[int, GuildMusicState] = {}


def get_guild_state(guild_id: int) -> GuildMusicState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState()
    return music_states[guild_id]


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "?:??"
    total = int(seconds)
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def _extract_with_ytdlp(search_target: str, source_label: str, requester: str) -> Optional[Song]:
    opts = dict(YDL_BASE_OPTS)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_target, download=False)
        if not info:
            return None
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                return None
            info = entries[0]

        stream_url = info.get("url")
        if not stream_url:
            return None

        title = info.get("title") or "Canción sin título"
        webpage_url = info.get("webpage_url") or stream_url
        duration_str = format_duration(info.get("duration"))
        thumbnail = info.get("thumbnail")

        return Song(
            title=title,
            stream_url=stream_url,
            webpage_url=webpage_url,
            requester=requester,
            duration_str=duration_str,
            source_name=source_label,
            thumbnail=thumbnail,
        )


def _search_itunes_fallback(query: str, requester: str) -> Optional[Song]:
    """Fallback ultrarrápido si tanto YouTube como SoundCloud bloquean la IP del servidor."""
    encoded = urllib.parse.quote(query)
    url = f"https://itunes.apple.com/search?term={encoded}&media=music&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "VictiniBot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        results = data.get("results", [])
        if not results:
            return None
        track = results[0]
        preview_url = track.get("previewUrl")
        if not preview_url:
            return None
        artist = track.get("artistName", "")
        name = track.get("trackName", query)
        full_title = f"{artist} - {name}" if artist else name
        return Song(
            title=full_title,
            stream_url=preview_url,
            webpage_url=track.get("trackViewUrl", preview_url),
            requester=requester,
            duration_str="0:30 (Preview)",
            source_name="Apple Music Preview",
            thumbnail=track.get("artworkUrl100"),
        )


def search_song_sync(query: str, requester: str) -> Optional[Song]:
    """
    Busca una canción por nombre o URL.
    1. Si es URL directa, la extrae con yt-dlp.
    2. Si es nombre de canción, intenta SoundCloud (scsearch1, ideal para IPs de Render sin bloqueo de bot)
       y YouTube (ytsearch1), con fallback a Apple Music.
    """
    query = query.strip()
    is_url = query.startswith("http://") or query.startswith("https://")

    if is_url:
        try:
            return _extract_with_ytdlp(query, "Enlace directo", requester)
        except Exception as e:
            print(f"⚠️ Error extrayendo URL directa ({query}): {e}")
            return None

    # 1. Intentar SoundCloud primero (no sufre bloqueo anti-bot en servidores cloud como Render)
    try:
        song = _extract_with_ytdlp(f"scsearch1:{query}", "SoundCloud", requester)
        if song:
            return song
    except Exception as e:
        print(f"⚠️ SoundCloud search falló para '{query}': {e}")

    # 2. Intentar YouTube
    try:
        song = _extract_with_ytdlp(f"ytsearch1:{query}", "YouTube", requester)
        if song:
            return song
    except Exception as e:
        print(f"⚠️ YouTube search falló para '{query}': {e}")

    # 3. Fallback a Apple Music
    try:
        return _search_itunes_fallback(query, requester)
    except Exception as e:
        print(f"⚠️ Fallback iTunes falló para '{query}': {e}")
        return None


async def create_audio_source(stream_url: str) -> discord.AudioSource:
    """
    Crea el AudioSource usando FFmpegOpusAudio (no requiere libopus.so instalado en el sistema Linux de Render).
    Si falla, usa FFmpegPCMAudio como respaldo.
    """
    try:
        return await discord.FFmpegOpusAudio.from_probe(
            stream_url,
            executable=FFMPEG_EXECUTABLE,
            before_options=FFMPEG_BEFORE_OPTIONS,
            options=FFMPEG_OPTIONS,
        )
    except Exception:
        return discord.FFmpegPCMAudio(
            stream_url,
            executable=FFMPEG_EXECUTABLE,
            before_options=FFMPEG_BEFORE_OPTIONS,
            options=FFMPEG_OPTIONS,
        )


def build_now_playing_embed(song: Song, status_title: str = "🎶 Reproduciendo ahora en SNAP! 🔥") -> discord.Embed:
    embed = discord.Embed(
        title=status_title,
        description=f"**[{song.title}]({song.webpage_url})**",
        color=discord.Color.orange(),
    )
    embed.add_field(name="⏱️ Duración", value=song.duration_str, inline=True)
    embed.add_field(name="🎧 Pedido por", value=song.requester, inline=True)
    embed.add_field(name="📡 Fuente", value=song.source_name, inline=True)
    if song.thumbnail:
        embed.set_thumbnail(url=song.thumbnail)
    embed.set_footer(text="Victini DJ • Mascota oficial de SNAP! 🔥")
    return embed


class MusicControlView(discord.ui.View):
    """Botones interactivos para pausar/reanudar, saltar canción o desconectar a Victini."""

    def __init__(self, guild_id: int, loop: asyncio.AbstractEventLoop):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.bot_loop = loop

    @discord.ui.button(label="⏯️ Pausar / Reanudar", style=discord.ButtonStyle.primary)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_guild_state(self.guild_id)
        vc = state.voice_client
        if not vc or not vc.is_connected():
            await interaction.response.send_message("No estoy conectado a ningún canal de voz.", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Música pausada por **Victini DJ**.", ephemeral=False)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ ¡Música reanudada! 🔥", ephemeral=False)
        else:
            await interaction.response.send_message("No hay ninguna canción sonando en este momento.", ephemeral=True)

    @discord.ui.button(label="⏭️ Saltar", style=discord.ButtonStyle.secondary)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_guild_state(self.guild_id)
        vc = state.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("No hay ninguna canción para saltar.", ephemeral=True)
            return

        vc.stop()  # Dispara el callback after -> play_next
        await interaction.response.send_message("⏭️ ¡Canción saltada! Pasando a la siguiente... 🔥")

    @discord.ui.button(label="⏹️ Detener y Salir", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_guild_state(self.guild_id)
        state.queue.clear()
        state.current = None
        vc = state.voice_client
        if vc and vc.is_connected():
            await vc.disconnect(force=True)
        state.voice_client = None
        await interaction.response.send_message("⏹️ Música detenida y **Victini Bot** salió del canal de voz. 👋🔥")


async def play_next(guild_id: int, loop: asyncio.AbstractEventLoop) -> None:
    state = get_guild_state(guild_id)
    vc = state.voice_client

    if not vc or not vc.is_connected():
        state.current = None
        return

    if not state.queue:
        state.current = None
        return

    next_song = state.queue.pop(0)
    state.current = next_song

    try:
        source = await create_audio_source(next_song.stream_url)
    except Exception as e:
        print(f"❌ Error creando fuente de audio para '{next_song.title}': {e}")
        if state.text_channel:
            await state.text_channel.send(
                f"⚠️ No pude reproducir **{next_song.title}**, pasando a la siguiente..."
            )
        await play_next(guild_id, loop)
        return

    def _after_playback(error: Optional[Exception]):
        if error:
            print(f"⚠️ Error en reproducción de voz: {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild_id, loop), loop)

    vc.play(source, after=_after_playback)

    if state.text_channel:
        embed = build_now_playing_embed(next_song)
        view = MusicControlView(guild_id=guild_id, loop=loop)
        try:
            await state.text_channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"⚠️ No se pudo enviar embed de reproducción: {e}")


def setup_music_commands(bot: discord.ext.commands.Bot) -> None:
    """Registra los comandos slash de música (/play, /skip, /stop, /cola) en el árbol del bot."""

    @bot.tree.command(
        name="play",
        description="Victini entra a tu canal de voz y reproduce la canción que pidas 🎶🔥",
    )
    @app_commands.describe(cancion="Nombre de la canción o link que querés escuchar")
    async def play_command(interaction: discord.Interaction, cancion: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
                ephemeral=True,
            )
            return

        # Determinar a qué canal de voz conectarse:
        # 1. Si el usuario está conectado a un canal de voz, usar ese.
        # 2. Si el comando se tiró en el chat integrado de un canal de voz, usar ese canal de voz.
        target_voice_channel: Optional[discord.VoiceChannel | discord.StageChannel] = None
        if interaction.user.voice and interaction.user.voice.channel:
            target_voice_channel = interaction.user.voice.channel
        elif isinstance(interaction.channel, (discord.VoiceChannel, discord.StageChannel)):
            target_voice_channel = interaction.channel

        if target_voice_channel is None:
            await interaction.response.send_message(
                "🎧 ¡Primero tenés que conectarte a un canal de voz (o escribir `/play` desde el chat de un canal de voz) para que entre a poner música! 🔥",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Buscar la canción en un hilo secundario para no bloquear el bot
        song = await asyncio.to_thread(
            search_song_sync,
            cancion,
            interaction.user.display_name,
        )

        if song is None:
            await interaction.followup.send(
                f"❌ No pude encontrar ninguna canción para **`{cancion}`**. Probá con otro nombre o autor. 🔥"
            )
            return

        state = get_guild_state(interaction.guild.id)
        state.text_channel = interaction.channel

        # Conectar o mover a Victini al canal de voz
        vc = interaction.guild.voice_client
        try:
            if vc is None or not vc.is_connected():
                vc = await target_voice_channel.connect(timeout=15.0, self_deaf=True)
            elif vc.channel.id != target_voice_channel.id:
                await vc.move_to(target_voice_channel)
            state.voice_client = vc
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ No pude conectarme al canal de voz **{target_voice_channel.name}** (verificá mis permisos de Conectar y Hablar): `{e}`"
            )
            return

        # Si ya está reproduciendo o en pausa, agregar a la cola
        if vc.is_playing() or vc.is_paused():
            state.queue.append(song)
            embed = build_now_playing_embed(
                song,
                status_title=f"➕ Agregada a la cola (Posición #{len(state.queue)}) 🔥",
            )
            await interaction.followup.send(embed=embed)
        else:
            state.queue.append(song)
            await interaction.followup.send(
                f"🔥 Conectado a **{target_voice_channel.name}**... ¡Preparando las llamas musicales para **{song.title}**! 🎶"
            )
            await play_next(interaction.guild.id, bot.loop)

    @bot.tree.command(
        name="skip",
        description="Salta a la siguiente canción de la cola de reproducción ⏭️",
    )
    async def skip_command(interaction: discord.Interaction):
        if interaction.guild is None:
            return
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message(
                "No hay ninguna canción reproduciéndose en este momento.",
                ephemeral=True,
            )
            return

        vc.stop()
        await interaction.response.send_message("⏭️ ¡Canción saltada! Pasando a la siguiente... 🔥")

    @bot.tree.command(
        name="stop",
        description="Detiene la música, vacía la cola y desconecta a Victini del canal de voz ⏹️",
    )
    async def stop_command(interaction: discord.Interaction):
        if interaction.guild is None:
            return
        state = get_guild_state(interaction.guild.id)
        state.queue.clear()
        state.current = None
        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect(force=True)
            state.voice_client = None
            await interaction.response.send_message(
                "⏹️ Música detenida y **Victini Bot** salió del canal de voz. ¡Nos vemos! 🔥✌️"
            )
        else:
            await interaction.response.send_message(
                "No estoy conectado a ningún canal de voz.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="cola",
        description="Muestra la canción actual y la lista de canciones en espera 🎶",
    )
    async def queue_command(interaction: discord.Interaction):
        if interaction.guild is None:
            return
        state = get_guild_state(interaction.guild.id)

        embed = discord.Embed(
            title="🎶 Cola de Música de SNAP! 🔥",
            color=discord.Color.orange(),
        )

        if state.current:
            embed.add_field(
                name="▶️ Sonando ahora",
                value=f"**{state.current.title}** (`{state.current.duration_str}`) — pedido por *{state.current.requester}*",
                inline=False,
            )
        else:
            embed.add_field(
                name="▶️ Sonando ahora",
                value="Ninguna canción en reproducción.",
                inline=False,
            )

        if state.queue:
            lines = []
            for idx, s in enumerate(state.queue[:10], start=1):
                lines.append(f"`#{idx}` **{s.title}** (`{s.duration_str}`) — *{s.requester}*")
            if len(state.queue) > 10:
                lines.append(f"*...y {len(state.queue) - 10} canciones más.*")
            embed.add_field(
                name=f"📋 En espera ({len(state.queue)})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="📋 En espera",
                value="La cola está vacía. Usá `/play` para agregar temas.",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)
