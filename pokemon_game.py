import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import os
import random
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from typing import Optional, List, Callable, Awaitable

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from database import (
    get_pokeballs,
    consume_pokeball,
    get_pokemon_team,
    add_pokemon_to_team,
    replace_pokemon_in_team,
    add_pokemon_xp,
    get_user_stats,
)

CATCH_CHANNEL_NAME = "🎮𝑪𝑨𝑻𝑪𝑯"


def _norm_channel(name: str) -> str:
    norm = unicodedata.normalize("NFKC", name).lower().strip()
    return "".join(ch for ch in norm if ch.isascii() and ch.isalnum())


def is_catch_channel(channel: Optional[discord.abc.GuildChannel]) -> bool:
    """Verifica que el comando /catch se ejecute únicamente en el canal 🎮𝑪𝑨𝑻𝑪𝑯."""
    if channel is None or not hasattr(channel, "name"):
        return False
    if channel.name == CATCH_CHANNEL_NAME:
        return True
    return _norm_channel(channel.name) == _norm_channel(CATCH_CHANNEL_NAME)


@dataclass(frozen=True)
class PokemonSpecies:
    pokedex_id: int
    name: str
    rarity: str      # Común, Raro, Épico, Legendario
    ptype: str


RARITY_CONFIG = {
    "Común": {"weight": 55, "catch_rate": 0.80, "color": discord.Color.green(), "rgb": (46, 204, 113), "emoji": "🟢"},
    "Raro": {"weight": 27, "catch_rate": 0.55, "color": discord.Color.blue(), "rgb": (52, 152, 219), "emoji": "🔵"},
    "Épico": {"weight": 13, "catch_rate": 0.35, "color": discord.Color.purple(), "rgb": (155, 89, 182), "emoji": "🟣"},
    "Legendario": {"weight": 5, "catch_rate": 0.18, "color": discord.Color.gold(), "rgb": (241, 196, 15), "emoji": "🟡"},
}

POKEMON_POOL: List[PokemonSpecies] = [
    # Comunes (80% captura)
    PokemonSpecies(25, "Pikachu", "Común", "Eléctrico ⚡"),
    PokemonSpecies(133, "Eevee", "Común", "Normal ⭐"),
    PokemonSpecies(4, "Charmander", "Común", "Fuego 🔥"),
    PokemonSpecies(1, "Bulbasaur", "Común", "Planta 🌿"),
    PokemonSpecies(7, "Squirtle", "Común", "Agua 💧"),
    PokemonSpecies(39, "Jigglypuff", "Común", "Hada 🌸"),
    PokemonSpecies(52, "Meowth", "Común", "Normal ⭐"),
    PokemonSpecies(54, "Psyduck", "Común", "Agua 💧"),
    PokemonSpecies(58, "Growlithe", "Común", "Fuego 🔥"),
    PokemonSpecies(92, "Gastly", "Común", "Fantasma 👻"),
    PokemonSpecies(129, "Magikarp", "Común", "Agua 💧"),
    PokemonSpecies(143, "Snorlax", "Común", "Normal ⭐"),
    PokemonSpecies(252, "Treecko", "Común", "Planta 🌿"),
    PokemonSpecies(255, "Torchic", "Común", "Fuego 🔥"),
    PokemonSpecies(258, "Mudkip", "Común", "Agua 💧"),
    PokemonSpecies(393, "Piplup", "Común", "Agua 💧"),
    PokemonSpecies(447, "Riolu", "Común", "Lucha 🥊"),
    PokemonSpecies(570, "Zorua", "Común", "Siniestro 🌑"),
    # Raros (55% captura)
    PokemonSpecies(6, "Charizard", "Raro", "Fuego / Volador 🔥"),
    PokemonSpecies(9, "Blastoise", "Raro", "Agua 💧"),
    PokemonSpecies(3, "Venusaur", "Raro", "Planta / Veneno 🌿"),
    PokemonSpecies(94, "Gengar", "Raro", "Fantasma / Veneno 👻"),
    PokemonSpecies(59, "Arcanine", "Raro", "Fuego 🔥"),
    PokemonSpecies(130, "Gyarados", "Raro", "Agua / Volador 💧"),
    PokemonSpecies(131, "Lapras", "Raro", "Agua / Hielo ❄️"),
    PokemonSpecies(197, "Umbreon", "Raro", "Siniestro 🌑"),
    PokemonSpecies(196, "Espeon", "Raro", "Psíquico 🔮"),
    PokemonSpecies(212, "Scizor", "Raro", "Bicho / Acero ⚙️"),
    PokemonSpecies(282, "Gardevoir", "Raro", "Psíquico / Hada 🌸"),
    PokemonSpecies(359, "Absol", "Raro", "Siniestro 🌑"),
    PokemonSpecies(448, "Lucario", "Raro", "Lucha / Acero 🥊"),
    PokemonSpecies(468, "Togekiss", "Raro", "Hada / Volador 🌸"),
    # Épicos (35% captura)
    PokemonSpecies(149, "Dragonite", "Épico", "Dragón / Volador 🐉"),
    PokemonSpecies(248, "Tyranitar", "Épico", "Roca / Siniestro 🪨"),
    PokemonSpecies(373, "Salamence", "Épico", "Dragón / Volador 🐉"),
    PokemonSpecies(376, "Metagross", "Épico", "Acero / Psíquico ⚙️"),
    PokemonSpecies(445, "Garchomp", "Épico", "Dragón / Tierra 🐉"),
    PokemonSpecies(635, "Hydreigon", "Épico", "Siniestro / Dragón 🐉"),
    PokemonSpecies(637, "Volcarona", "Épico", "Bicho / Fuego 🔥"),
    PokemonSpecies(658, "Greninja", "Épico", "Agua / Siniestro 💧"),
    PokemonSpecies(778, "Mimikyu", "Épico", "Fantasma / Hada 👻"),
    PokemonSpecies(887, "Dragapult", "Épico", "Dragón / Fantasma 🐉"),
    # Legendarios / Míticos (18% captura)
    PokemonSpecies(150, "Mewtwo", "Legendario", "Psíquico 🔮"),
    PokemonSpecies(151, "Mew", "Legendario", "Psíquico 🔮"),
    PokemonSpecies(249, "Lugia", "Legendario", "Psíquico / Volador 🔮"),
    PokemonSpecies(250, "Ho-Oh", "Legendario", "Fuego / Volador 🔥"),
    PokemonSpecies(384, "Rayquaza", "Legendario", "Dragón / Volador 🐉"),
    PokemonSpecies(382, "Kyogre", "Legendario", "Agua 💧"),
    PokemonSpecies(383, "Groudon", "Legendario", "Tierra 🌋"),
    PokemonSpecies(483, "Dialga", "Legendario", "Acero / Dragón ⏳"),
    PokemonSpecies(484, "Palkia", "Legendario", "Agua / Dragón 🌌"),
    PokemonSpecies(487, "Giratina", "Legendario", "Fantasma / Dragón 👻"),
    PokemonSpecies(491, "Darkrai", "Legendario", "Siniestro 🌑"),
    PokemonSpecies(493, "Arceus", "Legendario", "Normal ✨"),
    PokemonSpecies(494, "Victini", "Legendario", "Psíquico / Fuego 🔥✌️"),
]

RARITY_POWER = {
    "Común": 1,
    "Raro": 4,
    "Épico": 7,
    "Legendario": 11,
}

# Tabla de evoluciones por nivel: pokedex_id -> siguiente evolución
EVOLUTION_TABLE = {
    1: {"min_level": 16, "to_id": 2, "to_name": "Ivysaur", "to_type": "Planta / Veneno 🌿", "to_rarity": "Raro"},
    2: {"min_level": 32, "to_id": 3, "to_name": "Venusaur", "to_type": "Planta / Veneno 🌿", "to_rarity": "Raro"},
    4: {"min_level": 16, "to_id": 5, "to_name": "Charmeleon", "to_type": "Fuego 🔥", "to_rarity": "Raro"},
    5: {"min_level": 36, "to_id": 6, "to_name": "Charizard", "to_type": "Fuego / Volador 🔥", "to_rarity": "Raro"},
    7: {"min_level": 16, "to_id": 8, "to_name": "Wartortle", "to_type": "Agua 💧", "to_rarity": "Raro"},
    8: {"min_level": 36, "to_id": 9, "to_name": "Blastoise", "to_type": "Agua 💧", "to_rarity": "Raro"},
    25: {"min_level": 22, "to_id": 26, "to_name": "Raichu", "to_type": "Eléctrico ⚡", "to_rarity": "Raro"},
    39: {"min_level": 20, "to_id": 40, "to_name": "Wigglytuff", "to_type": "Normal / Hada 🌸", "to_rarity": "Raro"},
    52: {"min_level": 24, "to_id": 53, "to_name": "Persian", "to_type": "Normal ⭐", "to_rarity": "Raro"},
    54: {"min_level": 26, "to_id": 55, "to_name": "Golduck", "to_type": "Agua 💧", "to_rarity": "Raro"},
    58: {"min_level": 24, "to_id": 59, "to_name": "Arcanine", "to_type": "Fuego 🔥", "to_rarity": "Raro"},
    92: {"min_level": 18, "to_id": 93, "to_name": "Haunter", "to_type": "Fantasma / Veneno 👻", "to_rarity": "Raro"},
    93: {"min_level": 32, "to_id": 94, "to_name": "Gengar", "to_type": "Fantasma / Veneno 👻", "to_rarity": "Raro"},
    129: {"min_level": 20, "to_id": 130, "to_name": "Gyarados", "to_type": "Agua / Volador 💧", "to_rarity": "Raro"},
    133: {"min_level": 20, "to_id": 197, "to_name": "Umbreon", "to_type": "Siniestro 🌑", "to_rarity": "Raro"},
    252: {"min_level": 16, "to_id": 253, "to_name": "Grovyle", "to_type": "Planta 🌿", "to_rarity": "Raro"},
    253: {"min_level": 36, "to_id": 254, "to_name": "Sceptile", "to_type": "Planta 🌿", "to_rarity": "Épico"},
    255: {"min_level": 16, "to_id": 256, "to_name": "Combusken", "to_type": "Fuego / Lucha 🔥", "to_rarity": "Raro"},
    256: {"min_level": 36, "to_id": 257, "to_name": "Blaziken", "to_type": "Fuego / Lucha 🔥", "to_rarity": "Épico"},
    258: {"min_level": 16, "to_id": 259, "to_name": "Marshtomp", "to_type": "Agua / Tierra 💧", "to_rarity": "Raro"},
    259: {"min_level": 36, "to_id": 260, "to_name": "Swampert", "to_type": "Agua / Tierra 💧", "to_rarity": "Épico"},
    393: {"min_level": 16, "to_id": 394, "to_name": "Prinplup", "to_type": "Agua 💧", "to_rarity": "Raro"},
    394: {"min_level": 36, "to_id": 395, "to_name": "Empoleon", "to_type": "Agua / Acero 💧", "to_rarity": "Épico"},
    447: {"min_level": 22, "to_id": 448, "to_name": "Lucario", "to_type": "Lucha / Acero 🥊", "to_rarity": "Raro"},
    570: {"min_level": 25, "to_id": 571, "to_name": "Zoroark", "to_type": "Siniestro 🌑", "to_rarity": "Épico"},
}


def get_artwork_url(pokedex_id: int, is_shiny: bool = False) -> str:
    if is_shiny:
        return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/shiny/{pokedex_id}.png"
    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pokedex_id}.png"


def roll_wild_pokemon() -> tuple[PokemonSpecies, bool]:
    """Elige un Pokémon aleatorio ponderado por rareza y con 5% de probabilidad Shiny."""
    weights = [RARITY_CONFIG[p.rarity]["weight"] for p in POKEMON_POOL]
    species = random.choices(POKEMON_POOL, weights=weights, k=1)[0]
    is_shiny = random.random() < 0.05
    return species, is_shiny


def _load_font(size: int, bold: bool = False):
    """Carga una fuente TTF disponible en Linux (Render) o Windows, con fallback seguro a Pillow."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _clean_text_for_card(text: str) -> str:
    """Limpia emojis de color fuera de BMP para evitar cuadros vacíos en fuentes TTF estándar."""
    return "".join(ch for ch in text if ord(ch) <= 0x024F).strip()


def _fetch_image_bytes(url: str) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VictiniBot-SNAP/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read()
    except Exception:
        return None


def build_team_card_png(
    username: str,
    level: int,
    pokeballs: int,
    team: List[dict],
    avatar_bytes: Optional[bytes] = None,
) -> bytes:
    """
    Genera la imagen PNG de la Ficha de Entrenador SNAP! (920x540) con el username,
    avatar circular, nivel, Pokéballs y los 6 slots del equipo Pokémon.
    """
    W, H = 920, 540
    img = Image.new("RGBA", (W, H), (16, 17, 36, 255))
    draw = ImageDraw.Draw(img)

    # Fondo degradado vertical oscuro con tono fuego SNAP!
    for y in range(H):
        r = int(15 + (y / H) * 18)
        g = int(16 + (y / H) * 10)
        b = int(34 + (y / H) * 20)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # Marco exterior naranja Victini
    draw.rounded_rectangle([10, 10, W - 11, H - 11], radius=22, outline=(255, 107, 53, 220), width=3)

    # Descargar en paralelo los artworks oficiales de los Pokémon del equipo
    sprite_bytes_list: List[Optional[bytes]] = []
    if team:
        urls = [get_artwork_url(m["pokedex_id"], m["is_shiny"]) for m in team[:6]]
        with ThreadPoolExecutor(max_workers=6) as pool:
            sprite_bytes_list = list(pool.map(_fetch_image_bytes, urls))

    # Fuentes
    f_title = _load_font(30, bold=True)
    f_sub = _load_font(18, bold=False)
    f_badge = _load_font(15, bold=True)
    f_name = _load_font(20, bold=True)
    f_small = _load_font(14, bold=False)

    # Header: Avatar circular + Username + Stats
    draw.rounded_rectangle([26, 26, W - 26, 122], radius=16, fill=(28, 30, 58, 240), outline=(255, 159, 28, 120), width=2)

    avatar_x, avatar_y, avatar_size = 42, 38, 72
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, avatar_size, avatar_size], fill=255)
            img.paste(av, (avatar_x, avatar_y), mask)
            draw.ellipse([avatar_x - 2, avatar_y - 2, avatar_x + avatar_size + 2, avatar_y + avatar_size + 2], outline=(255, 159, 28, 255), width=3)
        except Exception:
            draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(255, 107, 53, 255))
    else:
        draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(255, 107, 53, 255))

    clean_user = _clean_text_for_card(username) or "Entrenador"
    if len(clean_user) > 22:
        clean_user = clean_user[:21] + "..."
    draw.text((132, 40), clean_user, font=f_title, fill=(255, 255, 255, 255))
    draw.text(
        (132, 78),
        f"Nivel {level}   |   Pokeballs: {pokeballs}   |   Equipo: {len(team)}/6",
        font=f_sub,
        fill=(255, 185, 80, 255),
    )
    draw.text((W - 210, 62), "SNAP! TRAINER", font=f_badge, fill=(255, 107, 53, 220))

    # Grid 3x2 para los 6 Pokémon
    card_w, card_h = 276, 178
    gap_x, gap_y = 20, 18
    start_x, start_y = 26, 140

    for slot in range(6):
        col = slot % 3
        row = slot // 3
        x0 = start_x + col * (card_w + gap_x)
        y0 = start_y + row * (card_h + gap_y)
        x1 = x0 + card_w
        y1 = y0 + card_h

        if slot < len(team):
            mon = team[slot]
            r_color = RARITY_CONFIG.get(mon["rarity"], {"rgb": (150, 150, 150)})["rgb"]
            draw.rounded_rectangle(
                [x0, y0, x1, y1],
                radius=16,
                fill=(26, 28, 54, 245),
                outline=(*r_color, 230),
                width=2,
            )

            # Badge de nivel arriba a la izquierda + rareza arriba a la derecha
            p_lvl = int(mon.get("poke_level") or 1)
            draw.rounded_rectangle([x0 + 10, y0 + 10, x0 + 74, y0 + 32], radius=8, fill=(255, 107, 53, 230))
            draw.text((x0 + 18, y0 + 13), f"Nv. {p_lvl}", font=_load_font(12, bold=True), fill=(255, 255, 255, 255))

            rarity_txt = _clean_text_for_card(mon["rarity"]).upper()
            draw.rounded_rectangle([x1 - 104, y0 + 10, x1 - 10, y0 + 32], radius=8, fill=(*r_color, 210))
            draw.text((x1 - 96, y0 + 13), rarity_txt[:10], font=_load_font(12, bold=True), fill=(15, 16, 30, 255))

            if mon["is_shiny"]:
                draw.rounded_rectangle([x0 + 80, y0 + 10, x0 + 136, y0 + 32], radius=8, fill=(255, 215, 0, 230))
                draw.text((x0 + 86, y0 + 13), "SHINY", font=_load_font(12, bold=True), fill=(20, 20, 20, 255))

            # Sprite del Pokémon
            sp_bytes = sprite_bytes_list[slot] if slot < len(sprite_bytes_list) else None
            if sp_bytes:
                try:
                    sp = Image.open(io.BytesIO(sp_bytes)).convert("RGBA")
                    sp.thumbnail((104, 104), Image.Resampling.LANCZOS)
                    sx = x0 + (card_w - sp.width) // 2
                    sy = y0 + 24 + (98 - sp.height) // 2
                    img.paste(sp, (sx, sy), sp)
                except Exception:
                    pass

            # Nombre y tipo abajo
            mon_name = _clean_text_for_card(mon["name"])
            if mon["is_shiny"]:
                mon_name = f"* {mon_name}"
            mon_type = _clean_text_for_card(mon["ptype"])
            draw.text((x0 + 14, y1 - 52), mon_name[:20], font=f_name, fill=(255, 255, 255, 255))
            draw.text((x0 + 14, y1 - 26), mon_type[:28], font=f_small, fill=(185, 190, 215, 255))
        else:
            # Slot vacío con Pokéball sutil
            draw.rounded_rectangle(
                [x0, y0, x1, y1],
                radius=16,
                fill=(20, 22, 42, 180),
                outline=(65, 70, 105, 140),
                width=2,
            )
            cx, cy = x0 + card_w // 2, y0 + 76
            draw.ellipse([cx - 26, cy - 26, cx + 26, cy + 26], outline=(80, 86, 125, 160), width=3)
            draw.line([cx - 26, cy, cx + 26, cy], fill=(80, 86, 125, 160), width=3)
            draw.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=(20, 22, 42, 255), outline=(80, 86, 125, 160), width=3)
            draw.text((cx - 38, y1 - 38), "Slot vacio", font=f_small, fill=(110, 116, 155, 200))

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def build_welcome_card_png(
    username: str,
    member_count: int,
    avatar_bytes: Optional[bytes] = None,
) -> bytes:
    """
    Genera la imagen PNG de bienvenida para nuevos miembros de SNAP! (880x320)
    con la foto de perfil del usuario, su username y el artwork de Victini.
    """
    W, H = 880, 320
    img = Image.new("RGBA", (W, H), (16, 17, 36, 255))
    draw = ImageDraw.Draw(img)

    # Fondo degradado oscuro con tono fuego SNAP!
    for y in range(H):
        r = int(15 + (y / H) * 20)
        g = int(16 + (y / H) * 10)
        b = int(34 + (y / H) * 22)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # Marco exterior naranja Victini + tarjeta interior
    draw.rounded_rectangle([10, 10, W - 11, H - 11], radius=22, outline=(255, 107, 53, 230), width=3)
    draw.rounded_rectangle([24, 24, W - 24, H - 24], radius=16, fill=(26, 28, 54, 220), outline=(255, 159, 28, 90), width=2)

    # Descargar artwork oficial de Victini (#494)
    victini_bytes = _fetch_image_bytes(get_artwork_url(494, is_shiny=False))

    # Avatar circular del usuario a la izquierda
    av_x, av_y, av_size = 54, 86, 148
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (av_size, av_size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, av_size, av_size], fill=255)
            img.paste(av, (av_x, av_y), mask)
        except Exception:
            draw.ellipse([av_x, av_y, av_x + av_size, av_y + av_size], fill=(255, 107, 53, 255))
    else:
        draw.ellipse([av_x, av_y, av_x + av_size, av_y + av_size], fill=(255, 107, 53, 255))
    draw.ellipse([av_x - 3, av_y - 3, av_x + av_size + 3, av_y + av_size + 3], outline=(255, 159, 28, 255), width=4)

    # Textos centrales
    f_tag = _load_font(22, bold=True)
    f_user = _load_font(36, bold=True)
    f_sub = _load_font(18, bold=False)

    clean_user = _clean_text_for_card(username) or "Nuevo Miembro"
    if len(clean_user) > 18:
        clean_user = clean_user[:17] + "..."

    draw.text((232, 84), "BIENVENIDO/A A SNAP!", font=f_tag, fill=(255, 159, 28, 255))
    draw.text((232, 124), clean_user, font=f_user, fill=(255, 255, 255, 255))
    draw.text((232, 182), f"Miembro #{member_count}  |  Comunidad SNAP!", font=f_sub, fill=(195, 200, 225, 255))

    # Artwork oficial de Victini a la derecha
    if victini_bytes:
        try:
            vic = Image.open(io.BytesIO(victini_bytes)).convert("RGBA")
            vic.thumbnail((190, 190), Image.Resampling.LANCZOS)
            vx = W - 44 - vic.width
            vy = (H - vic.height) // 2
            img.paste(vic, (vx, vy), vic)
        except Exception:
            pass

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class ReplacePokemonView(discord.ui.View):
    """Permite elegir exactamente qué Pokémon del equipo (6/6) liberar para hacer lugar al nuevo."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        species: PokemonSpecies,
        is_shiny: bool,
        team: List[dict],
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.team = team
        self.on_backup = on_backup

        for idx, mon in enumerate(team[:6], start=1):
            shiny_tag = "✨ " if mon["is_shiny"] else ""
            label = f"{idx}. {shiny_tag}{mon['name']} ({mon['rarity']})" 
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary, row=(idx - 1) // 3)
            btn.callback = self._make_replace_callback(mon)
            self.add_item(btn)

        cancel_btn = discord.ui.Button(label="❌ Cancelar y liberar al nuevo", style=discord.ButtonStyle.danger, row=2)
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

    def _make_replace_callback(self, mon_to_release: dict):
        async def _callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "🔥 ¡Ey! Este encuentro es de otro entrenador, usá `/catch` para el tuyo.",
                    ephemeral=True,
                )
                return

            ok = replace_pokemon_in_team(
                guild_id=self.guild.id,
                user_id=self.author_id,
                release_row_id=mon_to_release["id"],
                pokedex_id=self.species.pokedex_id,
                name=self.species.name,
                rarity=self.species.rarity,
                ptype=self.species.ptype,
                is_shiny=self.is_shiny,
                caught_at=time.time(),
            )

            for item in self.children:
                item.disabled = True

            if ok:
                shiny_new = "✨ " if self.is_shiny else ""
                shiny_old = "✨ " if mon_to_release["is_shiny"] else ""
                embed = discord.Embed(
                    title="🔄 ¡Equipo actualizado en SNAP! 🔥",
                    description=(
                        f"Liberaste a **{shiny_old}{mon_to_release['name']}** en la naturaleza 🕊️ "
                        f"y sumaste a **{shiny_new}{self.species.name}** (`{self.species.rarity}`) a tu equipo (6/6)!"
                    ),
                    color=RARITY_CONFIG[self.species.rarity]["color"],
                )
                embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
                embed.set_footer(text="Usá /team para ver la imagen de tu equipo • Victini Bot 🔥✌️")
                await interaction.response.edit_message(embed=embed, view=self)
                asyncio.create_task(self.on_backup(self.guild, True))
            else:
                await interaction.response.edit_message(
                    content="⚠️ Hubo un problema actualizando tu equipo. Probá de nuevo con `/catch`.",
                    view=self,
                )

        return _callback

    async def _cancel_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("🔥 Este encuentro no es tuyo.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        shiny_tag = "✨ " if self.is_shiny else ""
        embed = discord.Embed(
            title="🕊️ Pokémon liberado",
            description=f"Decidiste mantener tu equipo actual y liberar a **{shiny_tag}{self.species.name}**.",
            color=discord.Color.light_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=self)


class PostCaptureDecisionView(discord.ui.View):
    """Tras capturar el Pokémon, permite quedárselo (añadir o reemplazar si hay 6) o liberarlo."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        species: PokemonSpecies,
        is_shiny: bool,
        team: List[dict],
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.team = team
        self.on_backup = on_backup

        if len(team) >= 6:
            self.keep_btn.label = "🔄 Quedármelo (elegir a cuál liberar)"
            self.keep_btn.style = discord.ButtonStyle.primary
        else:
            self.keep_btn.label = f"✅ Añadir al equipo ({len(team) + 1}/6)"
            self.keep_btn.style = discord.ButtonStyle.success

    @discord.ui.button(label="✅ Añadir al equipo", style=discord.ButtonStyle.success)
    async def keep_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 ¡Ey! Este Pokémon lo capturó otro entrenador.",
                ephemeral=True,
            )
            return

        current_team = get_pokemon_team(self.guild.id, self.author_id)
        if len(current_team) >= 6:
            shiny_tag = "✨ " if self.is_shiny else ""
            embed = discord.Embed(
                title="🎒 ¡Tu equipo está lleno (6/6)! 🔄",
                description=(
                    f"Elegí qué Pokémon de tu equipo querés **liberar** para hacerle lugar a "
                    f"**{shiny_tag}{self.species.name}** (`{self.species.rarity}`):"
                ),
                color=discord.Color.orange(),
            )
            embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
            replace_view = ReplacePokemonView(
                guild=self.guild,
                author_id=self.author_id,
                species=self.species,
                is_shiny=self.is_shiny,
                team=current_team,
                on_backup=self.on_backup,
            )
            await interaction.response.edit_message(embed=embed, view=replace_view)
            return

        added = add_pokemon_to_team(
            guild_id=self.guild.id,
            user_id=self.author_id,
            pokedex_id=self.species.pokedex_id,
            name=self.species.name,
            rarity=self.species.rarity,
            ptype=self.species.ptype,
            is_shiny=self.is_shiny,
            caught_at=time.time(),
        )

        for item in self.children:
            item.disabled = True

        if added:
            shiny_tag = "✨ " if self.is_shiny else ""
            new_count = len(current_team) + 1
            embed = discord.Embed(
                title="🎉 ¡Pokémon guardado en tu equipo! 🔥",
                description=(
                    f"**{shiny_tag}{self.species.name}** (`{self.species.rarity}`) se unió a tu equipo "
                    f"(`{new_count}/6`). ¡Victini te felicita! ✌️"
                ),
                color=RARITY_CONFIG[self.species.rarity]["color"],
            )
            embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
            embed.set_footer(text="Usá /team para ver la imagen de tu equipo • Victini Bot 🔥")
            await interaction.response.edit_message(embed=embed, view=self)
            asyncio.create_task(self.on_backup(self.guild, True))

    @discord.ui.button(label="🕊️ Liberar", style=discord.ButtonStyle.secondary)
    async def release_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 ¡Ey! Este encuentro es de otro entrenador.",
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True

        shiny_tag = "✨ " if self.is_shiny else ""
        embed = discord.Embed(
            title="🕊️ Pokémon liberado",
            description=f"Dejaste ir en libertad a **{shiny_tag}{self.species.name}**. ¡Qué buen gesto! 🔥",
            color=discord.Color.light_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=self)


class PostBattleCatchView(discord.ui.View):
    """Vista tras ganar una batalla: permite lanzar Pokéball con +20% de probabilidad o terminar."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        species: PokemonSpecies,
        is_shiny: bool,
        pokeballs: int,
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.on_backup = on_backup

        base_rate = RARITY_CONFIG[species.rarity]["catch_rate"]
        boosted_pct = int(min(0.98, base_rate + 0.20) * 100)
        self.catch_weakened_btn.label = f"🔴 ¡Capturar debilitado! ({boosted_pct}% | Tenés {pokeballs})"

    @discord.ui.button(label="🔴 ¡Capturar debilitado!", style=discord.ButtonStyle.danger)
    async def catch_weakened_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 ¡No te robes el encuentro! Tirale `/catch` para buscar el tuyo.",
                ephemeral=True,
            )
            return

        ok, remaining = consume_pokeball(self.guild.id, self.author_id)
        if not ok:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="❌ ¡Te quedaste sin Pokéballs! Subí de nivel chateando o estando activo en voz para ganar más.",
                view=self,
            )
            return

        cfg = RARITY_CONFIG[self.species.rarity]
        boosted_rate = min(0.98, cfg["catch_rate"] + 0.20)
        caught = random.random() <= boosted_rate
        shiny_tag = "✨ " if self.is_shiny else ""

        if not caught:
            for item in self.children:
                item.disabled = True
            embed = discord.Embed(
                title=f"💨 ¡Oh no! {shiny_tag}{self.species.name} se escapó...",
                description=(
                    f"La Pokéball se movió 1... 2... ¡y se rompió a pesar de estar debilitado! 🔥\n"
                    f"Te quedan **{remaining}** Pokéballs."
                ),
                color=discord.Color.red(),
            )
            embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
            embed.set_footer(text="Victini dice: ¡La próxima no falla! ✌️")
            await interaction.response.edit_message(embed=embed, view=self)
            asyncio.create_task(self.on_backup(self.guild, True))
            return

        team = get_pokemon_team(self.guild.id, self.author_id)
        decision_view = PostCaptureDecisionView(
            guild=self.guild,
            author_id=self.author_id,
            species=self.species,
            is_shiny=self.is_shiny,
            team=team,
            on_backup=self.on_backup,
        )

        extra_note = (
            f"\n\n⚠️ **Tu equipo está lleno (`6/6`).** Elegí si querés liberarlo o reemplazar a uno de tu equipo:"
            if len(team) >= 6
            else f"\n\nTenés espacio en tu equipo (`{len(team)}/6`). ¿Qué querés hacer?"
        )

        embed = discord.Embed(
            title=f"🎉 ¡ATRAPASTE A {shiny_tag}{self.species.name.upper()}! 🔥",
            description=(
                f"{cfg['emoji']} **Rareza:** {self.species.rarity} | **Tipo:** {self.species.ptype}\n"
                f"🎱 **Pokéballs restantes:** {remaining}"
                f"{extra_note}"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
        embed.set_footer(text="Elegí con los botones de abajo • Victini Bot 🔥✌️")
        await interaction.response.edit_message(embed=embed, view=decision_view)
        asyncio.create_task(self.on_backup(self.guild, True))

    @discord.ui.button(label="🏁 Terminar", style=discord.ButtonStyle.secondary)
    async def finish_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("🔥 Este encuentro no es tuyo.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title="🏁 ¡Entrenamiento completado!",
            description=f"*Dejaste ir a **{self.species.name}** tras la victoria. ¡Buen combate!* 🔥",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=self)


class ChooseFighterView(discord.ui.View):
    """Permite elegir un Pokémon del equipo para pelear contra el encuentro salvaje."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        species: PokemonSpecies,
        is_shiny: bool,
        pokeballs: int,
        team: list[dict],
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.pokeballs = pokeballs
        self.team = team
        self.on_backup = on_backup

        for idx, mon in enumerate(team[:6], start=1):
            shiny_tag = "✨ " if mon.get("is_shiny") else ""
            lvl = mon.get("poke_level", 1)
            btn = discord.ui.Button(
                label=f"{idx}. {shiny_tag}{mon['name']} (Nv. {lvl})",
                style=discord.ButtonStyle.primary,
                row=(idx - 1) // 3,
            )
            btn.callback = self._make_fight_cb(mon)
            self.add_item(btn)

        back_btn = discord.ui.Button(
            label="↩️ Volver",
            style=discord.ButtonStyle.secondary,
            row=2,
        )
        back_btn.callback = self._back_cb
        self.add_item(back_btn)

    def _make_fight_cb(self, mon: dict):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("🔥 Este encuentro no es tuyo.", ephemeral=True)
                return

            fighter_lvl = int(mon.get("poke_level", 1))
            fighter_power = RARITY_POWER.get(mon["rarity"], 10) + fighter_lvl * 3 + (5 if mon.get("is_shiny") else 0)

            wild_cfg = RARITY_CONFIG[self.species.rarity]
            wild_base_power = RARITY_POWER.get(self.species.rarity, 10)
            wild_level = max(1, min(35, fighter_lvl + random.randint(-2, 3)))
            wild_power = wild_base_power + wild_level * 3 + (4 if self.is_shiny else 0)

            win_chance = 0.50 + (fighter_power - wild_power) * 0.025
            win_chance = max(0.25, min(0.92, win_chance))
            won = random.random() <= win_chance

            base_xp = max(18, wild_base_power + wild_level * 4)
            xp_gain = base_xp if won else max(8, base_xp // 3)

            xp_res = add_pokemon_xp(
                row_id=mon["id"],
                guild_id=self.guild.id,
                user_id=self.author_id,
                xp_gain=xp_gain,
                evolution_table=EVOLUTION_TABLE,
            )

            shiny_f = "✨ " if mon.get("is_shiny") else ""
            shiny_w = "✨ " if self.is_shiny else ""

            if xp_res:
                new_name = xp_res["name"]
                old_name = xp_res["old_name"]
                new_lvl = xp_res["new_level"]
                new_xp = xp_res["new_xp"]
                next_xp = xp_res["next_xp"]
                leveled_up = xp_res["leveled_up"]
                evolved = xp_res["evolved"]
                art_id = xp_res["pokedex_id"]
            else:
                new_name = mon["name"]
                old_name = mon["name"]
                new_lvl = fighter_lvl
                new_xp = mon.get("poke_xp", 0) + xp_gain
                next_xp = 40 * max(1, new_lvl)
                leveled_up = False
                evolved = False
                art_id = mon["pokedex_id"]

            progress_lines = [
                f"⭐ **+{xp_gain} XP** para **{shiny_f}{new_name}** (`{new_xp}/{next_xp} XP` • **Nv. {new_lvl}**)"
            ]
            if leveled_up:
                progress_lines.append(f"🆙 *¡Subió a **Nivel {new_lvl}**!*")
            if evolved:
                progress_lines.append(
                    f"✨ **¡EVOLUCIÓN!** *{shiny_f}{old_name}* evolucionó en **{shiny_f}{new_name}**! 🎉"
                )

            asyncio.create_task(self.on_backup(self.guild, True))

            if won:
                embed = discord.Embed(
                    title=f"⚔️ ¡VICTORIA DE {shiny_f}{new_name.upper()}! 🔥",
                    description=(
                        f"Tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*) derrotó a **{shiny_w}{self.species.name}** (*Nv. {wild_level}* | {wild_cfg['emoji']} {self.species.rarity}).\n\n"
                        + "\n".join(progress_lines)
                        + "\n\n*¡El Pokémon salvaje quedó debilitado! Podés intentar capturarlo con **+20% de probabilidad** o terminar.*"
                    ),
                    color=discord.Color.gold() if evolved else discord.Color.green(),
                )
                embed.set_image(url=get_artwork_url(art_id, bool(mon.get("is_shiny"))))
                embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
                embed.set_footer(text="Victini Bot • ¡Victoria! 🔥✌️")
                next_view = PostBattleCatchView(
                    guild=self.guild,
                    author_id=self.author_id,
                    species=self.species,
                    is_shiny=self.is_shiny,
                    pokeballs=self.pokeballs,
                    on_backup=self.on_backup,
                )
                await interaction.response.edit_message(embed=embed, view=next_view)
            else:
                for item in self.children:
                    item.disabled = True
                embed = discord.Embed(
                    title=f"💥 ¡{shiny_w}{self.species.name} fue demasiado fuerte!",
                    description=(
                        f"Tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*) cayó en combate ante **{shiny_w}{self.species.name}** (*Nv. {wild_level}*), pero igual aprendió de la batalla:\n\n"
                        + "\n".join(progress_lines)
                    ),
                    color=discord.Color.orange(),
                )
                embed.set_thumbnail(url=get_artwork_url(art_id, bool(mon.get("is_shiny"))))
                embed.set_footer(text="Victini dice: ¡Seguí entrenando para la revancha! ✌️")
                await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def _back_cb(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("🔥 Este encuentro no es tuyo.", ephemeral=True)
            return

        cfg = RARITY_CONFIG[self.species.rarity]
        shiny_text = "✨ **¡SHINY!** ✨\n" if self.is_shiny else ""
        embed = discord.Embed(
            title=f"🌿 ¡Un {self.species.name} salvaje apareció!",
            description=(
                f"{shiny_text}"
                f"{cfg['emoji']} **Rareza:** {self.species.rarity}\n"
                f"🔥 **Tipo:** {self.species.ptype}\n"
                f"🎯 **Probabilidad de captura:** {int(cfg['catch_rate'] * 100)}%\n\n"
                f"*¿Querés lanzar una Pokéball, pelear con tu equipo o huir?*"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
        embed.set_footer(text="Tenés 2 minutos para decidir • Victini Bot 🔥✌️")

        encounter_view = WildEncounterView(
            guild=self.guild,
            author_id=self.author_id,
            species=self.species,
            is_shiny=self.is_shiny,
            pokeballs=self.pokeballs,
            on_backup=self.on_backup,
        )
        await interaction.response.edit_message(embed=embed, view=encounter_view)


class WildEncounterView(discord.ui.View):
    """Vista inicial cuando aparece un Pokémon salvaje: permite lanzar Pokéball, pelear o huir."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        species: PokemonSpecies,
        is_shiny: bool,
        pokeballs: int,
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.pokeballs = pokeballs
        self.on_backup = on_backup

        self.throw_btn.label = f"🔴 ¡Lanzar Pokéball! (Tenés {pokeballs})"

    @discord.ui.button(label="🔴 ¡Lanzar Pokéball!", style=discord.ButtonStyle.danger)
    async def throw_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 ¡No te robes el encuentro! Tirale `/catch` para buscar el tuyo.",
                ephemeral=True,
            )
            return

        ok, remaining = consume_pokeball(self.guild.id, self.author_id)
        if not ok:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="❌ ¡Te quedaste sin Pokéballs! Subí de nivel chateando o estando activo en voz para ganar más.",
                view=self,
            )
            return

        cfg = RARITY_CONFIG[self.species.rarity]
        caught = random.random() <= cfg["catch_rate"]
        shiny_tag = "✨ " if self.is_shiny else ""

        if not caught:
            for item in self.children:
                item.disabled = True
            embed = discord.Embed(
                title=f"💨 ¡Oh no! {shiny_tag}{self.species.name} se escapó...",
                description=(
                    f"La Pokéball se movió 1... 2... ¡y se rompió! 🔥\n"
                    f"Te quedan **{remaining}** Pokéballs."
                ),
                color=discord.Color.red(),
            )
            embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
            embed.set_footer(text="Victini dice: ¡La próxima no falla! ✌️")
            await interaction.response.edit_message(embed=embed, view=self)
            asyncio.create_task(self.on_backup(self.guild, True))
            return

        team = get_pokemon_team(self.guild.id, self.author_id)
        decision_view = PostCaptureDecisionView(
            guild=self.guild,
            author_id=self.author_id,
            species=self.species,
            is_shiny=self.is_shiny,
            team=team,
            on_backup=self.on_backup,
        )

        extra_note = (
            f"\n\n⚠️ **Tu equipo está lleno (`6/6`).** Elegí si querés liberarlo o reemplazar a uno de tu equipo:"
            if len(team) >= 6
            else f"\n\nTenés espacio en tu equipo (`{len(team)}/6`). ¿Qué querés hacer?"
        )

        embed = discord.Embed(
            title=f"🎉 ¡ATRAPASTE A {shiny_tag}{self.species.name.upper()}! 🔥",
            description=(
                f"{cfg['emoji']} **Rareza:** {self.species.rarity} | **Tipo:** {self.species.ptype}\n"
                f"🎱 **Pokéballs restantes:** {remaining}"
                f"{extra_note}"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
        embed.set_footer(text="Elegí con los botones de abajo • Victini Bot 🔥✌️")
        await interaction.response.edit_message(embed=embed, view=decision_view)
        asyncio.create_task(self.on_backup(self.guild, True))

    @discord.ui.button(label="⚔️ ¡Pelear!", style=discord.ButtonStyle.primary)
    async def fight_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 ¡No te robes el encuentro! Tirale `/catch` para buscar el tuyo.",
                ephemeral=True,
            )
            return

        team = get_pokemon_team(self.guild.id, self.author_id)
        if not team:
            await interaction.response.send_message(
                "❌ Todavía no tenés ningún Pokémon en tu equipo para pelear. ¡Primero capturá uno con **🔴 ¡Lanzar Pokéball!**!",
                ephemeral=True,
            )
            return

        shiny_tag = "✨ " if self.is_shiny else ""
        embed = discord.Embed(
            title=f"⚔️ ¡Elegí tu Pokémon para pelear contra {shiny_tag}{self.species.name}!",
            description="*Seleccioná a uno de tus compañeros abajo para combatir, ganar **XP**, subir de nivel y hasta **evolucionar**:*",
            color=discord.Color.orange(),
        )
        embed.set_thumbnail(url=get_artwork_url(self.species.pokedex_id, self.is_shiny))
        embed.set_footer(text="Victini Bot • Combate Pokémon 🔥✌️")

        choose_view = ChooseFighterView(
            guild=self.guild,
            author_id=self.author_id,
            species=self.species,
            is_shiny=self.is_shiny,
            pokeballs=self.pokeballs,
            team=team,
            on_backup=self.on_backup,
        )
        await interaction.response.edit_message(embed=embed, view=choose_view)

    @discord.ui.button(label="🏃 Huir", style=discord.ButtonStyle.secondary)
    async def flee_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("🔥 Este encuentro no es tuyo.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title="🏃 ¡Escapaste a salvo!",
            description=f"Decidiste no gastar una Pokéball en **{self.species.name}**. Usá `/catch` cuando quieras buscar otro.",
            color=discord.Color.light_grey(),
        )
        await interaction.response.edit_message(embed=embed, view=self)


async def _send_team_card(interaction: discord.Interaction, usuario: Optional[discord.Member] = None) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    target = usuario or interaction.user
    team = get_pokemon_team(interaction.guild.id, target.id)
    pokeballs = get_pokeballs(interaction.guild.id, target.id)
    level, _, _ = get_user_stats(interaction.guild.id, target.id)

    avatar_bytes: Optional[bytes] = None
    try:
        avatar_bytes = await target.display_avatar.with_size(256).read()
    except Exception:
        pass

    png_bytes = await asyncio.to_thread(
        build_team_card_png,
        target.display_name,
        level,
        pokeballs,
        team,
        avatar_bytes,
    )

    file = discord.File(io.BytesIO(png_bytes), filename=f"team_{target.id}.png")
    await interaction.followup.send(file=file)


def setup_pokemon_commands(
    bot: commands.Bot,
    on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    find_channel_fn: Callable[[discord.Guild, str], Optional[discord.TextChannel]],
) -> None:
    """Registra /catch (exclusivo de 🎮𝑪𝑨𝑻𝑪𝑯), /team y /equipo en el árbol de comandos de Victini."""

    @bot.tree.command(
        name="catch",
        description="Usá 1 Pokéball para capturar un Pokémon salvaje con Victini (Solo en 🎮𝑪𝑨𝑻𝑪𝑯)",
    )
    async def catch_command(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
                ephemeral=True,
            )
            return

        if not is_catch_channel(interaction.channel):
            catch_ch = find_channel_fn(interaction.guild, CATCH_CHANNEL_NAME)
            ch_mention = catch_ch.mention if catch_ch else f"**{CATCH_CHANNEL_NAME}**"
            await interaction.response.send_message(
                f"🎮 ¡Ey! El comando `/catch` solo se puede usar en el canal {ch_mention} 👀🔥",
                ephemeral=True,
            )
            return

        pokeballs = get_pokeballs(interaction.guild.id, interaction.user.id)
        level, _, _ = get_user_stats(interaction.guild.id, interaction.user.id)

        if pokeballs <= 0:
            await interaction.response.send_message(
                f"🎱 **No tenés Pokéballs disponibles** *(Nivel actual: {level})*.\n"
                f"¡Cada nivel que subís chateando o estando activo en canales de voz te da **+1 Pokéball**! 🔥",
                ephemeral=True,
            )
            return

        species, is_shiny = roll_wild_pokemon()
        cfg = RARITY_CONFIG[species.rarity]
        shiny_tag = "✨ SHINY " if is_shiny else ""
        pct = int(cfg["catch_rate"] * 100)

        embed = discord.Embed(
            title=f"🌿 ¡Victini encontró un {shiny_tag}{species.name} salvaje! 🔥",
            description=(
                f"¡Mirá quién apareció entre las llamas de **SNAP!** 👀\n\n"
                f"{cfg['emoji']} **Rareza:** {species.rarity} *(Probabilidad de captura: **{pct}%**)*\n"
                f"🏷️ **Tipo:** {species.ptype}\n"
                f"🎱 **Tus Pokéballs:** {pokeballs}"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(species.pokedex_id, is_shiny))
        embed.set_footer(text="¿Le tiramos una Pokéball? • Victini Bot 🔥✌️")

        view = WildEncounterView(
            guild=interaction.guild,
            author_id=interaction.user.id,
            species=species,
            is_shiny=is_shiny,
            pokeballs=pokeballs,
            on_backup=on_backup,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(
        name="team",
        description="Genera una imagen con tu username y tu equipo de hasta 6 Pokémon 🎒🔥",
    )
    async def team_command(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        await _send_team_card(interaction, usuario)

    @bot.tree.command(
        name="equipo",
        description="Muestra la imagen de tu equipo Pokémon y tus Pokéballs disponibles 🎒🔥",
    )
    async def equipo_command(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        await _send_team_card(interaction, usuario)
