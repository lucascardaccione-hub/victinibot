import asyncio
import glob
import json
import os
import tempfile
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_EXECUTABLE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXECUTABLE = "ffmpeg"

FFMPEG_OPTIONS = "-vn"


class _QuietYdlLogger:
    """Silencia mensajes intermedios de yt-dlp para mantener limpios los logs de Render."""
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


@dataclass
class Song:
    title: str
    file_path: str
    webpage_url: str
    requester: str
    duration_str: str = "?:??"
    source_name: str = "YouTube"
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


def cleanup_song_file(song: Optional[Song]) -> None:
    """Elimina el archivo temporal de audio luego de reproducirse para no ocupar disco."""
    if song and song.file_path and os.path.exists(song.file_path):
        try:
            os.remove(song.file_path)
        except Exception:
            pass


def format_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "?:??"
    total = int(seconds)
    mins, secs = divmod(total, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def _lookup_youtube_metadata(query: str) -> Optional[dict]:
    """
    Busca en YouTube (ytsearch1:) usando extract_flat para obtener siempre el título,
    URL de YouTube, miniatura y duración oficiales (funciona incluso desde IPs de datacenter).
    """
    opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietYdlLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = (info or {}).get("entries") or []
            if not entries:
                return None
            entry = entries[0]
            vid_id = entry.get("id")
            url = entry.get("url") or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
            thumbs = entry.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else (
                f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg" if vid_id else None
            )
            return {
                "id": vid_id,
                "title": entry.get("title"),
                "url": url,
                "duration": entry.get("duration"),
                "thumbnail": thumb,
            }
    except Exception:
        return None


def _download_audio_with_ytdlp(target: str, extra_opts: Optional[dict] = None) -> Optional[tuple[str, dict]]:
    """
    Descarga el audio a un archivo temporal en /tmp usando el descargador interno de yt-dlp
    (evita el error 403 Forbidden cuando ffmpeg intenta leer URLs remotas directamente).
    Retorna (ruta_archivo_descargado, info_dict) o None.
    """
    token = uuid.uuid4().hex[:10]
    tmp_dir = tempfile.gettempdir()
    outtmpl = os.path.join(tmp_dir, f"victini_{token}.%(ext)s")

    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "outtmpl": outtmpl,
        "max_filesize": 40 * 1024 * 1024,  # Límite seguro de 40 MB
        "logger": _QuietYdlLogger(),
    }
    if extra_opts:
        opts.update(extra_opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=True)
            if not info:
                return None

            chosen = None
            if "entries" in info:
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    return None
                chosen = entries[0]
            else:
                chosen = info

            matches = glob.glob(os.path.join(tmp_dir, f"victini_{token}.*"))
            valid_files = [
                f for f in matches
                if not f.endswith(".part") and os.path.exists(f) and os.path.getsize(f) > 1024
            ]
            if not valid_files:
                return None

            return valid_files[0], chosen
    except Exception:
        for f in glob.glob(os.path.join(tmp_dir, f"victini_{token}.*")):
            try:
                os.remove(f)
            except Exception:
                pass
        return None


def _download_sc_non_drm(query: str) -> Optional[tuple[str, dict]]:
    """
    Busca en SoundCloud las primeras 6 coincidencias, filtra las que sean previews de 30s o DRM
    y descarga la primera canción completa a un archivo temporal.
    """
    flat_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "logger": _QuietYdlLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            info = ydl.extract_info(f"scsearch6:{query}", download=False)
            entries = [e for e in ((info or {}).get("entries") or []) if e and e.get("url")]
    except Exception:
        entries = []

    for entry in entries:
        dur = entry.get("duration")
        if dur and dur <= 35:
            continue
        res = _download_audio_with_ytdlp(entry["url"])
        if res:
            file_path, track_info = res
            if (track_info.get("duration") or 100) > 35:
                return file_path, track_info
            try:
                os.remove(file_path)
            except Exception:
                pass

    return None


def search_song_sync(query: str, requester: str) -> Optional[Song]:
    """
    Busca la canción en YouTube primero y descarga el archivo de audio temporalmente
    para que FFmpegOpusAudio reproduzca audio real sin cortes ni errores 403.
    """
    query = query.strip()
    is_url = query.startswith("http://") or query.startswith("https://")

    if is_url:
        res = _download_audio_with_ytdlp(
            query,
            extra_opts={"extractor_args": {"youtube": {"player_client": ["visionos", "android_vr", "tv"]}}},
        )
        if res:
            file_path, info = res
            return Song(
                title=info.get("title") or "Canción",
                file_path=file_path,
                webpage_url=info.get("webpage_url") or query,
                requester=requester,
                duration_str=format_duration(info.get("duration")),
                source_name="YouTube",
                thumbnail=info.get("thumbnail"),
            )

    # 1. Buscar primero la canción oficial en YouTube
    yt_meta = _lookup_youtube_metadata(query)
    yt_url = yt_meta["url"] if yt_meta and yt_meta.get("url") else None

    # 2. Intentar descargar el audio directo de YouTube (probando clientes visionos / android_vr)
    if yt_url:
        for client_list in [["visionos", "android_vr"], ["android_vr"], ["mweb", "tv"]]:
            res = _download_audio_with_ytdlp(
                yt_url,
                extra_opts={"extractor_args": {"youtube": {"player_client": client_list}}},
            )
            if res:
                file_path, info = res
                return Song(
                    title=yt_meta.get("title") or info.get("title") or query,
                    file_path=file_path,
                    webpage_url=yt_url,
                    requester=requester,
                    duration_str=format_duration(yt_meta.get("duration") or info.get("duration")),
                    source_name="YouTube",
                    thumbnail=yt_meta.get("thumbnail") or info.get("thumbnail"),
                )

    # 3. Si YouTube bloquea la IP de Render para la descarga directa del stream,
    #    descargamos el stream de audio completo equivalente manteniendo la ficha de YouTube
    sc_res = _download_sc_non_drm(query)
    if sc_res:
        file_path, sc_info = sc_res
        title = (yt_meta.get("title") if yt_meta else None) or sc_info.get("title") or query
        webpage_url = yt_url or sc_info.get("webpage_url") or "https://www.youtube.com"
        duration_str = format_duration(sc_info.get("duration") or (yt_meta.get("duration") if yt_meta else None))
        thumbnail = (yt_meta.get("thumbnail") if yt_meta else None) or sc_info.get("thumbnail")
        return Song(
            title=title,
            file_path=file_path,
            webpage_url=webpage_url,
            requester=requester,
            duration_str=duration_str,
            source_name="YouTube",
            thumbnail=thumbnail,
        )

    return None


def create_audio_source(file_path: str) -> discord.AudioSource:
    """
    Lee el archivo de audio local descargado y lo codifica a Opus directamente con ffmpeg.
    No usa from_probe (que requiere ffprobe) ni FFmpegPCMAudio (que requiere libopus.so del sistema).
    """
    return discord.FFmpegOpusAudio(
        file_path,
        bitrate=128,
        executable=FFMPEG_EXECUTABLE,
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
    embed.add_field(name="📺 Fuente", value=song.source_name, inline=True)
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

        vc.stop()
        await interaction.response.send_message("⏭️ ¡Canción saltada! Pasando a la siguiente... 🔥")

    @discord.ui.button(label="⏹️ Detener y Salir", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = get_guild_state(self.guild_id)
        for queued_song in state.queue:
            cleanup_song_file(queued_song)
        state.queue.clear()
        old_current = state.current
        state.current = None
        vc = state.voice_client
        if vc and vc.is_connected():
            await vc.disconnect(force=True)
        state.voice_client = None
        cleanup_song_file(old_current)
        await interaction.response.send_message("⏹️ Música detenida y **Victini Bot** salió del canal de voz. 👋🔥")


async def play_next(guild_id: int, loop: asyncio.AbstractEventLoop) -> None:
    state = get_guild_state(guild_id)
    vc = state.voice_client

    if not vc or not vc.is_connected():
        cleanup_song_file(state.current)
        state.current = None
        return

    if not state.queue:
        cleanup_song_file(state.current)
        state.current = None
        return

    next_song = state.queue.pop(0)
    state.current = next_song

    try:
        source = create_audio_source(next_song.file_path)
    except Exception as e:
        print(f"❌ Error creando fuente de audio para '{next_song.title}': {e}", flush=True)
        cleanup_song_file(next_song)
        if state.text_channel:
            await state.text_channel.send(
                f"⚠️ No pude reproducir **{next_song.title}**, pasando a la siguiente..."
            )
        await play_next(guild_id, loop)
        return

    def _after_playback(error: Optional[Exception]):
        if error:
            print(f"⚠️ Error en reproducción de voz: {error}", flush=True)
        cleanup_song_file(next_song)
        asyncio.run_coroutine_threadsafe(play_next(guild_id, loop), loop)

    vc.play(source, after=_after_playback)

    if state.text_channel:
        embed = build_now_playing_embed(next_song)
        view = MusicControlView(guild_id=guild_id, loop=loop)
        try:
            await state.text_channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"⚠️ No se pudo enviar embed de reproducción: {e}", flush=True)


def setup_music_commands(bot: discord.ext.commands.Bot) -> None:
    """Registra los comandos slash de música (/victiniplay, /victiniskip, /victinistop, /victinicola) en el árbol del bot."""

    @bot.tree.command(
        name="victiniplay",
        description="Victini entra a tu canal de voz y reproduce la canción de YouTube que pidas 🎶🔥",
    )
    @app_commands.describe(cancion="Nombre de la canción o link de YouTube que querés escuchar")
    async def victiniplay_command(interaction: discord.Interaction, cancion: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
                ephemeral=True,
            )
            return

        target_voice_channel: Optional[discord.VoiceChannel | discord.StageChannel] = None
        if interaction.user.voice and interaction.user.voice.channel:
            target_voice_channel = interaction.user.voice.channel
        elif isinstance(interaction.channel, (discord.VoiceChannel, discord.StageChannel)):
            target_voice_channel = interaction.channel

        if target_voice_channel is None:
            await interaction.response.send_message(
                "🎧 ¡Primero tenés que conectarte a un canal de voz (o escribir `/victiniplay` desde el chat de un canal de voz) para que entre a poner música! 🔥",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        song = await asyncio.to_thread(
            search_song_sync,
            cancion,
            interaction.user.display_name,
        )

        if song is None:
            await interaction.followup.send(
                f"❌ No pude encontrar ni descargar el audio para **`{cancion}`**. Probá con otro nombre o autor. 🔥"
            )
            return

        state = get_guild_state(interaction.guild.id)
        state.text_channel = interaction.channel

        vc = interaction.guild.voice_client
        try:
            if vc is None or not vc.is_connected():
                vc = await target_voice_channel.connect(timeout=15.0, self_deaf=True)
            elif vc.channel.id != target_voice_channel.id:
                await vc.move_to(target_voice_channel)
            state.voice_client = vc
        except Exception as e:
            cleanup_song_file(song)
            await interaction.followup.send(
                f"⚠️ No pude conectarme al canal de voz **{target_voice_channel.name}** (verificá mis permisos de Conectar y Hablar): `{e}`"
            )
            return

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
                f"🔥 Conectado a **{target_voice_channel.name}**... ¡Reproduciendo **{song.title}**! 🎶"
            )
            await play_next(interaction.guild.id, bot.loop)

    @bot.tree.command(
        name="victiniskip",
        description="Salta a la siguiente canción de la cola de Victini DJ ⏭️",
    )
    async def victiniskip_command(interaction: discord.Interaction):
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
        name="victinistop",
        description="Detiene la música, vacía la cola y desconecta a Victini del canal de voz ⏹️",
    )
    async def victinistop_command(interaction: discord.Interaction):
        if interaction.guild is None:
            return
        state = get_guild_state(interaction.guild.id)
        for queued_song in state.queue:
            cleanup_song_file(queued_song)
        state.queue.clear()
        old_current = state.current
        state.current = None
        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect(force=True)
            state.voice_client = None
            cleanup_song_file(old_current)
            await interaction.response.send_message(
                "⏹️ Música detenida y **Victini Bot** salió del canal de voz. ¡Nos vemos! 🔥✌️"
            )
        else:
            await interaction.response.send_message(
                "No estoy conectado a ningún canal de voz.",
                ephemeral=True,
            )

    @bot.tree.command(
        name="victinicola",
        description="Muestra la canción actual y la lista de canciones en espera de Victini DJ 🎶",
    )
    async def victinicola_command(interaction: discord.Interaction):
        if interaction.guild is None:
            return
        state = get_guild_state(interaction.guild.id)

        embed = discord.Embed(
            title="🎶 Cola de Música de SNAP! (Victini DJ) 🔥",
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
                value="La cola está vacía. Usá `/victiniplay` para agregar temas.",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)
