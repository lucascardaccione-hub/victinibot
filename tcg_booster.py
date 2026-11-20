import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import os
import random
import time
import urllib.request
from typing import Callable, Awaitable, List, Optional

import discord
from PIL import Image, ImageDraw, ImageFont

from database import add_tcg_cards

TCGDEX_IMG_PREFIX = "https://assets.tcgdex.net/en/"
WEB_PORTAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://victini.onrender.com").rstrip("/")

TCG_RARITY_STYLE = {
    "Común": {"emoji": "⚪", "color": (160, 168, 184), "embed_color": 0x9CA3AF},
    "Infrecuente": {"emoji": "🟢", "color": (52, 211, 153), "embed_color": 0x10B981},
    "Rara": {"emoji": "🔵", "color": (59, 130, 246), "embed_color": 0x3B82F6},
    "Ultra Rara": {"emoji": "🟣", "color": (168, 85, 247), "embed_color": 0xA855F7},
    "Ilustración Rara": {"emoji": "🌟", "color": (251, 146, 60), "embed_color": 0xFB923C},
    "Secreta / SIR": {"emoji": "👑", "color": (250, 204, 21), "embed_color": 0xFACC15},
}

# Catálogo real de cartas Pokémon TCG (TCGdex: 151, Surging Sparks, Base Set, Crown Zenith)
# Tupla: (card_id, name, set_name, rarity, image_rel_path)
TCG_CATALOG = [
    ('sv03.5-001', 'Bulbasaur', '151', 'Común', 'sv/sv03.5/001'),
    ('sv03.5-002', 'Ivysaur', '151', 'Infrecuente', 'sv/sv03.5/002'),
    ('sv03.5-003', 'Venusaur ex', '151', 'Ultra Rara', 'sv/sv03.5/003'),
    ('sv03.5-004', 'Charmander', '151', 'Común', 'sv/sv03.5/004'),
    ('sv03.5-005', 'Charmeleon', '151', 'Infrecuente', 'sv/sv03.5/005'),
    ('sv03.5-006', 'Charizard ex', '151', 'Ultra Rara', 'sv/sv03.5/006'),
    ('sv03.5-007', 'Squirtle', '151', 'Común', 'sv/sv03.5/007'),
    ('sv03.5-008', 'Wartortle', '151', 'Infrecuente', 'sv/sv03.5/008'),
    ('sv03.5-009', 'Blastoise ex', '151', 'Ultra Rara', 'sv/sv03.5/009'),
    ('sv03.5-010', 'Caterpie', '151', 'Común', 'sv/sv03.5/010'),
    ('sv03.5-011', 'Metapod', '151', 'Común', 'sv/sv03.5/011'),
    ('sv03.5-012', 'Butterfree', '151', 'Infrecuente', 'sv/sv03.5/012'),
    ('sv03.5-013', 'Weedle', '151', 'Común', 'sv/sv03.5/013'),
    ('sv03.5-014', 'Kakuna', '151', 'Común', 'sv/sv03.5/014'),
    ('sv03.5-015', 'Beedrill', '151', 'Rara', 'sv/sv03.5/015'),
    ('sv03.5-016', 'Pidgey', '151', 'Común', 'sv/sv03.5/016'),
    ('sv03.5-017', 'Pidgeotto', '151', 'Común', 'sv/sv03.5/017'),
    ('sv03.5-018', 'Pidgeot', '151', 'Infrecuente', 'sv/sv03.5/018'),
    ('sv03.5-019', 'Rattata', '151', 'Común', 'sv/sv03.5/019'),
    ('sv03.5-020', 'Raticate', '151', 'Infrecuente', 'sv/sv03.5/020'),
    ('sv03.5-021', 'Spearow', '151', 'Común', 'sv/sv03.5/021'),
    ('sv03.5-022', 'Fearow', '151', 'Infrecuente', 'sv/sv03.5/022'),
    ('sv03.5-023', 'Ekans', '151', 'Común', 'sv/sv03.5/023'),
    ('sv03.5-024', 'Arbok ex', '151', 'Ultra Rara', 'sv/sv03.5/024'),
    ('sv03.5-025', 'Pikachu', '151', 'Común', 'sv/sv03.5/025'),
    ('sv03.5-026', 'Raichu', '151', 'Rara', 'sv/sv03.5/026'),
    ('sv03.5-027', 'Sandshrew', '151', 'Común', 'sv/sv03.5/027'),
    ('sv03.5-028', 'Sandslash', '151', 'Infrecuente', 'sv/sv03.5/028'),
    ('sv03.5-029', 'Nidoran♀', '151', 'Común', 'sv/sv03.5/029'),
    ('sv03.5-030', 'Nidorina', '151', 'Infrecuente', 'sv/sv03.5/030'),
    ('sv03.5-031', 'Nidoqueen', '151', 'Infrecuente', 'sv/sv03.5/031'),
    ('sv03.5-032', 'Nidoran♂', '151', 'Común', 'sv/sv03.5/032'),
    ('sv03.5-033', 'Nidorino', '151', 'Infrecuente', 'sv/sv03.5/033'),
    ('sv03.5-034', 'Nidoking', '151', 'Rara', 'sv/sv03.5/034'),
    ('sv03.5-035', 'Clefairy', '151', 'Común', 'sv/sv03.5/035'),
    ('sv03.5-036', 'Clefable', '151', 'Infrecuente', 'sv/sv03.5/036'),
    ('sv03.5-037', 'Vulpix', '151', 'Común', 'sv/sv03.5/037'),
    ('sv03.5-038', 'Ninetales ex', '151', 'Ultra Rara', 'sv/sv03.5/038'),
    ('sv03.5-039', 'Jigglypuff', '151', 'Común', 'sv/sv03.5/039'),
    ('sv03.5-040', 'Wigglytuff ex', '151', 'Ultra Rara', 'sv/sv03.5/040'),
    ('sv03.5-041', 'Zubat', '151', 'Común', 'sv/sv03.5/041'),
    ('sv03.5-042', 'Golbat', '151', 'Infrecuente', 'sv/sv03.5/042'),
    ('sv03.5-043', 'Oddish', '151', 'Común', 'sv/sv03.5/043'),
    ('sv03.5-044', 'Gloom', '151', 'Infrecuente', 'sv/sv03.5/044'),
    ('sv03.5-045', 'Vileplume', '151', 'Rara', 'sv/sv03.5/045'),
    ('sv03.5-046', 'Paras', '151', 'Común', 'sv/sv03.5/046'),
    ('sv03.5-047', 'Parasect', '151', 'Infrecuente', 'sv/sv03.5/047'),
    ('sv03.5-048', 'Venonat', '151', 'Común', 'sv/sv03.5/048'),
    ('sv03.5-049', 'Venomoth', '151', 'Infrecuente', 'sv/sv03.5/049'),
    ('sv03.5-050', 'Diglett', '151', 'Común', 'sv/sv03.5/050'),
    ('sv03.5-051', 'Dugtrio', '151', 'Infrecuente', 'sv/sv03.5/051'),
    ('sv03.5-052', 'Meowth', '151', 'Común', 'sv/sv03.5/052'),
    ('sv03.5-053', 'Persian', '151', 'Infrecuente', 'sv/sv03.5/053'),
    ('sv03.5-054', 'Psyduck', '151', 'Común', 'sv/sv03.5/054'),
    ('sv03.5-055', 'Golduck', '151', 'Infrecuente', 'sv/sv03.5/055'),
    ('sv03.5-056', 'Mankey', '151', 'Común', 'sv/sv03.5/056'),
    ('sv03.5-057', 'Primeape', '151', 'Infrecuente', 'sv/sv03.5/057'),
    ('sv03.5-058', 'Growlithe', '151', 'Común', 'sv/sv03.5/058'),
    ('sv03.5-059', 'Arcanine', '151', 'Infrecuente', 'sv/sv03.5/059'),
    ('sv03.5-060', 'Poliwag', '151', 'Común', 'sv/sv03.5/060'),
    ('sv03.5-061', 'Poliwhirl', '151', 'Común', 'sv/sv03.5/061'),
    ('sv03.5-062', 'Poliwrath', '151', 'Infrecuente', 'sv/sv03.5/062'),
    ('sv03.5-063', 'Abra', '151', 'Común', 'sv/sv03.5/063'),
    ('sv03.5-064', 'Kadabra', '151', 'Infrecuente', 'sv/sv03.5/064'),
    ('sv03.5-065', 'Alakazam ex', '151', 'Ultra Rara', 'sv/sv03.5/065'),
    ('sv03.5-066', 'Machop', '151', 'Común', 'sv/sv03.5/066'),
    ('sv03.5-067', 'Machoke', '151', 'Infrecuente', 'sv/sv03.5/067'),
    ('sv03.5-068', 'Machamp', '151', 'Rara', 'sv/sv03.5/068'),
    ('sv03.5-069', 'Bellsprout', '151', 'Común', 'sv/sv03.5/069'),
    ('sv03.5-070', 'Weepinbell', '151', 'Común', 'sv/sv03.5/070'),
    ('sv03.5-071', 'Victreebel', '151', 'Infrecuente', 'sv/sv03.5/071'),
    ('sv03.5-072', 'Tentacool', '151', 'Común', 'sv/sv03.5/072'),
    ('sv03.5-073', 'Tentacruel', '151', 'Infrecuente', 'sv/sv03.5/073'),
    ('sv03.5-074', 'Geodude', '151', 'Común', 'sv/sv03.5/074'),
    ('sv03.5-075', 'Graveler', '151', 'Infrecuente', 'sv/sv03.5/075'),
    ('sv03.5-076', 'Golem ex', '151', 'Ultra Rara', 'sv/sv03.5/076'),
    ('sv03.5-077', 'Ponyta', '151', 'Común', 'sv/sv03.5/077'),
    ('sv03.5-078', 'Rapidash', '151', 'Infrecuente', 'sv/sv03.5/078'),
    ('sv03.5-079', 'Slowpoke', '151', 'Común', 'sv/sv03.5/079'),
    ('sv03.5-080', 'Slowbro', '151', 'Infrecuente', 'sv/sv03.5/080'),
    ('sv03.5-081', 'Magnemite', '151', 'Común', 'sv/sv03.5/081'),
    ('sv03.5-082', 'Magneton', '151', 'Infrecuente', 'sv/sv03.5/082'),
    ('sv03.5-083', "Farfetch'd", '151', 'Común', 'sv/sv03.5/083'),
    ('sv03.5-084', 'Doduo', '151', 'Común', 'sv/sv03.5/084'),
    ('sv03.5-085', 'Dodrio', '151', 'Rara', 'sv/sv03.5/085'),
    ('sv03.5-086', 'Seel', '151', 'Común', 'sv/sv03.5/086'),
    ('sv03.5-087', 'Dewgong', '151', 'Infrecuente', 'sv/sv03.5/087'),
    ('sv03.5-088', 'Grimer', '151', 'Común', 'sv/sv03.5/088'),
    ('sv03.5-089', 'Muk', '151', 'Infrecuente', 'sv/sv03.5/089'),
    ('sv03.5-090', 'Shellder', '151', 'Común', 'sv/sv03.5/090'),
    ('sv03.5-091', 'Cloyster', '151', 'Infrecuente', 'sv/sv03.5/091'),
    ('sv03.5-092', 'Gastly', '151', 'Común', 'sv/sv03.5/092'),
    ('sv03.5-093', 'Haunter', '151', 'Infrecuente', 'sv/sv03.5/093'),
    ('sv03.5-094', 'Gengar', '151', 'Rara', 'sv/sv03.5/094'),
    ('sv03.5-095', 'Onix', '151', 'Infrecuente', 'sv/sv03.5/095'),
    ('sv03.5-096', 'Drowzee', '151', 'Común', 'sv/sv03.5/096'),
    ('sv03.5-097', 'Hypno', '151', 'Infrecuente', 'sv/sv03.5/097'),
    ('sv03.5-098', 'Krabby', '151', 'Común', 'sv/sv03.5/098'),
    ('sv03.5-099', 'Kingler', '151', 'Infrecuente', 'sv/sv03.5/099'),
    ('sv03.5-100', 'Voltorb', '151', 'Común', 'sv/sv03.5/100'),
    ('sv03.5-101', 'Electrode', '151', 'Rara', 'sv/sv03.5/101'),
    ('sv03.5-102', 'Exeggcute', '151', 'Común', 'sv/sv03.5/102'),
    ('sv03.5-103', 'Exeggutor', '151', 'Infrecuente', 'sv/sv03.5/103'),
    ('sv03.5-104', 'Cubone', '151', 'Común', 'sv/sv03.5/104'),
    ('sv03.5-105', 'Marowak', '151', 'Rara', 'sv/sv03.5/105'),
    ('sv03.5-106', 'Hitmonlee', '151', 'Infrecuente', 'sv/sv03.5/106'),
    ('sv03.5-107', 'Hitmonchan', '151', 'Infrecuente', 'sv/sv03.5/107'),
    ('sv03.5-108', 'Lickitung', '151', 'Común', 'sv/sv03.5/108'),
    ('sv03.5-109', 'Koffing', '151', 'Común', 'sv/sv03.5/109'),
    ('sv03.5-110', 'Weezing', '151', 'Rara', 'sv/sv03.5/110'),
    ('sv03.5-111', 'Rhyhorn', '151', 'Común', 'sv/sv03.5/111'),
    ('sv03.5-112', 'Rhydon', '151', 'Infrecuente', 'sv/sv03.5/112'),
    ('sv03.5-113', 'Chansey', '151', 'Rara', 'sv/sv03.5/113'),
    ('sv03.5-114', 'Tangela', '151', 'Común', 'sv/sv03.5/114'),
    ('sv03.5-115', 'Kangaskhan ex', '151', 'Ultra Rara', 'sv/sv03.5/115'),
    ('sv03.5-116', 'Horsea', '151', 'Común', 'sv/sv03.5/116'),
    ('sv03.5-117', 'Seadra', '151', 'Infrecuente', 'sv/sv03.5/117'),
    ('sv03.5-118', 'Goldeen', '151', 'Común', 'sv/sv03.5/118'),
    ('sv03.5-119', 'Seaking', '151', 'Infrecuente', 'sv/sv03.5/119'),
    ('sv03.5-120', 'Staryu', '151', 'Común', 'sv/sv03.5/120'),
    ('sv03.5-121', 'Starmie', '151', 'Rara', 'sv/sv03.5/121'),
    ('sv03.5-122', 'Mr. Mime', '151', 'Rara', 'sv/sv03.5/122'),
    ('sv03.5-123', 'Scyther', '151', 'Infrecuente', 'sv/sv03.5/123'),
    ('sv03.5-124', 'Jynx ex', '151', 'Ultra Rara', 'sv/sv03.5/124'),
    ('sv03.5-125', 'Electabuzz', '151', 'Común', 'sv/sv03.5/125'),
    ('sv03.5-126', 'Magmar', '151', 'Común', 'sv/sv03.5/126'),
    ('sv03.5-127', 'Pinsir', '151', 'Infrecuente', 'sv/sv03.5/127'),
    ('sv03.5-128', 'Tauros', '151', 'Infrecuente', 'sv/sv03.5/128'),
    ('sv03.5-129', 'Magikarp', '151', 'Común', 'sv/sv03.5/129'),
    ('sv03.5-130', 'Gyarados', '151', 'Rara', 'sv/sv03.5/130'),
    ('sv03.5-131', 'Lapras', '151', 'Infrecuente', 'sv/sv03.5/131'),
    ('sv03.5-132', 'Ditto', '151', 'Rara', 'sv/sv03.5/132'),
    ('sv03.5-133', 'Eevee', '151', 'Común', 'sv/sv03.5/133'),
    ('sv03.5-134', 'Vaporeon', '151', 'Rara', 'sv/sv03.5/134'),
    ('sv03.5-135', 'Jolteon', '151', 'Rara', 'sv/sv03.5/135'),
    ('sv03.5-136', 'Flareon', '151', 'Rara', 'sv/sv03.5/136'),
    ('sv03.5-137', 'Porygon', '151', 'Común', 'sv/sv03.5/137'),
    ('sv03.5-138', 'Omanyte', '151', 'Infrecuente', 'sv/sv03.5/138'),
    ('sv03.5-139', 'Omastar', '151', 'Rara', 'sv/sv03.5/139'),
    ('sv03.5-140', 'Kabuto', '151', 'Infrecuente', 'sv/sv03.5/140'),
    ('sv03.5-141', 'Kabutops', '151', 'Rara', 'sv/sv03.5/141'),
    ('sv03.5-142', 'Aerodactyl', '151', 'Rara', 'sv/sv03.5/142'),
    ('sv03.5-143', 'Snorlax', '151', 'Infrecuente', 'sv/sv03.5/143'),
    ('sv03.5-144', 'Articuno', '151', 'Rara', 'sv/sv03.5/144'),
    ('sv03.5-145', 'Zapdos ex', '151', 'Ultra Rara', 'sv/sv03.5/145'),
    ('sv03.5-146', 'Moltres', '151', 'Rara', 'sv/sv03.5/146'),
    ('sv03.5-147', 'Dratini', '151', 'Común', 'sv/sv03.5/147'),
    ('sv03.5-148', 'Dragonair', '151', 'Infrecuente', 'sv/sv03.5/148'),
    ('sv03.5-149', 'Dragonite', '151', 'Rara', 'sv/sv03.5/149'),
    ('sv03.5-150', 'Mewtwo', '151', 'Rara', 'sv/sv03.5/150'),
    ('sv03.5-151', 'Mew ex', '151', 'Ultra Rara', 'sv/sv03.5/151'),
    ('sv03.5-152', 'Antique Dome Fossil', '151', 'Común', 'sv/sv03.5/152'),
    ('sv03.5-153', 'Antique Helix Fossil', '151', 'Común', 'sv/sv03.5/153'),
    ('sv03.5-154', 'Antique Old Amber', '151', 'Común', 'sv/sv03.5/154'),
    ('sv03.5-155', 'Big Air Balloon', '151', 'Infrecuente', 'sv/sv03.5/155'),
    ('sv03.5-156', "Bill's Transfer", '151', 'Infrecuente', 'sv/sv03.5/156'),
    ('sv03.5-157', 'Cycling Road', '151', 'Infrecuente', 'sv/sv03.5/157'),
    ('sv03.5-158', "Daisy's Help", '151', 'Infrecuente', 'sv/sv03.5/158'),
    ('sv03.5-159', 'Energy Sticker', '151', 'Infrecuente', 'sv/sv03.5/159'),
    ('sv03.5-160', "Erika's Invitation", '151', 'Infrecuente', 'sv/sv03.5/160'),
    ('sv03.5-161', "Giovanni's Charisma", '151', 'Infrecuente', 'sv/sv03.5/161'),
    ('sv03.5-162', 'Grabber', '151', 'Infrecuente', 'sv/sv03.5/162'),
    ('sv03.5-163', 'Leftovers', '151', 'Infrecuente', 'sv/sv03.5/163'),
    ('sv03.5-164', 'Protective Goggles', '151', 'Infrecuente', 'sv/sv03.5/164'),
    ('sv03.5-165', 'Rigid Band', '151', 'Infrecuente', 'sv/sv03.5/165'),
    ('sv03.5-166', 'Bulbasaur', '151', 'Ilustración Rara', 'sv/sv03.5/166'),
    ('sv03.5-167', 'Ivysaur', '151', 'Ilustración Rara', 'sv/sv03.5/167'),
    ('sv03.5-168', 'Charmander', '151', 'Ilustración Rara', 'sv/sv03.5/168'),
    ('sv03.5-169', 'Charmeleon', '151', 'Ilustración Rara', 'sv/sv03.5/169'),
    ('sv03.5-170', 'Squirtle', '151', 'Ilustración Rara', 'sv/sv03.5/170'),
    ('sv03.5-171', 'Wartortle', '151', 'Ilustración Rara', 'sv/sv03.5/171'),
    ('sv03.5-172', 'Caterpie', '151', 'Ilustración Rara', 'sv/sv03.5/172'),
    ('sv03.5-173', 'Pikachu', '151', 'Ilustración Rara', 'sv/sv03.5/173'),
    ('sv03.5-174', 'Nidoking', '151', 'Ilustración Rara', 'sv/sv03.5/174'),
    ('sv03.5-175', 'Psyduck', '151', 'Ilustración Rara', 'sv/sv03.5/175'),
    ('sv03.5-176', 'Poliwhirl', '151', 'Ilustración Rara', 'sv/sv03.5/176'),
    ('sv03.5-177', 'Machoke', '151', 'Ilustración Rara', 'sv/sv03.5/177'),
    ('sv03.5-178', 'Tangela', '151', 'Ilustración Rara', 'sv/sv03.5/178'),
    ('sv03.5-179', 'Mr. Mime', '151', 'Ilustración Rara', 'sv/sv03.5/179'),
    ('sv03.5-180', 'Omanyte', '151', 'Ilustración Rara', 'sv/sv03.5/180'),
    ('sv03.5-181', 'Dragonair', '151', 'Ilustración Rara', 'sv/sv03.5/181'),
    ('sv03.5-182', 'Venusaur ex', '151', 'Ultra Rara', 'sv/sv03.5/182'),
    ('sv03.5-183', 'Charizard ex', '151', 'Ultra Rara', 'sv/sv03.5/183'),
    ('sv03.5-184', 'Blastoise ex', '151', 'Ultra Rara', 'sv/sv03.5/184'),
    ('sv03.5-185', 'Arbok ex', '151', 'Ultra Rara', 'sv/sv03.5/185'),
    ('sv03.5-186', 'Ninetales ex', '151', 'Ultra Rara', 'sv/sv03.5/186'),
    ('sv03.5-187', 'Wigglytuff ex', '151', 'Ultra Rara', 'sv/sv03.5/187'),
    ('sv03.5-188', 'Alakazam ex', '151', 'Ultra Rara', 'sv/sv03.5/188'),
    ('sv03.5-189', 'Golem ex', '151', 'Ultra Rara', 'sv/sv03.5/189'),
    ('sv03.5-190', 'Kangaskhan ex', '151', 'Ultra Rara', 'sv/sv03.5/190'),
    ('sv03.5-191', 'Jynx ex', '151', 'Ultra Rara', 'sv/sv03.5/191'),
    ('sv03.5-192', 'Zapdos ex', '151', 'Ultra Rara', 'sv/sv03.5/192'),
    ('sv03.5-193', 'Mew ex', '151', 'Ultra Rara', 'sv/sv03.5/193'),
    ('sv03.5-194', "Bill's Transfer", '151', 'Ultra Rara', 'sv/sv03.5/194'),
    ('sv03.5-195', "Daisy's Help", '151', 'Ultra Rara', 'sv/sv03.5/195'),
    ('sv03.5-196', "Erika's Invitation", '151', 'Ultra Rara', 'sv/sv03.5/196'),
    ('sv03.5-197', "Giovanni's Charisma", '151', 'Ultra Rara', 'sv/sv03.5/197'),
    ('sv03.5-198', 'Venusaur ex', '151', 'Secreta / SIR', 'sv/sv03.5/198'),
    ('sv03.5-199', 'Charizard ex', '151', 'Secreta / SIR', 'sv/sv03.5/199'),
    ('sv03.5-200', 'Blastoise ex', '151', 'Secreta / SIR', 'sv/sv03.5/200'),
    ('sv03.5-201', 'Alakazam ex', '151', 'Secreta / SIR', 'sv/sv03.5/201'),
    ('sv03.5-202', 'Zapdos ex', '151', 'Secreta / SIR', 'sv/sv03.5/202'),
    ('sv03.5-203', "Erika's Invitation", '151', 'Secreta / SIR', 'sv/sv03.5/203'),
    ('sv03.5-204', "Giovanni's Charisma", '151', 'Secreta / SIR', 'sv/sv03.5/204'),
    ('sv03.5-205', 'Mew ex', '151', 'Secreta / SIR', 'sv/sv03.5/205'),
    ('sv03.5-206', 'Switch', '151', 'Secreta / SIR', 'sv/sv03.5/206'),
    ('sv03.5-207', 'Basic Psychic Energy', '151', 'Secreta / SIR', 'sv/sv03.5/207'),
    ('sv08-001', 'Exeggcute', 'Surging Sparks', 'Común', 'sv/sv08/001'),
    ('sv08-002', 'Exeggcute', 'Surging Sparks', 'Común', 'sv/sv08/002'),
    ('sv08-003', 'Exeggutor', 'Surging Sparks', 'Infrecuente', 'sv/sv08/003'),
    ('sv08-004', 'Durant ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/004'),
    ('sv08-005', 'Scatterbug', 'Surging Sparks', 'Común', 'sv/sv08/005'),
    ('sv08-006', 'Spewpa', 'Surging Sparks', 'Común', 'sv/sv08/006'),
    ('sv08-007', 'Vivillon', 'Surging Sparks', 'Infrecuente', 'sv/sv08/007'),
    ('sv08-008', 'Morelull', 'Surging Sparks', 'Común', 'sv/sv08/008'),
    ('sv08-009', 'Shiinotic', 'Surging Sparks', 'Infrecuente', 'sv/sv08/009'),
    ('sv08-010', 'Dhelmise', 'Surging Sparks', 'Común', 'sv/sv08/010'),
    ('sv08-011', 'Zarude', 'Surging Sparks', 'Rara', 'sv/sv08/011'),
    ('sv08-012', 'Capsakid', 'Surging Sparks', 'Común', 'sv/sv08/012'),
    ('sv08-013', 'Rellor', 'Surging Sparks', 'Común', 'sv/sv08/013'),
    ('sv08-014', 'Rabsca', 'Surging Sparks', 'Rara', 'sv/sv08/014'),
    ('sv08-015', 'Wo-Chien', 'Surging Sparks', 'Infrecuente', 'sv/sv08/015'),
    ('sv08-016', 'Vulpix', 'Surging Sparks', 'Común', 'sv/sv08/016'),
    ('sv08-017', 'Ninetales', 'Surging Sparks', 'Infrecuente', 'sv/sv08/017'),
    ('sv08-018', 'Paldean Tauros', 'Surging Sparks', 'Infrecuente', 'sv/sv08/018'),
    ('sv08-019', 'Ho-Oh', 'Surging Sparks', 'Infrecuente', 'sv/sv08/019'),
    ('sv08-020', 'Castform Sunny Form', 'Surging Sparks', 'Común', 'sv/sv08/020'),
    ('sv08-021', 'Victini', 'Surging Sparks', 'Infrecuente', 'sv/sv08/021'),
    ('sv08-022', 'Pansear', 'Surging Sparks', 'Común', 'sv/sv08/022'),
    ('sv08-023', 'Simisear', 'Surging Sparks', 'Común', 'sv/sv08/023'),
    ('sv08-024', 'Larvesta', 'Surging Sparks', 'Común', 'sv/sv08/024'),
    ('sv08-025', 'Volcarona', 'Surging Sparks', 'Común', 'sv/sv08/025'),
    ('sv08-026', 'Oricorio', 'Surging Sparks', 'Común', 'sv/sv08/026'),
    ('sv08-027', 'Sizzlipede', 'Surging Sparks', 'Común', 'sv/sv08/027'),
    ('sv08-028', 'Centiskorch', 'Surging Sparks', 'Común', 'sv/sv08/028'),
    ('sv08-029', 'Fuecoco', 'Surging Sparks', 'Común', 'sv/sv08/029'),
    ('sv08-030', 'Crocalor', 'Surging Sparks', 'Común', 'sv/sv08/030'),
    ('sv08-031', 'Skeledirge', 'Surging Sparks', 'Rara', 'sv/sv08/031'),
    ('sv08-032', 'Charcadet', 'Surging Sparks', 'Común', 'sv/sv08/032'),
    ('sv08-033', 'Charcadet', 'Surging Sparks', 'Común', 'sv/sv08/033'),
    ('sv08-034', 'Armarouge', 'Surging Sparks', 'Infrecuente', 'sv/sv08/034'),
    ('sv08-035', 'Ceruledge', 'Surging Sparks', 'Infrecuente', 'sv/sv08/035'),
    ('sv08-036', 'Ceruledge ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/036'),
    ('sv08-037', 'Scovillain ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/037'),
    ('sv08-038', 'Gouging Fire', 'Surging Sparks', 'Rara', 'sv/sv08/038'),
    ('sv08-039', 'Paldean Tauros', 'Surging Sparks', 'Infrecuente', 'sv/sv08/039'),
    ('sv08-040', 'Mantine', 'Surging Sparks', 'Común', 'sv/sv08/040'),
    ('sv08-041', 'Feebas', 'Surging Sparks', 'Común', 'sv/sv08/041'),
    ('sv08-042', 'Milotic ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/042'),
    ('sv08-043', 'Spheal', 'Surging Sparks', 'Común', 'sv/sv08/043'),
    ('sv08-044', 'Sealeo', 'Surging Sparks', 'Común', 'sv/sv08/044'),
    ('sv08-045', 'Walrein', 'Surging Sparks', 'Infrecuente', 'sv/sv08/045'),
    ('sv08-046', 'Shellos', 'Surging Sparks', 'Común', 'sv/sv08/046'),
    ('sv08-047', 'Cryogonal', 'Surging Sparks', 'Común', 'sv/sv08/047'),
    ('sv08-048', 'Black Kyurem ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/048'),
    ('sv08-049', 'Bruxish', 'Surging Sparks', 'Infrecuente', 'sv/sv08/049'),
    ('sv08-050', 'Quaxly', 'Surging Sparks', 'Común', 'sv/sv08/050'),
    ('sv08-051', 'Quaxwell', 'Surging Sparks', 'Común', 'sv/sv08/051'),
    ('sv08-052', 'Quaquaval', 'Surging Sparks', 'Infrecuente', 'sv/sv08/052'),
    ('sv08-053', 'Cetoddle', 'Surging Sparks', 'Común', 'sv/sv08/053'),
    ('sv08-054', 'Cetitan', 'Surging Sparks', 'Común', 'sv/sv08/054'),
    ('sv08-055', 'Iron Bundle', 'Surging Sparks', 'Infrecuente', 'sv/sv08/055'),
    ('sv08-056', 'Chien-Pao', 'Surging Sparks', 'Rara', 'sv/sv08/056'),
    ('sv08-057', 'Pikachu ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/057'),
    ('sv08-058', 'Magnemite', 'Surging Sparks', 'Común', 'sv/sv08/058'),
    ('sv08-059', 'Magneton', 'Surging Sparks', 'Infrecuente', 'sv/sv08/059'),
    ('sv08-060', 'Magnezone', 'Surging Sparks', 'Infrecuente', 'sv/sv08/060'),
    ('sv08-061', 'Rotom', 'Surging Sparks', 'Común', 'sv/sv08/061'),
    ('sv08-062', 'Blitzle', 'Surging Sparks', 'Común', 'sv/sv08/062'),
    ('sv08-063', 'Zebstrika', 'Surging Sparks', 'Común', 'sv/sv08/063'),
    ('sv08-064', 'Stunfisk', 'Surging Sparks', 'Común', 'sv/sv08/064'),
    ('sv08-065', 'Tapu Koko', 'Surging Sparks', 'Rara', 'sv/sv08/065'),
    ('sv08-066', 'Wattrel', 'Surging Sparks', 'Común', 'sv/sv08/066'),
    ('sv08-067', 'Kilowattrel', 'Surging Sparks', 'Infrecuente', 'sv/sv08/067'),
    ('sv08-068', 'Kilowattrel ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/068'),
    ('sv08-069', 'Miraidon', 'Surging Sparks', 'Infrecuente', 'sv/sv08/069'),
    ('sv08-070', 'Togepi', 'Surging Sparks', 'Común', 'sv/sv08/070'),
    ('sv08-071', 'Togetic', 'Surging Sparks', 'Común', 'sv/sv08/071'),
    ('sv08-072', 'Togekiss', 'Surging Sparks', 'Rara', 'sv/sv08/072'),
    ('sv08-073', 'Marill', 'Surging Sparks', 'Común', 'sv/sv08/073'),
    ('sv08-074', 'Azumarill', 'Surging Sparks', 'Infrecuente', 'sv/sv08/074'),
    ('sv08-075', 'Smoochum', 'Surging Sparks', 'Común', 'sv/sv08/075'),
    ('sv08-076', 'Latias ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/076'),
    ('sv08-077', 'Latios', 'Surging Sparks', 'Infrecuente', 'sv/sv08/077'),
    ('sv08-078', 'Uxie', 'Surging Sparks', 'Común', 'sv/sv08/078'),
    ('sv08-079', 'Mesprit', 'Surging Sparks', 'Común', 'sv/sv08/079'),
    ('sv08-080', 'Azelf', 'Surging Sparks', 'Común', 'sv/sv08/080'),
    ('sv08-081', 'Sigilyph', 'Surging Sparks', 'Común', 'sv/sv08/081'),
    ('sv08-082', 'Yamask', 'Surging Sparks', 'Común', 'sv/sv08/082'),
    ('sv08-083', 'Cofagrigus', 'Surging Sparks', 'Rara', 'sv/sv08/083'),
    ('sv08-084', 'Espurr', 'Surging Sparks', 'Común', 'sv/sv08/084'),
    ('sv08-085', 'Meowstic', 'Surging Sparks', 'Infrecuente', 'sv/sv08/085'),
    ('sv08-086', 'Sylveon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/086'),
    ('sv08-087', 'Dedenne', 'Surging Sparks', 'Común', 'sv/sv08/087'),
    ('sv08-088', 'Xerneas', 'Surging Sparks', 'Infrecuente', 'sv/sv08/088'),
    ('sv08-089', 'Oricorio', 'Surging Sparks', 'Común', 'sv/sv08/089'),
    ('sv08-090', 'Sandygast', 'Surging Sparks', 'Común', 'sv/sv08/090'),
    ('sv08-091', 'Palossand ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/091'),
    ('sv08-092', 'Tapu Lele', 'Surging Sparks', 'Rara', 'sv/sv08/092'),
    ('sv08-093', 'Indeedee', 'Surging Sparks', 'Infrecuente', 'sv/sv08/093'),
    ('sv08-094', 'Flittle', 'Surging Sparks', 'Común', 'sv/sv08/094'),
    ('sv08-095', 'Espathra', 'Surging Sparks', 'Infrecuente', 'sv/sv08/095'),
    ('sv08-096', 'Flutter Mane', 'Surging Sparks', 'Infrecuente', 'sv/sv08/096'),
    ('sv08-097', 'Gimmighoul', 'Surging Sparks', 'Común', 'sv/sv08/097'),
    ('sv08-098', 'Mankey', 'Surging Sparks', 'Común', 'sv/sv08/098'),
    ('sv08-099', 'Primeape', 'Surging Sparks', 'Común', 'sv/sv08/099'),
    ('sv08-100', 'Annihilape', 'Surging Sparks', 'Infrecuente', 'sv/sv08/100'),
    ('sv08-101', 'Paldean Tauros', 'Surging Sparks', 'Infrecuente', 'sv/sv08/101'),
    ('sv08-102', 'Phanpy', 'Surging Sparks', 'Común', 'sv/sv08/102'),
    ('sv08-103', 'Donphan', 'Surging Sparks', 'Común', 'sv/sv08/103'),
    ('sv08-104', 'Trapinch', 'Surging Sparks', 'Común', 'sv/sv08/104'),
    ('sv08-105', 'Vibrava', 'Surging Sparks', 'Común', 'sv/sv08/105'),
    ('sv08-106', 'Flygon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/106'),
    ('sv08-107', 'Gastrodon', 'Surging Sparks', 'Rara', 'sv/sv08/107'),
    ('sv08-108', 'Drilbur', 'Surging Sparks', 'Común', 'sv/sv08/108'),
    ('sv08-109', 'Excadrill', 'Surging Sparks', 'Común', 'sv/sv08/109'),
    ('sv08-110', 'Landorus', 'Surging Sparks', 'Rara', 'sv/sv08/110'),
    ('sv08-111', 'Passimian', 'Surging Sparks', 'Infrecuente', 'sv/sv08/111'),
    ('sv08-112', 'Clobbopus', 'Surging Sparks', 'Común', 'sv/sv08/112'),
    ('sv08-113', 'Grapploct', 'Surging Sparks', 'Común', 'sv/sv08/113'),
    ('sv08-114', 'Glimmet', 'Surging Sparks', 'Común', 'sv/sv08/114'),
    ('sv08-115', 'Glimmora', 'Surging Sparks', 'Común', 'sv/sv08/115'),
    ('sv08-116', 'Koraidon', 'Surging Sparks', 'Infrecuente', 'sv/sv08/116'),
    ('sv08-117', 'Deino', 'Surging Sparks', 'Común', 'sv/sv08/117'),
    ('sv08-118', 'Zweilous', 'Surging Sparks', 'Común', 'sv/sv08/118'),
    ('sv08-119', 'Hydreigon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/119'),
    ('sv08-120', 'Shroodle', 'Surging Sparks', 'Común', 'sv/sv08/120'),
    ('sv08-121', 'Grafaiai', 'Surging Sparks', 'Infrecuente', 'sv/sv08/121'),
    ('sv08-122', 'Alolan Diglett', 'Surging Sparks', 'Común', 'sv/sv08/122'),
    ('sv08-123', 'Alolan Dugtrio', 'Surging Sparks', 'Infrecuente', 'sv/sv08/123'),
    ('sv08-124', 'Skarmory', 'Surging Sparks', 'Común', 'sv/sv08/124'),
    ('sv08-125', 'Registeel', 'Surging Sparks', 'Infrecuente', 'sv/sv08/125'),
    ('sv08-126', 'Bronzor', 'Surging Sparks', 'Común', 'sv/sv08/126'),
    ('sv08-127', 'Bronzong', 'Surging Sparks', 'Común', 'sv/sv08/127'),
    ('sv08-128', 'Klefki', 'Surging Sparks', 'Común', 'sv/sv08/128'),
    ('sv08-129', 'Duraludon', 'Surging Sparks', 'Común', 'sv/sv08/129'),
    ('sv08-130', 'Archaludon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/130'),
    ('sv08-131', 'Gholdengo', 'Surging Sparks', 'Infrecuente', 'sv/sv08/131'),
    ('sv08-132', 'Iron Crown', 'Surging Sparks', 'Rara', 'sv/sv08/132'),
    ('sv08-133', 'Alolan Exeggutor ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/133'),
    ('sv08-134', 'Altaria', 'Surging Sparks', 'Infrecuente', 'sv/sv08/134'),
    ('sv08-135', 'Dialga', 'Surging Sparks', 'Rara', 'sv/sv08/135'),
    ('sv08-136', 'Palkia', 'Surging Sparks', 'Rara', 'sv/sv08/136'),
    ('sv08-137', 'Turtonator', 'Surging Sparks', 'Infrecuente', 'sv/sv08/137'),
    ('sv08-138', 'Applin', 'Surging Sparks', 'Común', 'sv/sv08/138'),
    ('sv08-139', 'Flapple', 'Surging Sparks', 'Infrecuente', 'sv/sv08/139'),
    ('sv08-140', 'Appletun', 'Surging Sparks', 'Infrecuente', 'sv/sv08/140'),
    ('sv08-141', 'Eternatus', 'Surging Sparks', 'Rara', 'sv/sv08/141'),
    ('sv08-142', 'Tatsugiri ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/142'),
    ('sv08-143', 'Eevee', 'Surging Sparks', 'Común', 'sv/sv08/143'),
    ('sv08-144', 'Snorlax', 'Surging Sparks', 'Común', 'sv/sv08/144'),
    ('sv08-145', 'Slakoth', 'Surging Sparks', 'Común', 'sv/sv08/145'),
    ('sv08-146', 'Vigoroth', 'Surging Sparks', 'Común', 'sv/sv08/146'),
    ('sv08-147', 'Slaking ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/147'),
    ('sv08-148', 'Swablu', 'Surging Sparks', 'Común', 'sv/sv08/148'),
    ('sv08-149', 'Zangoose', 'Surging Sparks', 'Común', 'sv/sv08/149'),
    ('sv08-150', 'Kecleon', 'Surging Sparks', 'Común', 'sv/sv08/150'),
    ('sv08-151', 'Bouffalant', 'Surging Sparks', 'Común', 'sv/sv08/151'),
    ('sv08-152', 'Rufflet', 'Surging Sparks', 'Común', 'sv/sv08/152'),
    ('sv08-153', 'Braviary', 'Surging Sparks', 'Infrecuente', 'sv/sv08/153'),
    ('sv08-154', 'Helioptile', 'Surging Sparks', 'Común', 'sv/sv08/154'),
    ('sv08-155', 'Heliolisk', 'Surging Sparks', 'Común', 'sv/sv08/155'),
    ('sv08-156', 'Oranguru', 'Surging Sparks', 'Común', 'sv/sv08/156'),
    ('sv08-157', 'Tandemaus', 'Surging Sparks', 'Común', 'sv/sv08/157'),
    ('sv08-158', 'Maushold', 'Surging Sparks', 'Infrecuente', 'sv/sv08/158'),
    ('sv08-159', 'Cyclizar ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/159'),
    ('sv08-160', 'Flamigo ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/160'),
    ('sv08-161', 'Terapagos', 'Surging Sparks', 'Rara', 'sv/sv08/161'),
    ('sv08-162', 'Amulet of Hope', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/162'),
    ('sv08-163', 'Babiri Berry', 'Surging Sparks', 'Infrecuente', 'sv/sv08/163'),
    ('sv08-164', 'Brilliant Blender', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/164'),
    ('sv08-165', 'Call Bell', 'Surging Sparks', 'Infrecuente', 'sv/sv08/165'),
    ('sv08-166', 'Chill Teaser Toy', 'Surging Sparks', 'Infrecuente', 'sv/sv08/166'),
    ('sv08-167', "Clemont's Quick Wit", 'Surging Sparks', 'Infrecuente', 'sv/sv08/167'),
    ('sv08-168', 'Colbur Berry', 'Surging Sparks', 'Infrecuente', 'sv/sv08/168'),
    ('sv08-169', 'Counter Gain', 'Surging Sparks', 'Infrecuente', 'sv/sv08/169'),
    ('sv08-170', 'Cyrano', 'Surging Sparks', 'Infrecuente', 'sv/sv08/170'),
    ('sv08-171', 'Deduction Kit', 'Surging Sparks', 'Infrecuente', 'sv/sv08/171'),
    ('sv08-172', 'Dragon Elixir', 'Surging Sparks', 'Infrecuente', 'sv/sv08/172'),
    ('sv08-173', 'Drasna', 'Surging Sparks', 'Común', 'sv/sv08/173'),
    ('sv08-174', 'Drayton', 'Surging Sparks', 'Infrecuente', 'sv/sv08/174'),
    ('sv08-175', 'Dusk Ball', 'Surging Sparks', 'Infrecuente', 'sv/sv08/175'),
    ('sv08-176', 'Energy Search Pro', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/176'),
    ('sv08-177', 'Gravity Mountain', 'Surging Sparks', 'Infrecuente', 'sv/sv08/177'),
    ('sv08-178', "Jasmine's Gaze", 'Surging Sparks', 'Infrecuente', 'sv/sv08/178'),
    ('sv08-179', "Lisia's Appeal", 'Surging Sparks', 'Infrecuente', 'sv/sv08/179'),
    ('sv08-180', 'Lively Stadium', 'Surging Sparks', 'Infrecuente', 'sv/sv08/180'),
    ('sv08-181', 'Meddling Memo', 'Surging Sparks', 'Infrecuente', 'sv/sv08/181'),
    ('sv08-182', 'Megaton Blower', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/182'),
    ('sv08-183', 'Miracle Headset', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/183'),
    ('sv08-184', 'Passho Berry', 'Surging Sparks', 'Infrecuente', 'sv/sv08/184'),
    ('sv08-185', 'Precious Trolley', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/185'),
    ('sv08-186', 'Scramble Switch', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/186'),
    ('sv08-187', 'Surfer', 'Surging Sparks', 'Infrecuente', 'sv/sv08/187'),
    ('sv08-188', 'Technical Machine: Fluorite', 'Surging Sparks', 'Infrecuente', 'sv/sv08/188'),
    ('sv08-189', 'Tera Orb', 'Surging Sparks', 'Infrecuente', 'sv/sv08/189'),
    ('sv08-190', 'Tyme', 'Surging Sparks', 'Infrecuente', 'sv/sv08/190'),
    ('sv08-191', 'Enriching Energy', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/191'),
    ('sv08-192', 'Exeggcute', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/192'),
    ('sv08-193', 'Vivillon', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/193'),
    ('sv08-194', 'Shiinotic', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/194'),
    ('sv08-195', 'Castform Sunny Form', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/195'),
    ('sv08-196', 'Larvesta', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/196'),
    ('sv08-197', 'Ceruledge', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/197'),
    ('sv08-198', 'Feebas', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/198'),
    ('sv08-199', 'Spheal', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/199'),
    ('sv08-200', 'Bruxish', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/200'),
    ('sv08-201', 'Cetitan', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/201'),
    ('sv08-202', 'Stunfisk', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/202'),
    ('sv08-203', 'Latios', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/203'),
    ('sv08-204', 'Mesprit', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/204'),
    ('sv08-205', 'Phanpy', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/205'),
    ('sv08-206', 'Vibrava', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/206'),
    ('sv08-207', 'Clobbopus', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/207'),
    ('sv08-208', 'Alolan Dugtrio', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/208'),
    ('sv08-209', 'Skarmory', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/209'),
    ('sv08-210', 'Flapple', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/210'),
    ('sv08-211', 'Appletun', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/211'),
    ('sv08-212', 'Slakoth', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/212'),
    ('sv08-213', 'Kecleon', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/213'),
    ('sv08-214', 'Braviary', 'Surging Sparks', 'Ilustración Rara', 'sv/sv08/214'),
    ('sv08-215', 'Durant ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/215'),
    ('sv08-216', 'Scovillain ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/216'),
    ('sv08-217', 'Milotic ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/217'),
    ('sv08-218', 'Black Kyurem ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/218'),
    ('sv08-219', 'Pikachu ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/219'),
    ('sv08-220', 'Latias ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/220'),
    ('sv08-221', 'Palossand ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/221'),
    ('sv08-222', 'Flygon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/222'),
    ('sv08-223', 'Hydreigon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/223'),
    ('sv08-224', 'Archaludon ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/224'),
    ('sv08-225', 'Alolan Exeggutor ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/225'),
    ('sv08-226', 'Tatsugiri ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/226'),
    ('sv08-227', 'Slaking ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/227'),
    ('sv08-228', 'Cyclizar ex', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/228'),
    ('sv08-229', "Clemont's Quick Wit", 'Surging Sparks', 'Ultra Rara', 'sv/sv08/229'),
    ('sv08-230', 'Cyrano', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/230'),
    ('sv08-231', 'Drasna', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/231'),
    ('sv08-232', 'Drayton', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/232'),
    ('sv08-233', "Jasmine's Gaze", 'Surging Sparks', 'Ultra Rara', 'sv/sv08/233'),
    ('sv08-234', "Lisia's Appeal", 'Surging Sparks', 'Ultra Rara', 'sv/sv08/234'),
    ('sv08-235', 'Surfer', 'Surging Sparks', 'Ultra Rara', 'sv/sv08/235'),
    ('sv08-236', 'Durant ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/236'),
    ('sv08-237', 'Milotic ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/237'),
    ('sv08-238', 'Pikachu ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/238'),
    ('sv08-239', 'Latias ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/239'),
    ('sv08-240', 'Hydreigon ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/240'),
    ('sv08-241', 'Archaludon ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/241'),
    ('sv08-242', 'Alolan Exeggutor ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/242'),
    ('sv08-243', "Clemont's Quick Wit", 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/243'),
    ('sv08-244', 'Drayton', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/244'),
    ('sv08-245', "Jasmine's Gaze", 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/245'),
    ('sv08-246', "Lisia's Appeal", 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/246'),
    ('sv08-247', 'Pikachu ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/247'),
    ('sv08-248', 'Alolan Exeggutor ex', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/248'),
    ('sv08-249', 'Counter Gain', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/249'),
    ('sv08-250', 'Gravity Mountain', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/250'),
    ('sv08-251', 'Night Stretcher', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/251'),
    ('sv08-252', 'Jet Energy', 'Surging Sparks', 'Secreta / SIR', 'sv/sv08/252'),
    ('base1-1', 'Alakazam', 'Base Set', 'Rara', 'base/base1/1'),
    ('base1-2', 'Blastoise', 'Base Set', 'Rara', 'base/base1/2'),
    ('base1-3', 'Chansey', 'Base Set', 'Rara', 'base/base1/3'),
    ('base1-4', 'Charizard', 'Base Set', 'Rara', 'base/base1/4'),
    ('base1-5', 'Clefairy', 'Base Set', 'Rara', 'base/base1/5'),
    ('base1-6', 'Gyarados', 'Base Set', 'Rara', 'base/base1/6'),
    ('base1-7', 'Hitmonchan', 'Base Set', 'Rara', 'base/base1/7'),
    ('base1-8', 'Machamp', 'Base Set', 'Rara', 'base/base1/8'),
    ('base1-9', 'Magneton', 'Base Set', 'Rara', 'base/base1/9'),
    ('base1-10', 'Mewtwo', 'Base Set', 'Rara', 'base/base1/10'),
    ('base1-11', 'Nidoking', 'Base Set', 'Rara', 'base/base1/11'),
    ('base1-12', 'Ninetales', 'Base Set', 'Rara', 'base/base1/12'),
    ('base1-13', 'Poliwrath', 'Base Set', 'Rara', 'base/base1/13'),
    ('base1-14', 'Raichu', 'Base Set', 'Rara', 'base/base1/14'),
    ('base1-15', 'Venusaur', 'Base Set', 'Rara', 'base/base1/15'),
    ('base1-16', 'Zapdos', 'Base Set', 'Rara', 'base/base1/16'),
    ('base1-17', 'Beedrill', 'Base Set', 'Rara', 'base/base1/17'),
    ('base1-18', 'Dragonair', 'Base Set', 'Rara', 'base/base1/18'),
    ('base1-19', 'Dugtrio', 'Base Set', 'Rara', 'base/base1/19'),
    ('base1-20', 'Electabuzz', 'Base Set', 'Rara', 'base/base1/20'),
    ('base1-21', 'Electrode', 'Base Set', 'Rara', 'base/base1/21'),
    ('base1-22', 'Pidgeotto', 'Base Set', 'Rara', 'base/base1/22'),
    ('base1-23', 'Arcanine', 'Base Set', 'Infrecuente', 'base/base1/23'),
    ('base1-24', 'Charmeleon', 'Base Set', 'Infrecuente', 'base/base1/24'),
    ('base1-25', 'Dewgong', 'Base Set', 'Infrecuente', 'base/base1/25'),
    ('base1-26', 'Dratini', 'Base Set', 'Infrecuente', 'base/base1/26'),
    ('base1-27', "Farfetch'd", 'Base Set', 'Infrecuente', 'base/base1/27'),
    ('base1-28', 'Growlithe', 'Base Set', 'Infrecuente', 'base/base1/28'),
    ('base1-29', 'Haunter', 'Base Set', 'Infrecuente', 'base/base1/29'),
    ('base1-30', 'Ivysaur', 'Base Set', 'Infrecuente', 'base/base1/30'),
    ('base1-31', 'Jynx', 'Base Set', 'Infrecuente', 'base/base1/31'),
    ('base1-32', 'Kadabra', 'Base Set', 'Infrecuente', 'base/base1/32'),
    ('base1-33', 'Kakuna', 'Base Set', 'Infrecuente', 'base/base1/33'),
    ('base1-34', 'Machoke', 'Base Set', 'Infrecuente', 'base/base1/34'),
    ('base1-35', 'Magikarp', 'Base Set', 'Infrecuente', 'base/base1/35'),
    ('base1-36', 'Magmar', 'Base Set', 'Infrecuente', 'base/base1/36'),
    ('base1-37', 'Nidorino', 'Base Set', 'Infrecuente', 'base/base1/37'),
    ('base1-38', 'Poliwhirl', 'Base Set', 'Infrecuente', 'base/base1/38'),
    ('base1-39', 'Porygon', 'Base Set', 'Infrecuente', 'base/base1/39'),
    ('base1-40', 'Raticate', 'Base Set', 'Infrecuente', 'base/base1/40'),
    ('base1-41', 'Seel', 'Base Set', 'Infrecuente', 'base/base1/41'),
    ('base1-42', 'Wartortle', 'Base Set', 'Infrecuente', 'base/base1/42'),
    ('base1-43', 'Abra', 'Base Set', 'Común', 'base/base1/43'),
    ('base1-44', 'Bulbasaur', 'Base Set', 'Común', 'base/base1/44'),
    ('base1-45', 'Caterpie', 'Base Set', 'Común', 'base/base1/45'),
    ('base1-46', 'Charmander', 'Base Set', 'Común', 'base/base1/46'),
    ('base1-47', 'Diglett', 'Base Set', 'Común', 'base/base1/47'),
    ('base1-48', 'Doduo', 'Base Set', 'Común', 'base/base1/48'),
    ('base1-49', 'Drowzee', 'Base Set', 'Común', 'base/base1/49'),
    ('base1-50', 'Gastly', 'Base Set', 'Común', 'base/base1/50'),
    ('base1-51', 'Koffing', 'Base Set', 'Común', 'base/base1/51'),
    ('base1-52', 'Machop', 'Base Set', 'Común', 'base/base1/52'),
    ('base1-53', 'Magnemite', 'Base Set', 'Común', 'base/base1/53'),
    ('base1-54', 'Metapod', 'Base Set', 'Común', 'base/base1/54'),
    ('base1-55', 'Nidoran♂', 'Base Set', 'Común', 'base/base1/55'),
    ('base1-56', 'Onix', 'Base Set', 'Común', 'base/base1/56'),
    ('base1-57', 'Pidgey', 'Base Set', 'Común', 'base/base1/57'),
    ('base1-58', 'Pikachu', 'Base Set', 'Común', 'base/base1/58'),
    ('base1-59', 'Poliwag', 'Base Set', 'Común', 'base/base1/59'),
    ('base1-60', 'Ponyta', 'Base Set', 'Común', 'base/base1/60'),
    ('base1-61', 'Rattata', 'Base Set', 'Común', 'base/base1/61'),
    ('base1-62', 'Sandshrew', 'Base Set', 'Común', 'base/base1/62'),
    ('base1-63', 'Squirtle', 'Base Set', 'Común', 'base/base1/63'),
    ('base1-64', 'Starmie', 'Base Set', 'Común', 'base/base1/64'),
    ('base1-65', 'Staryu', 'Base Set', 'Común', 'base/base1/65'),
    ('base1-66', 'Tangela', 'Base Set', 'Común', 'base/base1/66'),
    ('base1-67', 'Voltorb', 'Base Set', 'Común', 'base/base1/67'),
    ('base1-68', 'Vulpix', 'Base Set', 'Común', 'base/base1/68'),
    ('base1-69', 'Weedle', 'Base Set', 'Común', 'base/base1/69'),
    ('base1-70', 'Clefairy Doll', 'Base Set', 'Rara', 'base/base1/70'),
    ('base1-71', 'Computer Search', 'Base Set', 'Rara', 'base/base1/71'),
    ('base1-72', 'Devolution Spray', 'Base Set', 'Rara', 'base/base1/72'),
    ('base1-73', 'Impostor Professor Oak', 'Base Set', 'Rara', 'base/base1/73'),
    ('base1-74', 'Item Finder', 'Base Set', 'Rara', 'base/base1/74'),
    ('base1-75', 'Lass', 'Base Set', 'Rara', 'base/base1/75'),
    ('base1-76', 'Pokémon Breeder', 'Base Set', 'Rara', 'base/base1/76'),
    ('base1-77', 'Pokémon Trader', 'Base Set', 'Rara', 'base/base1/77'),
    ('base1-78', 'Scoop Up', 'Base Set', 'Rara', 'base/base1/78'),
    ('base1-79', 'Super Energy Removal', 'Base Set', 'Rara', 'base/base1/79'),
    ('base1-80', 'Defender', 'Base Set', 'Infrecuente', 'base/base1/80'),
    ('base1-81', 'Energy Retrieval', 'Base Set', 'Infrecuente', 'base/base1/81'),
    ('base1-82', 'Full Heal', 'Base Set', 'Infrecuente', 'base/base1/82'),
    ('base1-83', 'Maintenance', 'Base Set', 'Infrecuente', 'base/base1/83'),
    ('base1-84', 'PlusPower', 'Base Set', 'Infrecuente', 'base/base1/84'),
    ('base1-85', 'Pokémon Center', 'Base Set', 'Infrecuente', 'base/base1/85'),
    ('base1-86', 'Pokémon Flute', 'Base Set', 'Infrecuente', 'base/base1/86'),
    ('base1-87', 'Pokédex', 'Base Set', 'Infrecuente', 'base/base1/87'),
    ('base1-88', 'Professor Oak', 'Base Set', 'Infrecuente', 'base/base1/88'),
    ('base1-89', 'Revive', 'Base Set', 'Infrecuente', 'base/base1/89'),
    ('base1-90', 'Super Potion', 'Base Set', 'Infrecuente', 'base/base1/90'),
    ('base1-91', 'Bill', 'Base Set', 'Común', 'base/base1/91'),
    ('base1-92', 'Energy Removal', 'Base Set', 'Común', 'base/base1/92'),
    ('base1-93', 'Gust of Wind', 'Base Set', 'Común', 'base/base1/93'),
    ('base1-94', 'Potion', 'Base Set', 'Común', 'base/base1/94'),
    ('base1-95', 'Switch', 'Base Set', 'Común', 'base/base1/95'),
    ('base1-96', 'Double Colorless Energy', 'Base Set', 'Infrecuente', 'base/base1/96'),
    ('base1-97', 'Fighting Energy', 'Base Set', 'Común', 'base/base1/97'),
    ('base1-98', 'Fire Energy', 'Base Set', 'Común', 'base/base1/98'),
    ('base1-99', 'Grass Energy', 'Base Set', 'Común', 'base/base1/99'),
    ('base1-100', 'Lightning Energy', 'Base Set', 'Común', 'base/base1/100'),
    ('base1-101', 'Psychic Energy', 'Base Set', 'Común', 'base/base1/101'),
    ('base1-102', 'Water Energy', 'Base Set', 'Común', 'base/base1/102'),
    ('swsh12.5-001', 'Oddish', 'Crown Zenith', 'Común', 'swsh/swsh12.5/001'),
    ('swsh12.5-002', 'Gloom', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/002'),
    ('swsh12.5-003', 'Bellossom', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/003'),
    ('swsh12.5-004', 'Tangela', 'Crown Zenith', 'Común', 'swsh/swsh12.5/004'),
    ('swsh12.5-005', 'Tangrowth', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/005'),
    ('swsh12.5-006', 'Scyther', 'Crown Zenith', 'Común', 'swsh/swsh12.5/006'),
    ('swsh12.5-007', 'Sunkern', 'Crown Zenith', 'Común', 'swsh/swsh12.5/007'),
    ('swsh12.5-008', 'Yanma', 'Crown Zenith', 'Común', 'swsh/swsh12.5/008'),
    ('swsh12.5-009', 'Yanmega', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/009'),
    ('swsh12.5-010', 'Kricketot', 'Crown Zenith', 'Común', 'swsh/swsh12.5/010'),
    ('swsh12.5-011', 'Cherubi', 'Crown Zenith', 'Común', 'swsh/swsh12.5/011'),
    ('swsh12.5-012', 'Carnivine', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/012'),
    ('swsh12.5-013', 'Leafeon V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/013'),
    ('swsh12.5-014', 'Leafeon VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/014'),
    ('swsh12.5-015', 'Grubbin', 'Crown Zenith', 'Común', 'swsh/swsh12.5/015'),
    ('swsh12.5-016', 'Zarude', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/016'),
    ('swsh12.5-017', 'Calyrex', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/017'),
    ('swsh12.5-018', 'Charizard V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/018'),
    ('swsh12.5-019', 'Charizard VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/019'),
    ('swsh12.5-020', 'Radiant Charizard', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/020'),
    ('swsh12.5-021', 'Entei', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/021'),
    ('swsh12.5-022', 'Simisear V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/022'),
    ('swsh12.5-023', 'Simisear VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/023'),
    ('swsh12.5-024', 'Larvesta', 'Crown Zenith', 'Común', 'swsh/swsh12.5/024'),
    ('swsh12.5-025', 'Volcarona', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/025'),
    ('swsh12.5-026', 'Volcanion', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/026'),
    ('swsh12.5-027', 'Salandit', 'Crown Zenith', 'Común', 'swsh/swsh12.5/027'),
    ('swsh12.5-028', 'Salazzle', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/028'),
    ('swsh12.5-029', 'Seel', 'Crown Zenith', 'Común', 'swsh/swsh12.5/029'),
    ('swsh12.5-030', 'Galarian Mr. Mime', 'Crown Zenith', 'Común', 'swsh/swsh12.5/030'),
    ('swsh12.5-031', 'Wailmer', 'Crown Zenith', 'Común', 'swsh/swsh12.5/031'),
    ('swsh12.5-032', 'Wailord', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/032'),
    ('swsh12.5-033', 'Corphish', 'Crown Zenith', 'Común', 'swsh/swsh12.5/033'),
    ('swsh12.5-034', 'Snorunt', 'Crown Zenith', 'Común', 'swsh/swsh12.5/034'),
    ('swsh12.5-035', 'Luvdisc', 'Crown Zenith', 'Común', 'swsh/swsh12.5/035'),
    ('swsh12.5-036', 'Kyogre', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/036'),
    ('swsh12.5-037', 'Kyogre V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/037'),
    ('swsh12.5-038', 'Glaceon V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/038'),
    ('swsh12.5-039', 'Shinx', 'Crown Zenith', 'Común', 'swsh/swsh12.5/039'),
    ('swsh12.5-040', 'Shinx', 'Crown Zenith', 'Común', 'swsh/swsh12.5/040'),
    ('swsh12.5-041', 'Luxio', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/041'),
    ('swsh12.5-042', 'Luxio', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/042'),
    ('swsh12.5-043', 'Luxray', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/043'),
    ('swsh12.5-044', 'Luxray', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/044'),
    ('swsh12.5-045', 'Rotom V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/045'),
    ('swsh12.5-046', 'Rotom VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/046'),
    ('swsh12.5-047', 'Emolga', 'Crown Zenith', 'Común', 'swsh/swsh12.5/047'),
    ('swsh12.5-048', 'Eelektrik', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/048'),
    ('swsh12.5-049', 'Helioptile', 'Crown Zenith', 'Común', 'swsh/swsh12.5/049'),
    ('swsh12.5-050', 'Heliolisk', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/050'),
    ('swsh12.5-051', 'Radiant Charjabug', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/051'),
    ('swsh12.5-052', 'Zeraora', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/052'),
    ('swsh12.5-053', 'Zeraora V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/053'),
    ('swsh12.5-054', 'Zeraora VMAX', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/054'),
    ('swsh12.5-055', 'Zeraora VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/055'),
    ('swsh12.5-056', 'Pincurchin', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/056'),
    ('swsh12.5-057', 'Exeggcute', 'Crown Zenith', 'Común', 'swsh/swsh12.5/057'),
    ('swsh12.5-058', 'Exeggutor', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/058'),
    ('swsh12.5-059', 'Mewtwo', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/059'),
    ('swsh12.5-060', 'Mew V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/060'),
    ('swsh12.5-061', 'Girafarig', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/061'),
    ('swsh12.5-062', 'Lunatone', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/062'),
    ('swsh12.5-063', 'Dusclops', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/063'),
    ('swsh12.5-064', 'Tapu Lele', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/064'),
    ('swsh12.5-065', 'Hatterene V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/065'),
    ('swsh12.5-066', 'Hatterene VMAX', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/066'),
    ('swsh12.5-067', 'Enamorus', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/067'),
    ('swsh12.5-068', 'Graveler', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/068'),
    ('swsh12.5-069', 'Solrock', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/069'),
    ('swsh12.5-070', 'Baltoy', 'Crown Zenith', 'Común', 'swsh/swsh12.5/070'),
    ('swsh12.5-071', 'Riolu', 'Crown Zenith', 'Común', 'swsh/swsh12.5/071'),
    ('swsh12.5-072', 'Pancham', 'Crown Zenith', 'Común', 'swsh/swsh12.5/072'),
    ('swsh12.5-073', 'Rockruff', 'Crown Zenith', 'Común', 'swsh/swsh12.5/073'),
    ('swsh12.5-074', 'Lycanroc', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/074'),
    ('swsh12.5-075', 'Koffing', 'Crown Zenith', 'Común', 'swsh/swsh12.5/075'),
    ('swsh12.5-076', 'Absol', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/076'),
    ('swsh12.5-077', 'Purrloin', 'Crown Zenith', 'Común', 'swsh/swsh12.5/077'),
    ('swsh12.5-078', 'Liepard', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/078'),
    ('swsh12.5-079', 'Krokorok', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/079'),
    ('swsh12.5-080', 'Pangoro', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/080'),
    ('swsh12.5-081', 'Skrelp', 'Crown Zenith', 'Común', 'swsh/swsh12.5/081'),
    ('swsh12.5-082', 'Dragalge', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/082'),
    ('swsh12.5-083', 'Hoopa', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/083'),
    ('swsh12.5-084', 'Galarian Meowth', 'Crown Zenith', 'Común', 'swsh/swsh12.5/084'),
    ('swsh12.5-085', 'Galarian Perrserker', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/085'),
    ('swsh12.5-086', 'Scizor', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/086'),
    ('swsh12.5-087', 'Aron', 'Crown Zenith', 'Común', 'swsh/swsh12.5/087'),
    ('swsh12.5-088', 'Lairon', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/088'),
    ('swsh12.5-089', 'Aggron', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/089'),
    ('swsh12.5-090', 'Metang', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/090'),
    ('swsh12.5-091', 'Pawniard', 'Crown Zenith', 'Común', 'swsh/swsh12.5/091'),
    ('swsh12.5-092', 'Pawniard', 'Crown Zenith', 'Común', 'swsh/swsh12.5/092'),
    ('swsh12.5-093', 'Bisharp', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/093'),
    ('swsh12.5-094', 'Zacian', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/094'),
    ('swsh12.5-095', 'Zacian V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/095'),
    ('swsh12.5-096', 'Zacian VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/096'),
    ('swsh12.5-097', 'Zamazenta', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/097'),
    ('swsh12.5-098', 'Zamazenta V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/098'),
    ('swsh12.5-099', 'Zamazenta VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/099'),
    ('swsh12.5-100', 'Rayquaza V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/100'),
    ('swsh12.5-101', 'Rayquaza VMAX', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/101'),
    ('swsh12.5-102', 'Rayquaza VMAX', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/102'),
    ('swsh12.5-103', 'Duraludon V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/103'),
    ('swsh12.5-104', 'Duraludon VMAX', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/104'),
    ('swsh12.5-105', 'Radiant Eternatus', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/105'),
    ('swsh12.5-106', 'Tauros', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/106'),
    ('swsh12.5-107', 'Ditto', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/107'),
    ('swsh12.5-108', 'Eevee V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/108'),
    ('swsh12.5-109', 'Snorlax', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/109'),
    ('swsh12.5-110', 'Starly', 'Crown Zenith', 'Común', 'swsh/swsh12.5/110'),
    ('swsh12.5-111', 'Bidoof', 'Crown Zenith', 'Común', 'swsh/swsh12.5/111'),
    ('swsh12.5-112', 'Chatot', 'Crown Zenith', 'Común', 'swsh/swsh12.5/112'),
    ('swsh12.5-113', 'Regigigas V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/113'),
    ('swsh12.5-114', 'Regigigas VSTAR', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/114'),
    ('swsh12.5-115', 'Shaymin', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/115'),
    ('swsh12.5-116', 'Stoutland V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/116'),
    ('swsh12.5-117', 'Yungoos', 'Crown Zenith', 'Común', 'swsh/swsh12.5/117'),
    ('swsh12.5-118', 'Gumshoos', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/118'),
    ('swsh12.5-119', 'Oranguru', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/119'),
    ('swsh12.5-120', 'Greedent V', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/120'),
    ('swsh12.5-121', 'Wooloo', 'Crown Zenith', 'Común', 'swsh/swsh12.5/121'),
    ('swsh12.5-122', 'Dubwool', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/122'),
    ('swsh12.5-123', 'Bea', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/123'),
    ('swsh12.5-124', 'Bede', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/124'),
    ('swsh12.5-125', 'Crushing Hammer', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/125'),
    ('swsh12.5-126', 'Digging Duo', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/126'),
    ('swsh12.5-127', 'Energy Retrieval', 'Crown Zenith', 'Común', 'swsh/swsh12.5/127'),
    ('swsh12.5-128', 'Energy Search', 'Crown Zenith', 'Común', 'swsh/swsh12.5/128'),
    ('swsh12.5-129', 'Energy Switch', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/129'),
    ('swsh12.5-130', 'Friends in Hisui', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/130'),
    ('swsh12.5-131', 'Friends in Sinnoh', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/131'),
    ('swsh12.5-132', 'Great Ball', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/132'),
    ('swsh12.5-133', 'Hop', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/133'),
    ('swsh12.5-134', 'Leon', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/134'),
    ('swsh12.5-135', 'Lost Vacuum', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/135'),
    ('swsh12.5-136', 'Nessa', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/136'),
    ('swsh12.5-137', 'Poké Ball', 'Crown Zenith', 'Común', 'swsh/swsh12.5/137'),
    ('swsh12.5-138', 'Pokémon Catcher', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/138'),
    ('swsh12.5-139', 'Potion', 'Crown Zenith', 'Común', 'swsh/swsh12.5/139'),
    ('swsh12.5-140', 'Raihan', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/140'),
    ('swsh12.5-141', 'Rare Candy', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/141'),
    ('swsh12.5-142', 'Rescue Carrier', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/142'),
    ('swsh12.5-143', 'Sky Seal Stone', 'Crown Zenith', 'Rara', 'swsh/swsh12.5/143'),
    ('swsh12.5-144', 'Switch', 'Crown Zenith', 'Común', 'swsh/swsh12.5/144'),
    ('swsh12.5-145', 'Trekking Shoes', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/145'),
    ('swsh12.5-146', 'Ultra Ball', 'Crown Zenith', 'Infrecuente', 'swsh/swsh12.5/146'),
    ('swsh12.5-147', "Elesa's Sparkle", 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/147'),
    ('swsh12.5-148', 'Friends in Hisui', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/148'),
    ('swsh12.5-149', 'Friends in Sinnoh', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/149'),
    ('swsh12.5-150', "Professor's Research", 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/150'),
    ('swsh12.5-151', 'Volo', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/151'),
    ('swsh12.5-152', 'Grass Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/152'),
    ('swsh12.5-153', 'Fire Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/153'),
    ('swsh12.5-154', 'Water Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/154'),
    ('swsh12.5-155', 'Lightning Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/155'),
    ('swsh12.5-156', 'Psychic Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/156'),
    ('swsh12.5-157', 'Fighting Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/157'),
    ('swsh12.5-158', 'Darkness Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/158'),
    ('swsh12.5-159', 'Metal Energy', 'Crown Zenith', 'Ultra Rara', 'swsh/swsh12.5/159'),
    ('swsh12.5-160', 'Pikachu', 'Crown Zenith', 'Secreta / SIR', 'swsh/swsh12.5/160'),
]

_CARDS_BY_TIER: dict[str, list] = {}
for _entry in TCG_CATALOG:
    _CARDS_BY_TIER.setdefault(_entry[3], []).append(_entry)


def _to_card_dict(entry: tuple) -> dict:
    cid, name, set_name, rarity, rel = entry
    base = rel if rel.startswith("http") else f"{TCGDEX_IMG_PREFIX}{rel}"
    return {
        "card_id": cid,
        "name": name,
        "set_name": set_name,
        "rarity": rarity,
        "image_url": f"{base}/high.png",
        "low_image_url": f"{base}/low.png",
    }


def roll_booster_pack() -> List[dict]:
    """
    Genera un Mystery Booster Pack de 10 cartas reales de Pokémon TCG:
    - Cartas 1 a 9: completamente aleatorias con pull rates inspirados en sobres reales.
    - Carta 10 (Hit Final): SIEMPRE de mayor rareza (Rara o superior).
    """
    main_tiers = ["Común", "Infrecuente", "Rara", "Ultra Rara", "Ilustración Rara", "Secreta / SIR"]
    main_weights = [52.0, 30.0, 13.0, 3.5, 1.1, 0.4]

    hit_tiers = ["Rara", "Ultra Rara", "Ilustración Rara", "Secreta / SIR"]
    hit_weights = [58.0, 24.0, 12.0, 6.0]

    chosen_ids = set()
    pack: List[dict] = []

    for slot in range(10):
        if slot < 9:
            tier = random.choices(main_tiers, weights=main_weights, k=1)[0]
        else:
            tier = random.choices(hit_tiers, weights=hit_weights, k=1)[0]

        pool = _CARDS_BY_TIER.get(tier) or TCG_CATALOG
        candidates = [c for c in pool if c[0] not in chosen_ids] or pool
        picked = random.choice(candidates)
        chosen_ids.add(picked[0])
        pack.append(_to_card_dict(picked))

    return pack


def _load_font(size: int, bold: bool = False):
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


def _fetch_card_bytes(url: str) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VictiniBot-SNAP/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read()
    except Exception:
        return None


def build_booster_pack_grid_png(cards: List[dict], username: str) -> bytes:
    """Genera una grilla PNG 5x2 (1340x820) con las 10 cartas reales del Booster Pack."""
    W, H = 1340, 820
    img = Image.new("RGBA", (W, H), (14, 15, 32, 255))
    draw = ImageDraw.Draw(img)

    for y in range(H):
        r = int(14 + (y / H) * 18)
        g = int(15 + (y / H) * 10)
        b = int(32 + (y / H) * 24)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    draw.rounded_rectangle([10, 10, W - 11, H - 11], radius=22, outline=(255, 107, 53, 235), width=3)

    font_header = _load_font(28, bold=True)
    font_sub = _load_font(17, bold=False)
    font_name = _load_font(15, bold=True)
    font_rar = _load_font(13, bold=True)

    draw.text((34, 24), f"VICTINI MYSTERY BOOSTER PACK  •  {username[:24]}", font=font_header, fill=(255, 210, 76, 255))
    draw.text((34, 60), "10 cartas reales de Pokémon TCG • ¡La carta #10 garantiza un HIT de mayor rareza!", font=font_sub, fill=(205, 210, 235, 255))

    urls = [c.get("low_image_url") or c["image_url"] for c in cards[:10]]
    with ThreadPoolExecutor(max_workers=10) as ex:
        raw_images = list(ex.map(_fetch_card_bytes, urls))

    cols = 5
    card_w, card_h = 216, 300
    gap_x, gap_y = 42, 46
    start_x, start_y = 46, 104

    for idx, (card, raw_bytes) in enumerate(zip(cards[:10], raw_images)):
        col = idx % cols
        row = idx // cols
        x = start_x + col * (card_w + gap_x)
        y = start_y + row * (card_h + gap_y)

        style = TCG_RARITY_STYLE.get(card["rarity"], TCG_RARITY_STYLE["Común"])
        border_col = style["color"]
        border_w = 4 if idx == 9 or card["rarity"] in ("Ultra Rara", "Ilustración Rara", "Secreta / SIR") else 2

        draw.rounded_rectangle([x - 4, y - 4, x + card_w + 4, y + card_h + 4], radius=14, outline=border_col + (255,), width=border_w)

        if raw_bytes:
            try:
                c_img = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
                c_img = c_img.resize((card_w, card_h), Image.Resampling.LANCZOS)
                mask = Image.new("L", (card_w, card_h), 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=11, fill=255)
                img.paste(c_img, (x, y), mask)
            except Exception:
                draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=11, fill=(32, 34, 62, 255))
        else:
            draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=11, fill=(32, 34, 62, 255))

        label = f"#{idx + 1} {card['name'][:19]}"
        draw.text((x + 2, y + card_h + 7), label, font=font_name, fill=(255, 255, 255, 255))
        rar_txt = f"{card['rarity']}" + (" [HIT]" if idx == 9 else "")
        draw.text((x + 2, y + card_h + 25), rar_txt, font=font_rar, fill=border_col + (255,))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class BoosterPackView(discord.ui.View):
    """Vista interactiva con botón para abrir el Mystery Booster Pack de 10 cartas al subir de nivel."""

    def __init__(
        self,
        guild_id: int,
        author_id: int,
        author_name: str,
        new_level: int,
        on_backup: Optional[Callable[[discord.Guild, bool], Awaitable[None]]] = None,
    ):
        super().__init__(timeout=3600)
        self.guild_id = guild_id
        self.author_id = author_id
        self.author_name = author_name
        self.new_level = new_level
        self.on_backup = on_backup
        self.opened = False

    @discord.ui.button(label="🎴 ¡Abrir Booster Pack! (10 Cartas)", style=discord.ButtonStyle.danger)
    async def open_pack_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🔥 *¡Este Booster Pack misterioso es de otro entrenador!* Subí de nivel para conseguir el tuyo.",
                ephemeral=True,
            )
            return

        if self.opened:
            await interaction.response.send_message("🎴 ¡Este sobre ya fue abierto!", ephemeral=True)
            return

        self.opened = True
        button.disabled = True
        button.label = "✅ Sobre abierto"
        await interaction.response.defer()

        try:
            cards = roll_booster_pack()
            add_tcg_cards(self.guild_id, self.author_id, cards, time.time())
            png_bytes = await asyncio.to_thread(build_booster_pack_grid_png, cards, self.author_name)

            lines = []
            for idx, c in enumerate(cards, start=1):
                st = TCG_RARITY_STYLE.get(c["rarity"], TCG_RARITY_STYLE["Común"])
                hit_tag = " **★ HIT FINAL**" if idx == 10 else ""
                lines.append(
                    f"`#{idx:02d}` {st['emoji']} **[{c['name']}]({c['image_url']})** — *{c['rarity']}* (`{c['set_name']}`){hit_tag}"
                )

            hit_card = cards[-1]
            hit_style = TCG_RARITY_STYLE.get(hit_card["rarity"], TCG_RARITY_STYLE["Rara"])
            collection_url = f"{WEB_PORTAL_URL}/coleccion/{self.guild_id}/{self.author_id}"

            embed = discord.Embed(
                title=f"🎴 ¡BOOSTER PACK MISTERIOSO DE {self.author_name.upper()}! (Nv. {self.new_level}) 🔥",
                description="\n".join(lines),
                color=hit_style["embed_color"],
            )
            embed.set_image(url="attachment://booster_pack.png")
            embed.set_footer(text="Todas las cartas se guardaron en tu colección • Victini Bot 🔥✌️")

            result_view = discord.ui.View()
            result_view.add_item(
                discord.ui.Button(
                    label="🃏 Ver mi colección TCG en la Web",
                    style=discord.ButtonStyle.link,
                    url=collection_url,
                )
            )

            file = discord.File(io.BytesIO(png_bytes), filename="booster_pack.png")
            await interaction.edit_original_response(embed=embed, attachments=[file], view=result_view)
            if self.on_backup and interaction.guild:
                asyncio.create_task(self.on_backup(interaction.guild, True))
        except Exception as e:
            print(f"⚠️ Error abriendo Booster Pack: {e}", flush=True)
            await interaction.followup.send(
                "❌ Hubo un problema al abrir el Booster Pack. Intentá de nuevo en un momento.",
                ephemeral=True,
              )
