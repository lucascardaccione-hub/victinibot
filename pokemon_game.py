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
    add_pokeballs,
    get_pokemon_team,
    add_pokemon_to_team,
    replace_pokemon_in_team,
    add_pokemon_xp,
    get_user_stats,
    get_trainer_progress,
    update_trainer_progress,
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
    """Elige un Pokémon aleatorio ponderado por rareza y con 1% de probabilidad Shiny."""
    weights = [RARITY_CONFIG[p.rarity]["weight"] for p in POKEMON_POOL]
    species = random.choices(POKEMON_POOL, weights=weights, k=1)[0]
    is_shiny = random.random() < 0.01
    return species, is_shiny


_KNOWN_TYPES = (
    "Normal", "Fuego", "Agua", "Planta", "Eléctrico", "Hielo",
    "Lucha", "Veneno", "Tierra", "Volador", "Psíquico", "Bicho",
    "Roca", "Fantasma", "Dragón", "Siniestro", "Acero", "Hada",
)

# Tabla oficial de efectividad de tipos: atacante -> {defensor: multiplicador}
TYPE_CHART: dict[str, dict[str, float]] = {
    "Normal": {"Roca": 0.5, "Fantasma": 0.30, "Acero": 0.5},
    "Fuego": {"Fuego": 0.5, "Agua": 0.5, "Planta": 2.0, "Hielo": 2.0, "Bicho": 2.0, "Roca": 0.5, "Dragón": 0.5, "Acero": 2.0},
    "Agua": {"Fuego": 2.0, "Agua": 0.5, "Planta": 0.5, "Tierra": 2.0, "Roca": 2.0, "Dragón": 0.5},
    "Planta": {"Fuego": 0.5, "Agua": 2.0, "Planta": 0.5, "Veneno": 0.5, "Tierra": 2.0, "Volador": 0.5, "Bicho": 0.5, "Roca": 2.0, "Dragón": 0.5, "Acero": 0.5},
    "Eléctrico": {"Agua": 2.0, "Planta": 0.5, "Eléctrico": 0.5, "Tierra": 0.30, "Volador": 2.0, "Dragón": 0.5},
    "Hielo": {"Fuego": 0.5, "Agua": 0.5, "Planta": 2.0, "Hielo": 0.5, "Tierra": 2.0, "Volador": 2.0, "Dragón": 2.0, "Acero": 0.5},
    "Lucha": {"Normal": 2.0, "Hielo": 2.0, "Veneno": 0.5, "Volador": 0.5, "Psíquico": 0.5, "Bicho": 0.5, "Roca": 2.0, "Fantasma": 0.30, "Siniestro": 2.0, "Acero": 2.0, "Hada": 0.5},
    "Veneno": {"Planta": 2.0, "Veneno": 0.5, "Tierra": 0.5, "Roca": 0.5, "Fantasma": 0.5, "Acero": 0.30, "Hada": 2.0},
    "Tierra": {"Fuego": 2.0, "Planta": 0.5, "Eléctrico": 2.0, "Veneno": 2.0, "Volador": 0.30, "Bicho": 0.5, "Roca": 2.0, "Acero": 2.0},
    "Volador": {"Planta": 2.0, "Eléctrico": 0.5, "Lucha": 2.0, "Bicho": 2.0, "Roca": 0.5, "Acero": 0.5},
    "Psíquico": {"Lucha": 2.0, "Veneno": 2.0, "Psíquico": 0.5, "Siniestro": 0.30, "Acero": 0.5},
    "Bicho": {"Fuego": 0.5, "Planta": 2.0, "Lucha": 0.5, "Veneno": 0.5, "Volador": 0.5, "Psíquico": 2.0, "Fantasma": 0.5, "Siniestro": 2.0, "Acero": 0.5, "Hada": 0.5},
    "Roca": {"Fuego": 2.0, "Hielo": 2.0, "Lucha": 0.5, "Tierra": 0.5, "Volador": 2.0, "Bicho": 2.0, "Acero": 0.5},
    "Fantasma": {"Normal": 0.30, "Psíquico": 2.0, "Fantasma": 2.0, "Siniestro": 0.5},
    "Dragón": {"Dragón": 2.0, "Acero": 0.5, "Hada": 0.30},
    "Siniestro": {"Lucha": 0.5, "Psíquico": 2.0, "Fantasma": 2.0, "Siniestro": 0.5, "Hada": 0.5},
    "Acero": {"Fuego": 0.5, "Agua": 0.5, "Eléctrico": 0.5, "Hielo": 2.0, "Roca": 2.0, "Acero": 0.5, "Hada": 2.0},
    "Hada": {"Fuego": 0.5, "Lucha": 2.0, "Veneno": 0.5, "Dragón": 2.0, "Siniestro": 2.0, "Acero": 0.5},
}

_EVOLVED_FROM = {v["to_id"]: k for k, v in EVOLUTION_TABLE.items()}


def _parse_types(ptype_str: str) -> List[str]:
    found = [t for t in _KNOWN_TYPES if t.lower() in (ptype_str or "").lower()]
    return found or ["Normal"]


def get_type_multiplier(attacker_ptype: str, defender_ptype: str) -> float:
    """Calcula el multiplicador de ventaja elemental del atacante frente al defensor (mejor tipo STAB)."""
    atk_types = _parse_types(attacker_ptype)
    def_types = _parse_types(defender_ptype)
    best = 0.0
    for at in atk_types:
        chart = TYPE_CHART.get(at, {})
        mult = 1.0
        for dt in def_types:
            mult *= chart.get(dt, 1.0)
        if mult > best:
            best = mult
    return round(best, 2) if best > 0 else 1.0


def get_evolution_stage(pokedex_id: int, rarity: str) -> int:
    """Determina la fase evolutiva (1, 2 o 3) para escalar stats de combate."""
    if pokedex_id in _EVOLVED_FROM:
        prev_id = _EVOLVED_FROM[pokedex_id]
        if prev_id in _EVOLVED_FROM:
            return 3
        if pokedex_id in EVOLUTION_TABLE:
            return 2
        return 3 if rarity in ("Épico", "Legendario") else 2
    if pokedex_id in EVOLUTION_TABLE:
        return 1
    return 3 if rarity in ("Épico", "Legendario") else 2


def compute_pokemon_combat_stats(
    pokedex_id: int,
    rarity: str,
    ptype: str,
    level: int,
    is_shiny: bool = False,
) -> dict:
    """Calcula HP, ATK, DEF y VEL reales según rareza, fase evolutiva, tipo, nivel y Shiny."""
    lvl = max(1, int(level))
    stage = get_evolution_stage(pokedex_id, rarity)
    base_bst = {"Común": 300, "Raro": 395, "Épico": 495, "Legendario": 620}.get(rarity, 340)
    bst = base_bst + (stage - 1) * 70
    if is_shiny:
        bst = int(bst * 1.08)

    types = _parse_types(ptype)
    w_hp, w_atk, w_def, w_spd = 1.0, 1.0, 1.0, 1.0
    for t in types:
        if t in ("Fuego", "Dragón", "Lucha", "Siniestro"):
            w_atk += 0.22
        if t in ("Roca", "Acero", "Tierra", "Veneno"):
            w_def += 0.22
        if t in ("Eléctrico", "Volador", "Bicho", "Psíquico"):
            w_spd += 0.22
        if t in ("Agua", "Planta", "Normal", "Hada", "Hielo", "Fantasma"):
            w_hp += 0.18

    # Variación determinista suave por especie
    seed = (pokedex_id * 37) % 13 - 6
    total_w = w_hp + w_atk + w_def + w_spd
    b_hp = max(35, int((bst * (w_hp / total_w)) / 3.8) + seed)
    b_atk = max(35, int((bst * (w_atk / total_w)) / 3.8) - seed // 2)
    b_def = max(35, int((bst * (w_def / total_w)) / 3.8) + seed // 2)
    b_spd = max(35, int((bst * (w_spd / total_w)) / 3.8))

    return {
        "stage": stage,
        "hp": int((b_hp * 2 * lvl) / 42) + lvl + 20,
        "atk": int((b_atk * 2 * lvl) / 48) + 8,
        "def": int((b_def * 2 * lvl) / 48) + 8,
        "spd": int((b_spd * 2 * lvl) / 48) + 8,
    }


def roll_wild_level(team: List[dict], rarity: str) -> int:
    """Genera el nivel del Pokémon salvaje al momento del encuentro (se conserva si se captura)."""
    rarity_bonus = {"Común": 0, "Raro": 1, "Épico": 3, "Legendario": 5}.get(rarity, 0)
    if not team:
        return max(1, random.randint(1, 4) + rarity_bonus)
    top_levels = sorted((int(m.get("poke_level", 1)) for m in team), reverse=True)[:3]
    avg_lvl = sum(top_levels) / len(top_levels)
    return max(1, min(65, int(round(avg_lvl)) + random.randint(-2, 3) + rarity_bonus))


def simulate_pokemon_battle(fighter: dict, opponent: dict) -> dict:
    """
    Simula un combate por turnos teniendo en cuenta:
    - Nivel, Stats (HP, ATK, DEF, VEL) y Fase Evolutiva
    - Debilidades y resistencias elementales (TYPE_CHART)
    - Golpes críticos y condición Shiny
    """
    f_stats = compute_pokemon_combat_stats(
        fighter["pokedex_id"], fighter["rarity"], fighter["ptype"], fighter["level"], bool(fighter.get("is_shiny"))
    )
    o_stats = compute_pokemon_combat_stats(
        opponent["pokedex_id"], opponent["rarity"], opponent["ptype"], opponent["level"], bool(opponent.get("is_shiny"))
    )

    f_mult = get_type_multiplier(fighter["ptype"], opponent["ptype"])
    o_mult = get_type_multiplier(opponent["ptype"], fighter["ptype"])

    f_hp = f_stats["hp"]
    o_hp = o_stats["hp"]
    turns = 0
    f_first = f_stats["spd"] >= o_stats["spd"]

    def _hit(atk_val: int, def_val: int, mult: float) -> int:
        crit = 1.5 if random.random() < 0.08 else 1.0
        raw = ((atk_val / max(1, def_val)) * 13.5 + 5.5) * mult * crit * random.uniform(0.88, 1.12)
        return max(3, int(round(raw)))

    while f_hp > 0 and o_hp > 0 and turns < 20:
        turns += 1
        if f_first:
            o_hp = max(0, o_hp - _hit(f_stats["atk"], o_stats["def"], f_mult))
            if o_hp <= 0:
                break
            f_hp = max(0, f_hp - _hit(o_stats["atk"], o_stats["def"], o_mult))
        else:
            f_hp = max(0, f_hp - _hit(o_stats["atk"], o_stats["def"], o_mult))
            if f_hp <= 0:
                break
            o_hp = max(0, o_hp - _hit(f_stats["atk"], o_stats["def"], f_mult))

    won = o_hp == 0 or (f_hp > o_hp)

    eff_notes = []
    if f_mult >= 2.0:
        eff_notes.append(f"⚡ *¡Tu ataque fue **súper eficaz** (`x{f_mult:g}`)!*")
    elif f_mult < 1.0:
        eff_notes.append(f"🛡️ *El rival resistió tu tipo (`x{f_mult:g}`).*")
    if o_mult >= 2.0:
        eff_notes.append(f"⚠️ *El rival tuvo ventaja de tipo (`x{o_mult:g}`).*")

    summary = (
        f"📊 **Stats ({fighter['name']} Fase {f_stats['stage']}):** "
        f"`HP {f_stats['hp']} | ATK {f_stats['atk']} | DEF {f_stats['def']} | VEL {f_stats['spd']}` "
        f"*(HP restante: **{f_hp}/{f_stats['hp']}** en {turns} turnos)*"
    )
    if eff_notes:
        summary = " ".join(eff_notes) + "\n" + summary

    return {
        "won": won,
        "turns": turns,
        "f_stats": f_stats,
        "o_stats": o_stats,
        "f_hp": f_hp,
        "o_hp": o_hp,
        "f_mult": f_mult,
        "o_mult": o_mult,
        "summary": summary,
    }


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
        wild_level: int = 1,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.team = team
        self.on_backup = on_backup
        self.wild_level = max(1, int(wild_level))

        for idx, mon in enumerate(team[:6], start=1):
            shiny_tag = "✨ " if mon["is_shiny"] else ""
            label = f"{idx}. {shiny_tag}{mon['name']} (Nv. {mon.get('poke_level', 1)})"
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
                poke_level=self.wild_level,
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
                        f"y sumaste a **{shiny_new}{self.species.name}** (**Nv. {self.wild_level}** | `{self.species.rarity}`) a tu equipo (6/6)!"
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
        wild_level: int = 1,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.team = team
        self.on_backup = on_backup
        self.wild_level = max(1, int(wild_level))

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
                    f"**{shiny_tag}{self.species.name}** (**Nv. {self.wild_level}** | `{self.species.rarity}`):"
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
                wild_level=self.wild_level,
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
            poke_level=self.wild_level,
        )

        for item in self.children:
            item.disabled = True

        if added:
            shiny_tag = "✨ " if self.is_shiny else ""
            new_count = len(current_team) + 1
            embed = discord.Embed(
                title="🎉 ¡Pokémon guardado en tu equipo! 🔥",
                description=(
                    f"**{shiny_tag}{self.species.name}** (**Nv. {self.wild_level}** | `{self.species.rarity}`) se unió a tu equipo "
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
        wild_level: int = 1,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.on_backup = on_backup
        self.wild_level = max(1, int(wild_level))

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
            wild_level=self.wild_level,
        )

        extra_note = (
            f"\n\n⚠️ **Tu equipo está lleno (`6/6`).** Elegí si querés liberarlo o reemplazar a uno de tu equipo:"
            if len(team) >= 6
            else f"\n\nTenés espacio en tu equipo (`{len(team)}/6`). ¿Qué querés hacer?"
        )

        embed = discord.Embed(
            title=f"🎉 ¡ATRAPASTE A {shiny_tag}{self.species.name.upper()} (Nv. {self.wild_level})! 🔥",
            description=(
                f"{cfg['emoji']} **Rareza:** {self.species.rarity} | **Tipo:** {self.species.ptype}\n"
                f"⭐ **Nivel capturado:** Nv. {self.wild_level} | 🎱 **Pokéballs restantes:** {remaining}"
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


def _apply_exp_share(
    guild_id: int,
    user_id: int,
    team: list[dict],
    fighter_id: int,
    main_xp_gain: int,
) -> list[str]:
    """
    Si el entrenador tiene nivel >= 20 en el servidor, activa automáticamente el
    Repartir Experiencia y reparte XP (50%, mín. 5) al resto del equipo.
    """
    trainer_level, _, _ = get_user_stats(guild_id, user_id)
    if trainer_level < 20:
        return []

    others = [m for m in team if m["id"] != fighter_id]
    if not others:
        return []

    share_xp = max(5, main_xp_gain // 2)
    highlights: list[str] = []
    for mate in others:
        res = add_pokemon_xp(
            row_id=mate["id"],
            guild_id=guild_id,
            user_id=user_id,
            xp_gain=share_xp,
            evolution_table=EVOLUTION_TABLE,
        )
        if not res:
            continue
        shiny_m = "✨ " if mate.get("is_shiny") else ""
        if res["evolved"]:
            highlights.append(
                f"✨ *{shiny_m}{res['old_name']}* → **{shiny_m}{res['name']}** (**Nv. {res['new_level']}**)"
            )
        elif res["leveled_up"]:
            highlights.append(f"🆙 **{shiny_m}{res['name']}** (**Nv. {res['new_level']}**)")

    line = f"🎒 **Repartir Experiencia** *(Nv. {trainer_level}+)*: el resto del equipo sumó **+{share_xp} XP** c/u."
    if highlights:
        line += " " + " • ".join(highlights)
    return [line]


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
        wild_level: int = 1,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.pokeballs = pokeballs
        self.team = team
        self.on_backup = on_backup
        self.wild_level = max(1, int(wild_level))

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
            wild_cfg = RARITY_CONFIG[self.species.rarity]
            wild_level = self.wild_level

            battle = simulate_pokemon_battle(
                fighter={
                    "pokedex_id": mon["pokedex_id"],
                    "name": mon["name"],
                    "rarity": mon["rarity"],
                    "ptype": mon["ptype"],
                    "level": fighter_lvl,
                    "is_shiny": bool(mon.get("is_shiny")),
                },
                opponent={
                    "pokedex_id": self.species.pokedex_id,
                    "name": self.species.name,
                    "rarity": self.species.rarity,
                    "ptype": self.species.ptype,
                    "level": wild_level,
                    "is_shiny": self.is_shiny,
                },
            )
            won = battle["won"]

            wild_base_power = RARITY_POWER.get(self.species.rarity, 10)
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
            progress_lines.extend(
                _apply_exp_share(self.guild.id, self.author_id, self.team, mon["id"], xp_gain)
            )

            asyncio.create_task(self.on_backup(self.guild, True))

            if won:
                embed = discord.Embed(
                    title=f"⚔️ ¡VICTORIA DE {shiny_f}{new_name.upper()}! 🔥",
                    description=(
                        f"Tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*) derrotó a **{shiny_w}{self.species.name}** (*Nv. {wild_level}* | {wild_cfg['emoji']} {self.species.rarity}).\n\n"
                        + battle["summary"]
                        + "\n\n"
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
                    wild_level=self.wild_level,
                )
                await interaction.response.edit_message(embed=embed, view=next_view)
            else:
                for item in self.children:
                    item.disabled = True
                embed = discord.Embed(
                    title=f"💥 ¡{shiny_w}{self.species.name} fue demasiado fuerte!",
                    description=(
                        f"Tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*) cayó en combate ante **{shiny_w}{self.species.name}** (*Nv. {wild_level}*), pero igual aprendió de la batalla:\n\n"
                        + battle["summary"]
                        + "\n\n"
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
            title=f"🌿 ¡Un {self.species.name} salvaje (Nv. {self.wild_level}) apareció!",
            description=(
                f"{shiny_text}"
                f"{cfg['emoji']} **Rareza:** {self.species.rarity} | ⭐ **Nivel:** Nv. {self.wild_level}\n"
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
            wild_level=self.wild_level,
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
        wild_level: int = 1,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.species = species
        self.is_shiny = is_shiny
        self.pokeballs = pokeballs
        self.on_backup = on_backup
        self.wild_level = max(1, int(wild_level))

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
            wild_level=self.wild_level,
        )

        extra_note = (
            f"\n\n⚠️ **Tu equipo está lleno (`6/6`).** Elegí si querés liberarlo o reemplazar a uno de tu equipo:"
            if len(team) >= 6
            else f"\n\nTenés espacio en tu equipo (`{len(team)}/6`). ¿Qué querés hacer?"
        )

        embed = discord.Embed(
            title=f"🎉 ¡ATRAPASTE A {shiny_tag}{self.species.name.upper()} (Nv. {self.wild_level})! 🔥",
            description=(
                f"{cfg['emoji']} **Rareza:** {self.species.rarity} | **Tipo:** {self.species.ptype}\n"
                f"⭐ **Nivel capturado:** Nv. {self.wild_level} | 🎱 **Pokéballs restantes:** {remaining}"
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
            wild_level=self.wild_level,
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


@dataclass(frozen=True)
class TrainerOpponent:
    name: str
    title: str
    pokemon_id: int
    pokemon_name: str
    rarity: str
    ptype: str
    level: int
    quote: str
    xp_win: int
    xp_loss: int
    pokeball_chance: float
    pokeball_amount: int = 1
    badge_name: str = ""
    badge_emoji: str = ""


RANDOM_TRAINERS: List[TrainerOpponent] = [
    TrainerOpponent("Tito", "Dominguero", 19, "Rattata", "Común", "Normal", 5, "¡Mis shorts son súper cómodos y fáciles de llevar!", 45, 14, 0.50, 1),
    TrainerOpponent("Mateo", "Pescador", 129, "Magikarp", "Común", "Agua", 7, "¡Picó algo enorme... bueno, casi! ¡A pelear!", 50, 15, 0.50, 1),
    TrainerOpponent("Lucas", "Cazabichos", 123, "Scyther", "Raro", "Bicho/Volador", 11, "¡Mis Pokémon bicho son los más rápidos del Bosque Verde!", 65, 20, 0.50, 1),
    TrainerOpponent("Secuaz Rocket", "Team Rocket", 52, "Meowth", "Raro", "Normal", 13, "¡Entregá a tus Pokémon o preparate para el combate!", 75, 22, 0.50, 1),
    TrainerOpponent("Jessie y James", "Dúo del Team Rocket", 24, "Arbok", "Raro", "Veneno", 16, "¡Para proteger al mundo de la devastación, vamos a derrotarte!", 90, 28, 0.50, 1),
    TrainerOpponent("Enfermera Joy", "Desafío Amistoso", 113, "Chansey", "Raro", "Normal", 18, "¡Hasta en el Centro Pokémon entrenamos duro todos los días!", 95, 30, 0.50, 1),
    TrainerOpponent("Gary Oak", "Rival Clásico", 197, "Umbreon", "Épico", "Siniestro", 24, "¡Huelo a novato por acá! ¡Mostrame qué tan fuerte sos!", 135, 42, 0.50, 1),
    TrainerOpponent("Ash Ketchum", "Entrenador de Pueblo Paleta", 25, "Pikachu", "Épico", "Eléctrico", 27, "¡Pikachu, yo te elijo! ¡Vamos a dar lo mejor en esta batalla!", 150, 48, 0.50, 1),
    TrainerOpponent("N", "Rey del Equipo Plasma", 571, "Zoroark", "Épico", "Siniestro", 30, "¿Podés escuchar el corazón de tus Pokémon en medio del combate?", 170, 55, 0.50, 1),
    TrainerOpponent("Red", "Entrenador Legendario", 6, "Charizard", "Legendario", "Fuego/Volador", 36, "...", 220, 70, 0.50, 1),
]

GYM_LEADERS: List[TrainerOpponent] = [
    TrainerOpponent("Brock", "Líder de Gimnasio (Ciudad Plateada)", 95, "Onix", "Raro", "Roca/Tierra", 10, "¡Mi defensa de roca es impenetrable!", 95, 30, 1.0, 1, "Medalla Roca", "🪨"),
    TrainerOpponent("Misty", "Líder de Gimnasio (Ciudad Celeste)", 121, "Starmie", "Raro", "Agua/Psíquico", 15, "¡Te voy a arrastrar con la fuerza del océano!", 125, 40, 1.0, 1, "Medalla Cascada", "💧"),
    TrainerOpponent("Lt. Surge", "Líder de Gimnasio (Ciudad Carmín)", 26, "Raichu", "Raro", "Eléctrico", 20, "¡Te voy a electrocutar en un abrir y cerrar de ojos!", 160, 50, 1.0, 1, "Medalla Trueno", "⚡"),
    TrainerOpponent("Erika", "Líder de Gimnasio (Ciudad Azulona)", 45, "Vileplume", "Raro", "Planta/Veneno", 25, "¡Qué lindo día para una batalla elegante!", 195, 65, 1.0, 1, "Medalla Arcoíris", "🌿"),
    TrainerOpponent("Koga", "Líder de Gimnasio (Ciudad Fucsia)", 110, "Weezing", "Raro", "Veneno", 30, "¡Mis técnicas ninja y venenosas te dejarán sin salida!", 235, 75, 1.0, 1, "Medalla Alma", "☠️"),
    TrainerOpponent("Sabrina", "Líder de Gimnasio (Ciudad Azafrán)", 65, "Alakazam", "Épico", "Psíquico", 35, "Ya vi tu derrota en mi mente antes de empezar...", 280, 90, 1.0, 2, "Medalla Pantano", "🔮"),
    TrainerOpponent("Blaine", "Líder de Gimnasio (Isla Canela)", 59, "Arcanine", "Épico", "Fuego", 40, "¡Ja! ¡Mis Pokémon de fuego te van a dejar en cenizas!", 330, 105, 1.0, 2, "Medalla Volcán", "🔥"),
    TrainerOpponent("Giovanni", "Líder de Gimnasio (Ciudad Verde)", 34, "Nidoking", "Épico", "Veneno/Tierra", 45, "¡Contemplá el verdadero poder del jefe!", 390, 125, 1.0, 2, "Medalla Tierra", "🌍"),
]

LEAGUE_CHALLENGERS: List[TrainerOpponent] = [
    TrainerOpponent("Lorelei", "Alto Mando 1/5 • Especialista en Hielo", 131, "Lapras", "Épico", "Agua/Hielo", 48, "¡Nadie resiste el frío absoluto de mis Pokémon!", 430, 140, 1.0, 1, "Sala Helada", "❄️"),
    TrainerOpponent("Bruno", "Alto Mando 2/5 • Especialista en Lucha", 68, "Machamp", "Épico", "Lucha", 51, "¡El poder puro de nuestros músculos te aplastará!", 470, 155, 1.0, 1, "Sala de Lucha", "🥊"),
    TrainerOpponent("Agatha", "Alto Mando 3/5 • Especialista en Fantasma", 94, "Gengar", "Épico", "Fantasma/Veneno", 54, "¡Las sombras de la Liga te van a devorar, jovencito!", 510, 170, 1.0, 1, "Sala Espectral", "👻"),
    TrainerOpponent("Lance", "Alto Mando 4/5 • Maestro de Dragones", 149, "Dragonite", "Legendario", "Dragón/Volador", 58, "¡Los dragones son invencibles! ¿Podrás soportarlos?", 580, 190, 1.0, 2, "Sala Dragón", "🐉"),
    TrainerOpponent("Cynthia", "Campeona de la Liga Pokémon 5/5", 445, "Garchomp", "Legendario", "Dragón/Tierra", 63, "¡Mostrame el vínculo que construiste con tu equipo!", 720, 230, 1.0, 3, "Campeón de la Liga", "👑"),
]


class TrainerBattleView(discord.ui.View):
    """Vista de combate contra Entrenadores (/battle), Gimnasios (/gymchallenge) y Liga (/pokemonleague)."""

    def __init__(
        self,
        guild: discord.Guild,
        author_id: int,
        author_name: str,
        mode: str,  # "battle", "gym", "league"
        opponent: TrainerOpponent,
        team: list[dict],
        on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
        stage_index: int = 0,
        is_rematch: bool = False,
    ):
        super().__init__(timeout=120)
        self.guild = guild
        self.author_id = author_id
        self.author_name = author_name
        self.mode = mode
        self.opponent = opponent
        self.team = team
        self.on_backup = on_backup
        self.stage_index = stage_index
        self.is_rematch = is_rematch

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

    def _make_fight_cb(self, mon: dict):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "🔥 ¡Este combate no es tuyo! Usá el comando por tu cuenta.",
                    ephemeral=True,
                )
                return

            fighter_lvl = int(mon.get("poke_level", 1))
            opp_level = (
                max(1, fighter_lvl + random.randint(-1, 2))
                if self.mode == "battle"
                else self.opponent.level
            )
            battle = simulate_pokemon_battle(
                fighter={
                    "pokedex_id": mon["pokedex_id"],
                    "name": mon["name"],
                    "rarity": mon["rarity"],
                    "ptype": mon["ptype"],
                    "level": fighter_lvl,
                    "is_shiny": bool(mon.get("is_shiny")),
                },
                opponent={
                    "pokedex_id": self.opponent.pokemon_id,
                    "name": self.opponent.pokemon_name,
                    "rarity": self.opponent.rarity,
                    "ptype": self.opponent.ptype,
                    "level": opp_level,
                    "is_shiny": False,
                },
            )
            won = battle["won"]

            xp_gain = self.opponent.xp_win if won else self.opponent.xp_loss
            xp_res = add_pokemon_xp(
                row_id=mon["id"],
                guild_id=self.guild.id,
                user_id=self.author_id,
                xp_gain=xp_gain,
                evolution_table=EVOLUTION_TABLE,
            )

            shiny_f = "✨ " if mon.get("is_shiny") else ""
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

            reward_lines = [
                f"⭐ **+{xp_gain} XP** para **{shiny_f}{new_name}** (`{new_xp}/{next_xp} XP` • **Nv. {new_lvl}**)"
            ]
            if leveled_up:
                reward_lines.append(f"🆙 *¡Subió a **Nivel {new_lvl}**!*")
            if evolved:
                reward_lines.append(
                    f"✨ **¡EVOLUCIÓN!** *{shiny_f}{old_name}* evolucionó en **{shiny_f}{new_name}**! 🎉"
                )
            reward_lines.extend(
                _apply_exp_share(self.guild.id, self.author_id, self.team, mon["id"], xp_gain)
            )

            pokeballs_won = 0
            if won:
                if self.mode == "battle":
                    if random.random() <= self.opponent.pokeball_chance:
                        pokeballs_won = self.opponent.pokeball_amount
                elif self.mode == "gym":
                    if not self.is_rematch:
                        pokeballs_won = self.opponent.pokeball_amount
                        update_trainer_progress(
                            self.guild.id,
                            self.author_id,
                            gym_badges=self.stage_index + 1,
                            username=self.author_name,
                        )
                        reward_lines.append(
                            f"{self.opponent.badge_emoji} **¡Obtuviste la {self.opponent.badge_name}!** (`{self.stage_index + 1}/8`)"
                        )
                        if self.stage_index + 1 >= len(GYM_LEADERS):
                            reward_lines.append("👑 *¡Ya tenés las 8 Medallas! Podés desafiar `/pokemonleague`.*")
                    elif random.random() <= 0.50:
                        pokeballs_won = 1
                elif self.mode == "league":
                    if self.stage_index + 1 >= len(LEAGUE_CHALLENGERS):
                        pokeballs_won = self.opponent.pokeball_amount
                        cur = get_trainer_progress(self.guild.id, self.author_id)
                        new_wins = cur["league_wins"] + 1
                        update_trainer_progress(
                            self.guild.id,
                            self.author_id,
                            league_stage=0,
                            league_wins=new_wins,
                            username=self.author_name,
                        )
                        reward_lines.append(
                            f"🏆 **¡SOS CAMPEÓN DE LA LIGA POKÉMON!** *(Títulos: **{new_wins}**)*"
                        )
                    else:
                        pokeballs_won = self.opponent.pokeball_amount
                        update_trainer_progress(
                            self.guild.id,
                            self.author_id,
                            league_stage=self.stage_index + 1,
                            username=self.author_name,
                        )
                        next_opp = LEAGUE_CHALLENGERS[self.stage_index + 1]
                        reward_lines.append(
                            f"➡️ *Avanzaste a la ronda **{self.stage_index + 2}/5**: **{next_opp.name}**. ¡Volvé a tirar `/pokemonleague`!*"
                        )

                if pokeballs_won > 0:
                    total_balls = add_pokeballs(
                        self.guild.id,
                        self.author_id,
                        pokeballs_won,
                        username=self.author_name,
                    )
                    reward_lines.append(
                        f"🎱 **+{pokeballs_won} Pokéball{'s' if pokeballs_won > 1 else ''}** *(Total: **{total_balls}**)*"
                    )

            for item in self.children:
                item.disabled = True

            if won:
                embed = discord.Embed(
                    title=f"🏆 ¡VICTORIA CONTRA {self.opponent.name.upper()}! 🔥",
                    description=(
                        f"Tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*) venció al **{self.opponent.pokemon_name}** (*Nv. {opp_level}*) de **{self.opponent.name}** (*{self.opponent.title}*).\n\n"
                        + battle["summary"]
                        + "\n\n"
                        + "\n".join(reward_lines)
                    ),
                    color=discord.Color.gold() if (evolved or self.mode in ("gym", "league")) else discord.Color.green(),
                )
            else:
                embed = discord.Embed(
                    title=f"💥 ¡DERROTA ANTE {self.opponent.name.upper()}!",
                    description=(
                        f"El **{self.opponent.pokemon_name}** (*Nv. {opp_level}*) de **{self.opponent.name}** (*{self.opponent.title}*) superó a tu **{shiny_f}{old_name}** (*Nv. {fighter_lvl}*).\n\n"
                        + battle["summary"]
                        + "\n\n"
                        + "\n".join(reward_lines)
                        + "\n\n*¡Igual sumaste experiencia de entrenamiento! Subí de nivel y volvé por la revancha.*"
                    ),
                    color=discord.Color.red(),
                )

            embed.set_image(url=get_artwork_url(art_id, bool(mon.get("is_shiny"))))
            embed.set_thumbnail(url=get_artwork_url(self.opponent.pokemon_id, False))
            embed.set_footer(text="Victini Bot • Combate de Entrenadores 🔥✌️")
            await interaction.response.edit_message(embed=embed, view=self)
            asyncio.create_task(self.on_backup(self.guild, True))

        return callback


def setup_pokemon_commands(
    bot: commands.Bot,
    on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    find_channel_fn: Callable[[discord.Guild, str], Optional[discord.TextChannel]],
) -> None:
    """Registra /catch, /battle, /gymchallenge, /pokemonleague (exclusivos de 🎮𝑪𝑨𝑻𝑪𝑯), /team y /equipo."""

    async def _require_catch_channel_and_team(interaction: discord.Interaction, cmd_name: str) -> Optional[list[dict]]:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
                ephemeral=True,
            )
            return None

        if not is_catch_channel(interaction.channel):
            catch_ch = find_channel_fn(interaction.guild, CATCH_CHANNEL_NAME)
            ch_mention = catch_ch.mention if catch_ch else f"**{CATCH_CHANNEL_NAME}**"
            await interaction.response.send_message(
                f"🎮 ¡Ey! El comando `/{cmd_name}` solo se puede usar en el canal {ch_mention} 👀🔥",
                ephemeral=True,
            )
            return None

        team = get_pokemon_team(interaction.guild.id, interaction.user.id)
        if not team:
            await interaction.response.send_message(
                "❌ Todavía no tenés ningún Pokémon en tu equipo. ¡Usá `/catch` primero para atrapar tu primer compañero! 🔥",
                ephemeral=True,
            )
            return None
        return team

    @bot.tree.command(
        name="battle",
        description="Enfrentá a un Entrenador Pokémon para ganar XP y chances de Pokéballs (Solo en 🎮𝑪𝑨𝑻𝑪𝑯)",
    )
    async def battle_command(interaction: discord.Interaction):
        team = await _require_catch_channel_and_team(interaction, "battle")
        if team is None:
            return

        trainer = random.choice(RANDOM_TRAINERS)
        cfg = RARITY_CONFIG[trainer.rarity]
        embed = discord.Embed(
            title=f"⚔️ ¡{trainer.name} ({trainer.title}) te desafía a combatir! 🔥",
            description=(
                f"> *\"{trainer.quote}\"*\n\n"
                f"🐾 **Pokémon rival:** **{trainer.pokemon_name}** *(Nivel adaptado al Pokémon que elijas)*\n"
                f"{cfg['emoji']} **Rareza:** {trainer.rarity} | **Tipo:** {trainer.ptype}\n"
                f"🎁 **Recompensa si ganás:** **+{trainer.xp_win} XP** y **50%** de chance de **+1 Pokéball**\n"
                f"📉 **Si perdés:** **+{trainer.xp_loss} XP** de entrenamiento\n\n"
                f"*Elegí qué Pokémon de tu equipo sale a pelear:*"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(trainer.pokemon_id, False))
        embed.set_footer(text="Victini Bot • Desafío de Entrenadores 🔥✌️")

        view = TrainerBattleView(
            guild=interaction.guild,
            author_id=interaction.user.id,
            author_name=interaction.user.display_name,
            mode="battle",
            opponent=trainer,
            team=team,
            on_backup=on_backup,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(
        name="gymchallenge",
        description="Desafiá a los 8 Líderes de Gimnasio para ganar Medallas, XP y Pokéballs (Solo en 🎮𝑪𝑨𝑻𝑪𝑯)",
    )
    async def gymchallenge_command(interaction: discord.Interaction):
        team = await _require_catch_channel_and_team(interaction, "gymchallenge")
        if team is None:
            return

        progress = get_trainer_progress(interaction.guild.id, interaction.user.id)
        badges = progress["gym_badges"]
        is_rematch = badges >= len(GYM_LEADERS)
        stage_idx = random.randrange(len(GYM_LEADERS)) if is_rematch else badges
        leader = GYM_LEADERS[stage_idx]
        cfg = RARITY_CONFIG[leader.rarity]

        header_note = (
            f"🏅 **Tus Medallas:** `8/8` *(¡Revancha de Gimnasio!)*"
            if is_rematch
            else f"🏅 **Desafío de Medalla #{stage_idx + 1}/8:** {leader.badge_emoji} **{leader.badge_name}**"
        )
        ball_note = (
            f"**50%** de chance de **+1 Pokéball**"
            if is_rematch
            else f"**+{leader.pokeball_amount} Pokéball{'s' if leader.pokeball_amount > 1 else ''} garantizada{'s' if leader.pokeball_amount > 1 else ''}** + **{leader.badge_emoji} {leader.badge_name}**"
        )

        embed = discord.Embed(
            title=f"🏟️ ¡Gimnasio Pokémon: Líder {leader.name}! 🔥",
            description=(
                f"{header_note}\n"
                f"*{leader.title}*\n\n"
                f"> *\"{leader.quote}\"*\n\n"
                f"🐾 **Pokémon estrella:** **{leader.pokemon_name}** (*Nv. {leader.level}*)\n"
                f"{cfg['emoji']} **Rareza:** {leader.rarity} | **Tipo:** {leader.ptype}\n"
                f"🎁 **Si ganás:** **+{leader.xp_win} XP** y {ball_note}\n"
                f"📉 **Si perdés:** **+{leader.xp_loss} XP**\n\n"
                f"*Elegí qué Pokémon de tu equipo va al gimnasio:*"
            ),
            color=discord.Color.gold(),
        )
        embed.set_image(url=get_artwork_url(leader.pokemon_id, False))
        embed.set_footer(text="Victini Bot • Desafío de Gimnasios 🔥✌️")

        view = TrainerBattleView(
            guild=interaction.guild,
            author_id=interaction.user.id,
            author_name=interaction.user.display_name,
            mode="gym",
            opponent=leader,
            team=team,
            on_backup=on_backup,
            stage_index=stage_idx,
            is_rematch=is_rematch,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @bot.tree.command(
        name="pokemonleague",
        description="Enfrentá al Alto Mando y la Campeona de la Liga Pokémon (Requiere 8 Medallas • Solo en 🎮𝑪𝑨𝑻𝑪𝑯)",
    )
    async def pokemonleague_command(interaction: discord.Interaction):
        team = await _require_catch_channel_and_team(interaction, "pokemonleague")
        if team is None:
            return

        progress = get_trainer_progress(interaction.guild.id, interaction.user.id)
        if progress["gym_badges"] < len(GYM_LEADERS):
            await interaction.response.send_message(
                f"🔒 **Todavía no podés entrar a la Liga Pokémon.**\n"
                f"Necesitás las **8 Medallas de Gimnasio** y actualmente tenés **`{progress['gym_badges']}/8`**.\n"
                f"*Usá `/gymchallenge` para conseguir las que te faltan!* 🏟️🔥",
                ephemeral=True,
            )
            return

        stage_idx = progress["league_stage"] % len(LEAGUE_CHALLENGERS)
        challenger = LEAGUE_CHALLENGERS[stage_idx]
        cfg = RARITY_CONFIG[challenger.rarity]

        embed = discord.Embed(
            title=f"👑 ¡Liga Pokémon ({stage_idx + 1}/5): {challenger.name}! 🔥",
            description=(
                f"*{challenger.title}* | 🏆 *Títulos ganados: **{progress['league_wins']}***\n\n"
                f"> *\"{challenger.quote}\"*\n\n"
                f"🐾 **Pokémon rival:** **{challenger.pokemon_name}** (*Nv. {challenger.level}*)\n"
                f"{cfg['emoji']} **Rareza:** {challenger.rarity} | **Tipo:** {challenger.ptype}\n"
                f"🎁 **Si ganás:** **+{challenger.xp_win} XP** y **+{challenger.pokeball_amount} Pokéball{'s' if challenger.pokeball_amount > 1 else ''}**\n"
                f"📉 **Si perdés:** **+{challenger.xp_loss} XP**\n\n"
                f"*Elegí qué Pokémon de tu equipo entra a la arena:*"
            ),
            color=discord.Color.purple(),
        )
        embed.set_image(url=get_artwork_url(challenger.pokemon_id, False))
        embed.set_footer(text="Victini Bot • Liga Pokémon 🔥✌️")

        view = TrainerBattleView(
            guild=interaction.guild,
            author_id=interaction.user.id,
            author_name=interaction.user.display_name,
            mode="league",
            opponent=challenger,
            team=team,
            on_backup=on_backup,
            stage_index=stage_idx,
        )
        await interaction.response.send_message(embed=embed, view=view)

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
        user_team = get_pokemon_team(interaction.guild.id, interaction.user.id)
        wild_level = roll_wild_level(user_team, species.rarity)
        cfg = RARITY_CONFIG[species.rarity]
        shiny_tag = "✨ SHINY " if is_shiny else ""
        pct = int(cfg["catch_rate"] * 100)

        embed = discord.Embed(
            title=f"🌿 ¡Victini encontró un {shiny_tag}{species.name} salvaje (Nv. {wild_level})! 🔥",
            description=(
                f"¡Mirá quién apareció entre las llamas de **SNAP!** 👀\n\n"
                f"⭐ **Nivel:** Nv. {wild_level}\n"
                f"{cfg['emoji']} **Rareza:** {species.rarity} *(Probabilidad de captura: **{pct}%**)*\n"
                f"🏷️ **Tipo:** {species.ptype}\n"
                f"🎱 **Tus Pokéballs:** {pokeballs}"
            ),
            color=cfg["color"],
        )
        embed.set_image(url=get_artwork_url(species.pokedex_id, is_shiny))
        embed.set_footer(text="¿Le tiramos una Pokéball o peleamos? • Victini Bot 🔥✌️")

        view = WildEncounterView(
            guild=interaction.guild,
            author_id=interaction.user.id,
            species=species,
            is_shiny=is_shiny,
            pokeballs=pokeballs,
            on_backup=on_backup,
            wild_level=wild_level,
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
