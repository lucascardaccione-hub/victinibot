import asyncio
from concurrent.futures import ThreadPoolExecutor
import glob
import json
import os
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
    source_name: str = "YouTube HQ"
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


def _prepare_hq_opus_file(raw_file_path: str) -> str:
    """
    Convierte el archivo descargado a un contenedor Ogg Opus (.opus) de alta fidelidad (128kbps CVBR)
    ANTES de iniciar la reproducción:
    - Usa -fflags +genpts para timestamps limpios sin deformar el pitch (sin aresample=async).
    - Usa volume=-3.5dB con limitador suave (alimiter=limit=0.92) para sonido potente, nítido y con 0% clipping.
    - Usa 128kbps Constrained VBR (-vbr constrained) + FEC (-fec true -packet_loss 10) para máxima claridad de agudos y graves.
    """
    base, _ = os.path.splitext(raw_file_path)
    opus_path = f"{base}_hq.opus"

    cmd_encode = [
        FFMPEG_EXECUTABLE,
        "-y",
        "-fflags", "+genpts",
        "-i", raw_file_path,
        "-map_metadata", "-1",
        "-vn",
        "-af", "volume=-3.5dB,alimiter=limit=0.92:level=false:attack=5:release=50",
        "-c:a", "libopus",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "128k",
        "-vbr", "constrained",
        "-compression_level", "3",
        "-threads", "0",
        "-frame_duration", "20",
        "-application", "audio",
        "-fec", "true",
        "-packet_loss", "10",
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
    Busca en YouTube (ytsearch1:) en modo ultrarrápido (extract_flat) para obtener título oficial,
    canal/artista, duración y miniatura.
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
                        with urllib.request.urlopen(req, timeout=3) as resp:
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

    return None


def _lookup_sc_candidates(query: str) -> List[dict]:
    """Busca los candidatos de audio en paralelo a la consulta de metadatos de YouTube."""
    flat_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "logger": _QuietYdlLogger(),
    }
    candidates = []
    try:
        with yt_dlp.YoutubeDL(flat_opts) as ydl:
            info = ydl.extract_info(f"scsearch6:{query}", download=False)
            for e in ((info or {}).get("entries") or []):
                if e and e.get("url"):
                    dur = e.get("duration") or 0
                    if dur == 0 or dur > 35:
                        candidates.append(e)
    except Exception:
        pass
    return candidates


def _download_audio_fast(target: str, extra_opts: Optional[dict] = None) -> Optional[tuple[str, dict]]:
    """
    Descarga el stream de 160kbps con descarga paralela de fragmentos (concurrent_fragment_downloads=8)
    y fixup='never' (ya que _prepare_hq_opus_file procesa el archivo directamente con ffmpeg en un solo paso).
    """
    token = uuid.uuid4().hex[:10]
    tmp_dir = tempfile.gettempdir()
    outtmpl = os.path.join(tmp_dir, f"victini_{token}.%(ext)s")

    opts = {
        "format": "http_mp3_1_0/hls_aac_160k/251/bestaudio[abr>=128]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "outtmpl": outtmpl,
        "concurrent_fragment_downloads": 8,
        "fixup": "never",
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

            hq_opus_file = _prepare_hq_opus_file(valid_files[0])
            return hq_opus_file, chosen
    except Exception:
        for f in glob.glob(os.path.join(tmp_dir, f"victini_{token}.*")):
            try:
                os.remove(f)
            except Exception:
                pass
        return None


def _score_sc_candidate(entry: dict, yt_meta: Optional[dict], query: str) -> float:
    """
    Puntúa cada resultado candidato dando máxima prioridad a que coincidan las palabras
    de la búsqueda del usuario, el artista/canal oficial de YouTube y la duración.
    """
    score = 0.0
    sc_title_only = (entry.get("title") or "").lower()
    sc_uploader = (entry.get("uploader") or "").lower()
    sc_full = f"{sc_title_only} {sc_uploader}"
    sc_dur = entry.get("duration") or 0

    query_words = [w for w in query.lower().split() if len(w) >= 2]
    matched_q_words = sum(1 for w in query_words if w in sc_full)
    if query_words and matched_q_words == len(query_words):
        score += 180.0
    else:
        score += matched_q_words * 35.0

    if yt_meta:
        yt_dur = yt_meta.get("duration") or 0
        yt_channel = (yt_meta.get("channel") or "").lower()
        yt_title = (yt_meta.get("title") or "").lower()

        if yt_channel:
            yt_ch_clean = "".join(c for c in yt_channel if c.isalnum())
            sc_full_clean = "".join(c for c in sc_full if c.isalnum())
            if yt_channel in sc_full or (len(yt_ch_clean) >= 3 and yt_ch_clean in sc_full_clean):
                score += 120.0

        if yt_title and yt_title in sc_title_only:
            score += 70.0

        if yt_dur > 0 and sc_dur > 0:
            diff = abs(sc_dur - yt_dur)
            if diff <= 5:
                score += 60.0
            elif diff <= 15:
                score += 30.0
            elif diff > 60:
                score -= 50.0

    for bad_tag in ("slowed", "reverb", "nightcore", "8d audio", "karaoke"):
        if bad_tag in sc_title_only and bad_tag not in query.lower():
            score -= 80.0

    return score


def search_song_sync(query: str, requester: str) -> Optional[Song]:
    """
    Búsqueda y preparación ultrarrápida (~2 segundos):
    1. Ejecuta en PARALELO la búsqueda de ficha oficial de YouTube y la búsqueda de streams HQ (160kbps).
    2. Descarga con 8 hilos paralelos de fragmentos y codifica en un único paso a 128kbps CVBR Opus.
    """
    query = query.strip()
    is_url = query.startswith("http://") or query.startswith("https://")

    if is_url:
        res = _download_audio_fast(
            query,
            extra_opts={"extractor_args": {"youtube": {"player_client": ["android_testsuite"]}}},
        )
        if not res:
            res = _download_audio_fast(query)
        if res:
            file_path, info = res
            return Song(
                title=info.get("title") or "Canción",
                file_path=file_path,
                webpage_url=info.get("webpage_url") or query,
                requester=requester,
                duration_str=format_duration(info.get("duration")),
                source_name="YouTube HQ",
                thumbnail=info.get("thumbnail"),
            )
        return None

    # 1. Ejecutar en PARALELO la búsqueda de metadatos en YouTube y la búsqueda de streams HQ
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_yt = pool.submit(_lookup_youtube_metadata, query)
        fut_sc = pool.submit(_lookup_sc_candidates, query)
        yt_meta = fut_yt.result()
        candidates = fut_sc.result()

    # Si no hubo candidatos con la query cruda pero YouTube encontró artista + título, buscar con artista + título
    if not candidates and yt_meta and yt_meta.get("channel") and yt_meta.get("title"):
        ch = yt_meta["channel"]
        ti = yt_meta["title"]
        enriched = f"{ch} {ti}" if ch.lower() not in ti.lower() else ti
        candidates = _lookup_sc_candidates(enriched)

    candidates.sort(key=lambda e: _score_sc_candidate(e, yt_meta, query), reverse=True)

    yt_url = yt_meta.get("url") if yt_meta else None
    display_title = (yt_meta.get("display_title") if yt_meta else None) or query

    # 2. Descargar el mejor candidato HQ con 8 fragmentos en paralelo
    for entry in candidates[:4]:
        res = _download_audio_fast(entry["url"])
        if res:
            file_path, fb_info = res
            if (fb_info.get("duration") or 100) > 35:
                final_title = display_title if yt_meta else (fb_info.get("title") or query)
                webpage_url = yt_url or fb_info.get("webpage_url") or "https://www.youtube.com"
                duration_str = format_duration(fb_info.get("duration") or (yt_meta.get("duration") if yt_meta else None))
                thumbnail = (yt_meta.get("thumbnail") if yt_meta else None) or fb_info.get("thumbnail")
                return Song(
                    title=final_title,
                    file_path=file_path,
                    webpage_url=webpage_url,
                    requester=requester,
                    duration_str=duration_str,
                    source_name="YouTube HQ",
                    thumbnail=thumbnail,
                )
            try:
                os.remove(file_path)
            except Exception:
                pass

    # 3. Respaldo directo de YouTube si no estuvo en el catálogo HQ
    if yt_url:
        res = _download_audio_fast(
            yt_url,
            extra_opts={"extractor_args": {"youtube": {"player_client": ["android_testsuite"]}}},
        )
        if res:
            file_path, info = res
            return Song(
                title=display_title,
                file_path=file_path,
                webpage_url=yt_url,
                requester=requester,
                duration_str=format_duration(yt_meta.get("duration") or info.get("duration")),
                source_name="YouTube HQ",
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

    # Enviar primero el embed de reproducción para que el hilo de audio arranque sin competencia de CPU
    if state.text_channel:
        embed = build_now_playing_embed(next_song)
        view = MusicControlView(guild_id=guild_id, loop=loop)
        try:
            await state.text_channel.send(embed=embed, view=view)
        except Exception as e:
            print(f"⚠️ No se pudo enviar embed de reproducción: {e}", flush=True)

    def _after_playback(error: Optional[Exception]):
        if error:
            print(f"⚠️ Error en reproducción de voz: {error}", flush=True)
        cleanup_song_file(next_song)
        asyncio.run_coroutine_threadsafe(play_next(guild_id, loop), loop)

    vc.play(source, after=_after_playback)


def setup_music_commands(bot: commands.Bot) -> None:
    """Registra los comandos slash de música (/victiniplay, /victiniskip, /victinistop, /victinicola) en el árbol del bot."""

    @bot.tree.command(
        name="victiniplay",
        description="Victini entra a tu canal de voz al instante y reproduce la canción que pidas 🎶🔥",
    )
    @app_commands.describe(cancion="Nombre de la canción o link que querés escuchar")
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

        state = get_guild_state(interaction.guild.id)
        state.text_channel = interaction.channel

        # Conectar al canal de voz EN PARALELO mientras se busca y descarga la canción
        async def _ensure_voice_connected() -> Optional[discord.VoiceClient]:
            vc = interaction.guild.voice_client
            if vc is None or not vc.is_connected():
                vc = await target_voice_channel.connect(timeout=15.0, self_deaf=True)
            elif vc.channel.id != target_voice_channel.id:
                await vc.move_to(target_voice_channel)
            state.voice_client = vc
            return vc

        voice_task = asyncio.create_task(_ensure_voice_connected())
        search_task = asyncio.to_thread(
            search_song_sync,
            cancion,
            interaction.user.display_name,
        )

        try:
            vc = await voice_task
        except Exception as e:
            song_cleanup = await search_task
            cleanup_song_file(song_cleanup)
            await interaction.followup.send(
                f"⚠️ No pude conectarme al canal de voz **{target_voice_channel.name}** (verificá mis permisos de Conectar y Hablar): `{type(e).__name__}: {e}`"
            )
            return

        song = await search_task

        if song is None:
            await interaction.followup.send(
                f"❌ No pude encontrar ni descargar el audio para **`{cancion}`**. Probá con otro nombre o autor. 🔥"
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
