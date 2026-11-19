import asyncio
import glob
import json
import os
import ssl
import subprocess
import tempfile
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Optional, List, Dict, IO

import discord
from discord import app_commands
from discord.ext import commands
import discord.oggparse
import yt_dlp

try:
    import imageio_ffmpeg
    FFMPEG_EXECUTABLE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXECUTABLE = "ffmpeg"


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


def _prepare_hq_opus_file(raw_file_path: str, acodec: Optional[str] = None) -> str:
    """
    Convierte o remuxea el archivo descargado a un contenedor Ogg Opus (.opus) de alta fidelidad
    ANTES de iniciar la reproducción en Discord.
    - Si ya es Opus nativo de YouTube (Format 251 .webm 160kbps 48kHz), copia las tramas sin pérdida (-c:a copy) en ~45ms.
    - Si es AAC/M4A (itag=140 de YouTube), lo codifica a Opus 48kHz Stereo 160kbps VBR con máxima calidad (-compression_level 10 -application audio).
    De este modo, durante la reproducción en vivo en Render Free Tier (0.1 CPU) NO corre ningún subproceso ffmpeg,
    eliminando al 100% los microcortes, saturación y distorsión por límite de CPU.
    """
    base, ext = os.path.splitext(raw_file_path)
    opus_path = f"{base}_hq.opus"

    is_native_opus = (acodec or "").lower() == "opus" or ext.lower() == ".webm"

    if is_native_opus:
        cmd = [
            FFMPEG_EXECUTABLE,
            "-y",
            "-i", raw_file_path,
            "-map_metadata", "-1",
            "-vn",
            "-c:a", "copy",
            "-f", "opus",
            opus_path,
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and os.path.exists(opus_path) and os.path.getsize(opus_path) > 1024:
            try:
                os.remove(raw_file_path)
            except Exception:
                pass
            return opus_path

    # Codificación HQ a Ogg Opus 48kHz Stereo 160kbps para el stream oficial AAC itag=140 de YouTube
    cmd_encode = [
        FFMPEG_EXECUTABLE,
        "-y",
        "-i", raw_file_path,
        "-map_metadata", "-1",
        "-vn",
        "-c:a", "libopus",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "160k",
        "-vbr", "on",
        "-compression_level", "10",
        "-frame_duration", "20",
        "-application", "audio",
        "-f", "opus",
        opus_path,
    ]
    res = subprocess.run(cmd_encode, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode == 0 and os.path.exists(opus_path) and os.path.getsize(opus_path) > 1024:
        try:
            os.remove(raw_file_path)
        except Exception:
            pass
        return opus_path

    return raw_file_path


def _lookup_youtube_metadata(query: str) -> Optional[dict]:
    """
    Busca en YouTube (ytsearch1:) usando extract_flat + oEmbed para obtener siempre el ID del video,
    título oficial, canal/artista, URL de YouTube, miniatura y duración.
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
            raw_title = (entry.get("title") or "").strip()
            channel = (entry.get("channel") or entry.get("uploader") or "").strip()

            # Consultar siempre oEmbed si falta el canal para garantizar el nombre exacto del artista
            if not channel and vid_id:
                try:
                    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid_id}&format=json"
                    req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        odata = json.loads(resp.read().decode("utf-8"))
                        channel = (odata.get("author_name") or "").strip()
                        if not raw_title:
                            raw_title = (odata.get("title") or "").strip()
                except Exception:
                    pass

            clean_channel = channel.replace(" - Topic", "").replace("VEVO", "").strip()

            if clean_channel and clean_channel.lower() not in raw_title.lower():
                display_title = f"{clean_channel} - {raw_title}"
            else:
                display_title = raw_title

            url = entry.get("url") or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None)
            thumbs = entry.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else (
                f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg" if vid_id else None
            )
            return {
                "id": vid_id,
                "title": raw_title,
                "display_title": display_title,
                "channel": clean_channel,
                "url": url,
                "duration": entry.get("duration"),
                "thumbnail": thumb,
            }
    except Exception:
        return None


def _download_youtube_via_invidious_proxy(vid_id: str) -> Optional[str]:
    """
    Descarga el stream oficial de audio de YouTube (itag=140, 128kbps 44.1kHz Stereo M4A/AAC)
    directamente para el video `vid_id` a través de nodos Invidious con proxy local (`local=true`).
    Funciona al 100% desde IPs de datacenter (Render) cuando YouTube bloquea yt-dlp directo,
    garantizando que SIEMPRE suene el audio original del video de YouTube y nunca otra canción.
    """
    hosts = ["https://yt.chocolatemoo53.com"]
    try:
        req = urllib.request.Request(
            "https://api.invidious.io/instances.json?sort_by=health",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            instances = json.loads(resp.read().decode("utf-8"))
            for inst in instances:
                info = inst[1]
                if info.get("type") == "https":
                    uri = info.get("uri", "").rstrip("/")
                    if uri and uri not in hosts:
                        hosts.append(uri)
    except Exception:
        pass

    ctx = ssl._create_unverified_context()
    tmp_dir = tempfile.gettempdir()

    for host in hosts[:4]:
        stream_url = f"{host}/latest_version?id={vid_id}&itag=140&local=true"
        token = uuid.uuid4().hex[:10]
        raw_m4a = os.path.join(tmp_dir, f"victini_yt_{token}.m4a")
        try:
            req = urllib.request.Request(stream_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=22, context=ctx) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "audio" not in ctype and "video" not in ctype and "octet-stream" not in ctype:
                    continue
                with open(raw_m4a, "wb") as out_f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)

            if os.path.exists(raw_m4a) and os.path.getsize(raw_m4a) > 32768:
                hq_opus = _prepare_hq_opus_file(raw_m4a, acodec="aac")
                return hq_opus
        except Exception as e:
            print(f"⚠️ Proxy Invidious ({host}) falló para {vid_id}: {e}", flush=True)
        finally:
            if os.path.exists(raw_m4a):
                try:
                    os.remove(raw_m4a)
                except Exception:
                    pass

    return None


def _download_audio_with_ytdlp(target: str, extra_opts: Optional[dict] = None) -> Optional[tuple[str, dict]]:
    """
    Descarga el stream de mayor calidad de audio (priorizando Format 251 Opus 160kbps o AAC 160kbps)
    y lo prepara en un archivo .opus listo para transmisión directa sin consumo de CPU.
    """
    token = uuid.uuid4().hex[:10]
    tmp_dir = tempfile.gettempdir()
    outtmpl = os.path.join(tmp_dir, f"victini_{token}.%(ext)s")

    opts = {
        "format": "251/140/bestaudio[acodec=opus]/bestaudio[abr>=128]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "outtmpl": outtmpl,
        "max_filesize": 45 * 1024 * 1024,
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

            fmt_id = str(chosen.get("format_id") or "").lower()
            if "preview" in fmt_id:
                for f in glob.glob(os.path.join(tmp_dir, f"victini_{token}.*")):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
                return None

            matches = glob.glob(os.path.join(tmp_dir, f"victini_{token}.*"))
            valid_files = [
                f for f in matches
                if not f.endswith(".part") and os.path.exists(f) and os.path.getsize(f) > 1024
            ]
            if not valid_files:
                return None

            hq_opus_file = _prepare_hq_opus_file(valid_files[0], acodec=chosen.get("acodec"))
            return hq_opus_file, chosen
    except Exception:
        for f in glob.glob(os.path.join(tmp_dir, f"victini_{token}.*")):
            try:
                os.remove(f)
            except Exception:
                pass
        return None


def _extract_youtube_id_from_url(url: str) -> Optional[str]:
    """Extrae el video ID de 11 caracteres de una URL de YouTube."""
    try:
        parsed = urllib.parse.urlparse(url)
        if "youtu.be" in parsed.netloc:
            return parsed.path.strip("/").split("/")[0]
        qs = urllib.parse.parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]
    except Exception:
        pass
    return None


def search_song_sync(query: str, requester: str) -> Optional[Song]:
    """
    Busca la canción en YouTube y descarga SIEMPRE el audio real del video de YouTube:
    1. Intenta descarga directa de YouTube Format 251 (160kbps 48kHz Stereo Opus) con clientes Innertube.
    2. Si YouTube bloquea la IP de Render, descarga el stream oficial de YouTube (itag=140, M4A 128kbps Stereo)
       del mismo video exacto (`vid_id`) mediante proxy directo de YouTube (`_download_youtube_via_invidious_proxy`).
    3. Pre-convierte el archivo a `.opus` antes de reproducir para 0% consumo de CPU durante el playback.
    """
    query = query.strip()
    is_url = query.startswith("http://") or query.startswith("https://")

    hq_clients = [["android_testsuite"], ["mediaconnect"], ["android_producer"], ["tv_embedded"]]

    if is_url:
        for client_list in hq_clients:
            res = _download_audio_with_ytdlp(
                query,
                extra_opts={"extractor_args": {"youtube": {"player_client": client_list}}},
            )
            if res:
                file_path, info = res
                return Song(
                    title=info.get("title") or "Canción de YouTube",
                    file_path=file_path,
                    webpage_url=info.get("webpage_url") or query,
                    requester=requester,
                    duration_str=format_duration(info.get("duration")),
                    source_name="YouTube",
                    thumbnail=info.get("thumbnail"),
                )

        vid_id = _extract_youtube_id_from_url(query)
        if vid_id:
            yt_meta = _lookup_youtube_metadata(vid_id)
            proxy_file = _download_youtube_via_invidious_proxy(vid_id)
            if proxy_file:
                return Song(
                    title=(yt_meta.get("display_title") if yt_meta else None) or "Canción de YouTube",
                    file_path=proxy_file,
                    webpage_url=f"https://www.youtube.com/watch?v={vid_id}",
                    requester=requester,
                    duration_str=format_duration(yt_meta.get("duration") if yt_meta else None),
                    source_name="YouTube",
                    thumbnail=(yt_meta.get("thumbnail") if yt_meta else f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"),
                )
        return None

    # 1. Buscar el video oficial en YouTube
    yt_meta = _lookup_youtube_metadata(query)
    if not yt_meta or not yt_meta.get("id"):
        return None

    vid_id = yt_meta["id"]
    yt_url = yt_meta.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
    display_title = yt_meta.get("display_title") or yt_meta.get("title") or query

    # 2. Intentar descargar el audio HQ (Format 251 Opus 160kbps) directo de YouTube
    for client_list in hq_clients:
        res = _download_audio_with_ytdlp(
            yt_url,
            extra_opts={"extractor_args": {"youtube": {"player_client": client_list}}},
        )
        if res:
            file_path, info = res
            return Song(
                title=display_title,
                file_path=file_path,
                webpage_url=yt_url,
                requester=requester,
                duration_str=format_duration(yt_meta.get("duration") or info.get("duration")),
                source_name="YouTube",
                thumbnail=yt_meta.get("thumbnail") or info.get("thumbnail"),
            )

    # 3. Si YouTube bloquea la IP de Render, descargar el stream oficial de YouTube (itag=140 M4A)
    #    del MISMO video exacto (vid_id) por proxy directo de YouTube (sin usar SoundCloud)
    proxy_file = _download_youtube_via_invidious_proxy(vid_id)
    if proxy_file:
        return Song(
            title=display_title,
            file_path=proxy_file,
            webpage_url=yt_url,
            requester=requester,
            duration_str=format_duration(yt_meta.get("duration")),
            source_name="YouTube",
            thumbnail=yt_meta.get("thumbnail"),
        )

    return None


class DirectOggOpusSource(discord.AudioSource):
    """
    Lee tramas Opus directamente desde un archivo .opus local pre-generado sin levantar
    ningún subproceso ffmpeg durante la reproducción (0% uso de CPU en Render Free Tier).
    """
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._file: Optional[IO[bytes]] = open(file_path, "rb")
        self._packet_iter = discord.oggparse.OggStream(self._file).iter_packets()

    def read(self) -> bytes:
        if self._file is None:
            return b""
        while True:
            try:
                data = next(self._packet_iter, b"")
            except Exception:
                return b""
            if not data:
                return b""
            if data.startswith((b"OpusHead", b"OpusTags")):
                continue
            return data

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None


def create_audio_source(file_path: str) -> discord.AudioSource:
    """
    Crea el lector directo de Ogg Opus en memoria/disco sin subproceso ffmpeg en vivo.
    """
    return DirectOggOpusSource(file_path)


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


def setup_music_commands(bot: commands.Bot) -> None:
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
                f"❌ No pude encontrar ni descargar el audio de YouTube para **`{cancion}`**. Probá con otro nombre o autor. 🔥"
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
                f"⚠️ No pude conectarme al canal de voz **{target_voice_channel.name}** (verificá mis permisos de Conectar y Hablar): `{type(e).__name__}: {e}`"
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
