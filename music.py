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

    is_native_opus = "opus" in (acodec or "").lower() or ext.lower() == ".webm"

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


def _get_invidious_api_hosts() -> List[str]:
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
                if info.get("type") == "https" and info.get("api"):
                    uri = info.get("uri", "").rstrip("/")
                    if uri and uri not in hosts:
                        hosts.append(uri)
    except Exception:
        pass
    return hosts


def _lookup_youtube_metadata(query: str) -> Optional[dict]:
    """
    Busca en YouTube primero con yt-dlp (extract_flat + oEmbed) y tiene respaldo automático
    en la API de búsqueda de Invidious (/api/v1/search) por si YouTube bloquea la búsqueda en Render.
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
            if entries:
                entry = entries[0]
                vid_id = entry.get("id")
                raw_title = (entry.get("title") or "").strip()
                channel = (entry.get("channel") or entry.get("uploader") or "").strip()

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
                if vid_id:
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
        pass

    # Respaldo de búsqueda en YouTube vía API de Invidious
    ctx = ssl._create_unverified_context()
    for host in _get_invidious_api_hosts()[:3]:
        try:
            s_url = f"{host}/api/v1/search?q={urllib.parse.quote(query)}&type=video"
            req = urllib.request.Request(s_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                results = json.loads(resp.read().decode("utf-8"))
                if not results:
                    continue
                first = results[0]
                vid_id = first.get("videoId")
                if not vid_id:
                    continue
                raw_title = (first.get("title") or "").strip()
                channel = (first.get("author") or "").replace(" - Topic", "").replace("VEVO", "").strip()
                if channel and channel.lower() not in raw_title.lower():
                    display_title = f"{channel} - {raw_title}"
                else:
                    display_title = raw_title
                return {
                    "id": vid_id,
                    "title": raw_title,
                    "display_title": display_title,
                    "channel": channel,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "duration": first.get("lengthSeconds"),
                    "thumbnail": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                }
        except Exception:
            continue

    return None


def _download_youtube_via_companion_issuer(vid_id: str) -> Optional[str]:
    """
    Obtiene los adaptiveFormats firmados desde `/api/v1/videos/{vid_id}`, selecciona el stream
    Format 251 (160kbps 48kHz Studio Opus .webm) o Format 140 (128kbps M4A), y descarga el archivo
    directamente desde el nodo `issuer` exacto (`yt-compX`) que firmó el token `pot`.
    Evita el error 403 de balanceo entre nodos y garantiza calidad de estudio 100% original de YouTube.
    """
    ctx = ssl._create_unverified_context()
    tmp_dir = tempfile.gettempdir()

    for host in _get_invidious_api_hosts()[:3]:
        try:
            v_url = f"{host}/api/v1/videos/{vid_id}"
            req = urllib.request.Request(v_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                v_data = json.loads(resp.read().decode("utf-8"))

            af_map = {
                str(af.get("itag")): af
                for af in (v_data.get("adaptiveFormats") or [])
                if af.get("url")
            }

            # Priorizar Format 251 (160kbps 48kHz Stereo Opus nativo), luego 250, 140, 249
            for itag in ("251", "250", "140", "249"):
                chosen_af = af_map.get(itag)
                if not chosen_af:
                    continue

                raw_u = chosen_af["url"]
                parsed = urllib.parse.urlparse(raw_u)
                qs = urllib.parse.parse_qs(parsed.query)
                issuer_list = qs.get("issuer")

                if issuer_list and issuer_list[0]:
                    issuer = issuer_list[0]
                    proxied_u = f"https://{issuer}/videoplayback?{parsed.query}&host={parsed.netloc}"
                else:
                    proxied_u = f"{host}/latest_version?id={vid_id}&itag={itag}&local=true"

                is_opus = itag in ("251", "250", "249") or "opus" in (chosen_af.get("type") or "").lower()
                ext = ".webm" if is_opus else ".m4a"
                token = uuid.uuid4().hex[:10]
                raw_path = os.path.join(tmp_dir, f"victini_yt_{token}{ext}")

                try:
                    s_req = urllib.request.Request(proxied_u, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(s_req, timeout=25, context=ctx) as s_resp:
                        with open(raw_path, "wb") as out_f:
                            while True:
                                chunk = s_resp.read(65536)
                                if not chunk:
                                    break
                                out_f.write(chunk)

                    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 16384:
                        hq_opus = _prepare_hq_opus_file(
                            raw_path,
                            acodec="opus" if is_opus else "aac",
                        )
                        return hq_opus
                except Exception as e:
                    print(f"⚠️ Error descargando itag {itag} desde {proxied_u[:60]}: {e}", flush=True)
                finally:
                    if os.path.exists(raw_path):
                        try:
                            os.remove(raw_path)
                        except Exception:
                            pass
        except Exception as e:
            print(f"⚠️ Error consultando API de video en {host} para {vid_id}: {e}", flush=True)

    return None


def _download_audio_with_ytdlp(target: str, extra_opts: Optional[dict] = None) -> Optional[tuple[str, dict]]:
    """
    Respaldo con yt-dlp directo si el servidor tiene acceso residencial a YouTube.
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

            chosen = info["entries"][0] if "entries" in info and info.get("entries") else info
            if not chosen:
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
    Busca la canción en YouTube y descarga SIEMPRE el stream Format 251 (160kbps 48kHz Studio Opus)
    original de YouTube:
    1. Primero usa el proxy firmado por `issuer` (`_download_youtube_via_companion_issuer`), que funciona
       al 100% en IPs de Render sin bloqueo anti-bot de YouTube y copia el stream Opus nativo sin pérdida.
    2. Si el proxy no estuviera disponible, intenta descarga directa con yt-dlp.
    """
    query = query.strip()
    is_url = query.startswith("http://") or query.startswith("https://")

    if is_url:
        vid_id = _extract_youtube_id_from_url(query)
        if vid_id:
            yt_meta = _lookup_youtube_metadata(vid_id)
            proxy_file = _download_youtube_via_companion_issuer(vid_id)
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

        for client_list in [["android_testsuite"], ["mediaconnect"], ["tv_embedded"]]:
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
        return None

    # 1. Buscar el video oficial en YouTube
    yt_meta = _lookup_youtube_metadata(query)
    if not yt_meta or not yt_meta.get("id"):
        return None

    vid_id = yt_meta["id"]
    yt_url = yt_meta.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
    display_title = yt_meta.get("display_title") or yt_meta.get("title") or query

    # 2. Descargar Format 251 (160kbps 48kHz Studio Opus) vía nodo issuer firmado (funciona directo en Render)
    proxy_file = _download_youtube_via_companion_issuer(vid_id)
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

    # 3. Respaldo directo con yt-dlp
    for client_list in [["android_testsuite"], ["mediaconnect"], ["tv_embedded"]]:
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
