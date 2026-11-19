import asyncio
import random
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional, List, Callable, Awaitable

import discord
from discord.ext import commands

from database import (
    get_pokeballs,
    consume_pokeball,
    get_pokemon_team,
    add_pokemon_to_team,
    replace_pokemon_in_team,
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
    "Común": {"weight": 55, "catch_rate": 0.80, "color": discord.Color.green(), "emoji": "🟢"},
    "Raro": {"weight": 27, "catch_rate": 0.55, "color": discord.Color.blue(), "emoji": "🔵"},
    "Épico": {"weight": 13, "catch_rate": 0.35, "color": discord.Color.purple(), "emoji": "🟣"},
    "Legendario": {"weight": 5, "catch_rate": 0.18, "color": discord.Color.gold(), "emoji": "🟡"},
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
                embed.set_footer(text="Usá /equipo para ver tu equipo completo • Victini Bot 🔥✌️")
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
            # Equipo lleno: abrir selector con botones de los 6 Pokémon para elegir a cuál liberar
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
            embed.set_footer(text="Usá /equipo para ver tu equipo completo • Victini Bot 🔥")
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


class WildEncounterView(discord.ui.View):
    """Vista inicial cuando aparece un Pokémon salvaje: permite lanzar Pokéball o huir."""

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

        # ¡Capturado!
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


def setup_pokemon_commands(
    bot: commands.Bot,
    on_backup: Callable[[discord.Guild, bool], Awaitable[None]],
    find_channel_fn: Callable[[discord.Guild, str], Optional[discord.TextChannel]],
) -> None:
    """Registra /catch (exclusivo de 🎮𝑪𝑨𝑻𝑪𝑯) y /equipo en el árbol de comandos de Victini."""

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
        name="equipo",
        description="Muestra tu equipo de hasta 6 Pokémon capturados y tus Pokéballs disponibles 🎒🔥",
    )
    async def equipo_command(interaction: discord.Interaction, usuario: Optional[discord.Member] = None):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando solo funciona dentro del servidor **SNAP!** 🔥",
                ephemeral=True,
            )
            return

        target = usuario or interaction.user
        team = get_pokemon_team(interaction.guild.id, target.id)
        pokeballs = get_pokeballs(interaction.guild.id, target.id)
        level, _, _ = get_user_stats(interaction.guild.id, target.id)

        embed = discord.Embed(
            title=f"🎒 Equipo Pokémon de {target.display_name} 🔥",
            description=f"⭐ **Nivel:** {level} | 🎱 **Pokéballs:** {pokeballs} | 🧩 **Equipo:** {len(team)}/6",
            color=discord.Color.orange(),
        )

        if not team:
            embed.add_field(
                name="Sin Pokémon todavía",
                value=f"¡Subí de nivel para conseguir Pokéballs y usá `/catch` en **{CATCH_CHANNEL_NAME}**!",
                inline=False,
            )
        else:
            lines = []
            for idx, mon in enumerate(team, start=1):
                cfg = RARITY_CONFIG.get(mon["rarity"], {"emoji": "⚪"})
                shiny_tag = "✨ " if mon["is_shiny"] else ""
                lines.append(
                    f"`#{idx}` {cfg['emoji']} **{shiny_tag}{mon['name']}** — *{mon['rarity']}* ({mon['ptype']})"
                )
            embed.add_field(name="🐾 Compañeros", value="\n".join(lines), inline=False)
            embed.set_thumbnail(url=get_artwork_url(team[0]["pokedex_id"], team[0]["is_shiny"]))

        embed.set_footer(text="Victini Bot • Mascota oficial de SNAP! 🔥✌️")
        await interaction.response.send_message(embed=embed)
