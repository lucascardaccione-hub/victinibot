from datetime import datetime, timezone
import html
import json
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from database import get_bot_state, set_bot_state

ENTRETURNOS_CHANNEL_ID = "UCX_KX9tFeQ8TbIfw6Uf_LUg"
ENTRETURNOS_HANDLE = "@EntreTurnosLIVE"
_USER_AGENT = "Mozilla/5.0 (compatible; VictiniBot-SNAP/1.0)"
_MAX_SEEN_IDS = 200
_MAX_VIDEO_AGE_SECONDS = 6 * 3600  # Solo anunciar videos estrenados en las últimas 6 horas
_check_lock = threading.Lock()


def _parse_iso_ts(iso_str: str) -> float:
    if not iso_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str.strip().replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _load_seen_ids(state_key: str, legacy_key: Optional[str] = None) -> List[str]:
    raw = get_bot_state(state_key)
    seen: List[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                seen = [str(x) for x in parsed if x]
        except Exception:
            seen = []
    if legacy_key:
        legacy_val = get_bot_state(legacy_key)
        if legacy_val and legacy_val not in seen:
            seen.append(legacy_val)
    return seen


def _save_seen_ids(state_key: str, seen: List[str]) -> None:
    trimmed = seen[-_MAX_SEEN_IDS:]
    set_bot_state(state_key, json.dumps(trimmed, ensure_ascii=False))


def fetch_rss_entries() -> List[dict]:
    """Consulta el feed RSS oficial de YouTube y retorna todas las entradas ordenadas por fecha de publicación."""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ENTRETURNOS_CHANNEL_ID}"
    req = urllib.request.Request(rss_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entries: List[dict] = []
    for entry in root.findall("atom:entry", ns):
        vid = (entry.findtext("yt:videoId", namespaces=ns) or "").strip()
        if not vid:
            continue
        title = (entry.findtext("atom:title", namespaces=ns) or "Nuevo video en EntreTurnos").strip()
        published = (entry.findtext("atom:published", namespaces=ns) or "").strip()
        entries.append(
            {
                "video_id": vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "published": published,
                "published_ts": _parse_iso_ts(published),
            }
        )
    entries.sort(key=lambda e: e["published_ts"], reverse=True)
    return entries


def fetch_live_stream() -> Optional[dict]:
    """Verifica si @EntreTurnosLIVE está transmitiendo en vivo en este momento."""
    live_url = f"https://www.youtube.com/channel/{ENTRETURNOS_CHANNEL_ID}/live"
    req = urllib.request.Request(live_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        page = resp.read().decode("utf-8", "ignore")

    if '"isLiveNow":true' not in page and '"isLive":true' not in page:
        return None

    can_match = re.search(
        r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]+)"',
        page,
    )
    vid_match = can_match or re.search(r'"videoId":"([a-zA-Z0-9_-]{11})"', page)
    if not vid_match:
        return None

    vid = vid_match.group(1)
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', page)
    title = html.unescape(title_match.group(1)).strip() if title_match else "Directo en vivo de EntreTurnos"

    return {
        "video_id": vid,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def check_entreturnos_updates() -> List[dict]:
    """
    Revisa si @EntreTurnosLIVE inició un directo o estrenó un video nuevo.
    Usa historial persistente de IDs vistos + marca de tiempo de publicación para
    evitar re-enviar videos viejos cuando el RSS cambia de orden o tras un estreno/directo.
    """
    with _check_lock:
        events: List[dict] = []
        seen_videos = _load_seen_ids("yt_seen_video_ids", legacy_key="yt_last_video_id")
        seen_lives = _load_seen_ids("yt_seen_live_ids", legacy_key="yt_last_live_id")

        # 1. Revisar si está EN VIVO ahora mismo
        try:
            live_info = fetch_live_stream()
            if live_info:
                vid = live_info["video_id"]
                if vid not in seen_lives:
                    seen_lives.append(vid)
                    _save_seen_ids("yt_seen_live_ids", seen_lives)
                    set_bot_state("yt_last_live_id", vid)
                    if vid not in seen_videos:
                        seen_videos.append(vid)
                        _save_seen_ids("yt_seen_video_ids", seen_videos)
                        set_bot_state("yt_last_video_id", vid)
                    events.append({"kind": "live", **live_info})
        except Exception as e:
            print(f"⚠️ Error consultando directo de YouTube ({ENTRETURNOS_HANDLE}): {e}", flush=True)

        # 2. Revisar feed RSS para detectar SOLO estrenos/videos genuinamente nuevos
        try:
            entries = fetch_rss_entries()
            if entries:
                last_pub_raw = get_bot_state("yt_last_published_ts")
                last_pub_ts = float(last_pub_raw) if last_pub_raw else 0.0
                newest_ts = max(e["published_ts"] for e in entries)

                # Si nunca se inicializó la lista completa (primera vez o migración desde versión anterior),
                # sembramos TODOS los videos actuales del RSS sin spamear ninguno viejo.
                if not get_bot_state("yt_seen_video_ids"):
                    for e in entries:
                        if e["video_id"] not in seen_videos:
                            seen_videos.append(e["video_id"])
                    _save_seen_ids("yt_seen_video_ids", seen_videos)
                    set_bot_state("yt_last_video_id", entries[0]["video_id"])
                    if newest_ts > last_pub_ts:
                        set_bot_state("yt_last_published_ts", str(newest_ts))
                else:
                    now_ts = time.time()
                    # Buscar solo videos nuevos no vistos, publicados recientemente y más nuevos que last_pub_ts
                    new_entries = [
                        e
                        for e in entries
                        if e["video_id"] not in seen_videos
                        and e["video_id"] not in seen_lives
                        and e["published_ts"] > last_pub_ts
                        and (now_ts - e["published_ts"]) <= _MAX_VIDEO_AGE_SECONDS
                    ]
                    # Registrar todos los IDs presentes en el RSS para no re-detectarlos si el orden fluctúa
                    added_any = False
                    for e in entries:
                        if e["video_id"] not in seen_videos:
                            seen_videos.append(e["video_id"])
                            added_any = True
                    if added_any:
                        _save_seen_ids("yt_seen_video_ids", seen_videos)
                    if newest_ts > last_pub_ts:
                        set_bot_state("yt_last_published_ts", str(newest_ts))
                    set_bot_state("yt_last_video_id", entries[0]["video_id"])

                    # Anunciar en orden cronológico (del más antiguo al más reciente entre los nuevos)
                    for e in sorted(new_entries, key=lambda x: x["published_ts"]):
                        events.append({"kind": "video", **e})
        except Exception as e:
            print(f"⚠️ Error consultando RSS de YouTube ({ENTRETURNOS_HANDLE}): {e}", flush=True)

        return events
