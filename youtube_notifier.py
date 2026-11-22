import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from database import get_bot_state, set_bot_state

ENTRETURNOS_CHANNEL_ID = "UCX_KX9tFeQ8TbIfw6Uf_LUg"
ENTRETURNOS_HANDLE = "@EntreTurnosLIVE"
_USER_AGENT = "Mozilla/5.0 (compatible; VictiniBot-SNAP/1.0)"


def fetch_latest_rss_video() -> Optional[dict]:
    """Consulta el feed RSS oficial de YouTube para obtener el último video/contenido subido por @EntreTurnosLIVE."""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ENTRETURNOS_CHANNEL_ID}"
    req = urllib.request.Request(rss_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None

    vid = entry.findtext("yt:videoId", namespaces=ns)
    title = entry.findtext("atom:title", namespaces=ns) or "Nuevo video en EntreTurnos"
    published = entry.findtext("atom:published", namespaces=ns) or ""
    if not vid:
        return None

    return {
        "video_id": vid.strip(),
        "title": title.strip(),
        "url": f"https://www.youtube.com/watch?v={vid.strip()}",
        "published": published.strip(),
    }


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
    Revisa si @EntreTurnosLIVE inició un directo o publicó un nuevo video/short.
    Persiste los IDs ya notificados en DB para evitar avisos duplicados tras reinicios.
    """
    events: List[dict] = []
    just_announced_live_id: Optional[str] = None

    # 1. Revisar si está EN VIVO ahora mismo
    try:
        live_info = fetch_live_stream()
        if live_info:
            last_live_id = get_bot_state("yt_last_live_id")
            if live_info["video_id"] != last_live_id:
                set_bot_state("yt_last_live_id", live_info["video_id"])
                # También marcar este ID como visto en RSS para no duplicar aviso como "video nuevo"
                set_bot_state("yt_last_video_id", live_info["video_id"])
                just_announced_live_id = live_info["video_id"]
                events.append({"kind": "live", **live_info})
    except Exception as e:
        print(f"⚠️ Error consultando directo de YouTube ({ENTRETURNOS_HANDLE}): {e}", flush=True)

    # 2. Revisar último video/short subido en RSS
    try:
        latest = fetch_latest_rss_video()
        if latest:
            last_vid = get_bot_state("yt_last_video_id")
            if last_vid is None:
                # Primera inicialización: guardar el último video existente sin spamear contenido viejo
                set_bot_state("yt_last_video_id", latest["video_id"])
            elif latest["video_id"] != last_vid and latest["video_id"] != just_announced_live_id:
                last_live_id = get_bot_state("yt_last_live_id")
                set_bot_state("yt_last_video_id", latest["video_id"])
                if latest["video_id"] != last_live_id:
                    events.append({"kind": "video", **latest})
    except Exception as e:
        print(f"⚠️ Error consultando RSS de YouTube ({ENTRETURNOS_HANDLE}): {e}", flush=True)

    return events
