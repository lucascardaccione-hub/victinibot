import os
import time
import urllib.request
from threading import Thread
from flask import Flask, jsonify
from database import get_global_web_leaderboard, get_user_tcg_cards

app = Flask("")


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/health")
def health():
    return jsonify({"status": "ok", "bot": "Victini Bot - SNAP!"})


@app.route("/api/leaderboard")
def api_leaderboard():
    return jsonify(get_global_web_leaderboard(limit=50))


@app.route("/api/coleccion/<int:guild_id>/<int:user_id>")
def api_coleccion(guild_id: int, user_id: int):
    return jsonify(get_user_tcg_cards(guild_id, user_id))


@app.route("/coleccion/<int:guild_id>/<int:user_id>")
def coleccion_page(guild_id: int, user_id: int):
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Colección Pokémon TCG • SNAP!</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {{
                --bg: #0f1020;
                --card: #191b33;
                --accent: #ff9f1c;
                --border: #ff6b35;
                --text: #f4f4f9;
            }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: radial-gradient(circle at top, #1f1b3a 0%, #0f1020 75%);
                color: var(--text);
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }}
            .wrap {{
                width: 1120px;
                max-width: 100%;
                margin: 0 auto;
            }}
            .topbar {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
                gap: 12px;
                margin-bottom: 18px;
            }}
            .back-btn {{
                display: inline-block;
                padding: 10px 18px;
                background: #2b2e52;
                border: 1px solid var(--border);
                color: #fff;
                text-decoration: none;
                border-radius: 8px;
                font-weight: bold;
            }}
            .back-btn:hover {{ background: #363a66; }}
            .stats {{
                background: var(--card);
                border: 2px solid rgba(255, 107, 53, 0.35);
                border-radius: 14px;
                padding: 18px 22px;
                margin-bottom: 18px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
                gap: 12px;
            }}
            .filters {{
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                margin-bottom: 18px;
            }}
            .filter-btn {{
                padding: 8px 14px;
                border-radius: 999px;
                border: 1px solid rgba(255, 159, 28, 0.45);
                background: #191b33;
                color: #f4f4f9;
                cursor: pointer;
                font-weight: bold;
                font-size: 13px;
            }}
            .filter-btn.active {{
                background: linear-gradient(135deg, #ff6b35, #e71d36);
                border-color: transparent;
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(195px, 1fr));
                gap: 16px;
            }}
            .tcg-card {{
                background: var(--card);
                border: 2px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                padding: 10px;
                text-align: center;
                position: relative;
                transition: transform 0.15s;
            }}
            .tcg-card:hover {{ transform: translateY(-4px); }}
            .tcg-card img {{
                width: 100%;
                border-radius: 8px;
                display: block;
            }}
            .qty-badge {{
                position: absolute;
                top: 16px;
                right: 16px;
                background: rgba(15, 16, 32, 0.9);
                border: 1px solid #ff9f1c;
                color: #ff9f1c;
                font-weight: bold;
                font-size: 12px;
                padding: 3px 8px;
                border-radius: 999px;
            }}
            .card-title {{
                margin: 8px 0 3px;
                font-weight: bold;
                font-size: 14px;
            }}
            .card-meta {{
                font-size: 12px;
                color: #b8b8d1;
            }}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="topbar">
                <a class="back-btn" href="/">⬅️ Volver al Ranking de SNAP!</a>
                <h2 style="margin:0; color:#ff9f1c;">🃏 Colección Pokémon TCG</h2>
            </div>
            <div class="stats" id="statsBox">Cargando colección del entrenador...</div>
            <div class="filters" id="filterBar"></div>
            <div class="grid" id="cardsGrid"></div>
        </div>
        <script>
            let allCards = [];
            let currentFilter = 'Todas';
            const rarityColors = {{
                'Secreta / SIR': '#facc15',
                'Ilustración Rara': '#fb923c',
                'Ultra Rara': '#a855f7',
                'Rara': '#3b82f6',
                'Infrecuente': '#10b981',
                'Común': '#9ca3af'
            }};

            function renderGrid() {{
                const grid = document.getElementById('cardsGrid');
                const list = currentFilter === 'Todas'
                    ? allCards
                    : allCards.filter(c => c.rarity === currentFilter);
                if (!list.length) {{
                    grid.innerHTML = '<p style="color:#aaa;">Todavía no hay cartas en esta categoría.</p>';
                    return;
                }}
                grid.innerHTML = list.map(c => {{
                    const col = rarityColors[c.rarity] || '#9ca3af';
                    const qty = c.qty > 1 ? `<div class="qty-badge">x${{c.qty}}</div>` : '';
                    return `<div class="tcg-card" style="border-color:${{col}};">
                        ${{qty}}
                        <a href="${{c.image_url}}" target="_blank" rel="noopener">
                            <img src="${{c.image_url}}" alt="${{c.name}}" loading="lazy">
                        </a>
                        <div class="card-title">${{c.name}}</div>
                        <div class="card-meta" style="color:${{col}}; font-weight:bold;">${{c.rarity}}</div>
                        <div class="card-meta">${{c.set_name}}</div>
                    </div>`;
                }}).join('');
            }}

            async function loadCollection() {{
                const res = await fetch('/api/coleccion/{guild_id}/{user_id}');
                const data = await res.json();
                allCards = data.cards || [];
                document.getElementById('statsBox').innerHTML = `
                    <div>
                        <div style="font-size:20px; font-weight:bold; color:#ff9f1c;">${{data.username}} <span style="font-size:14px; color:#ccc;">(Nv. ${{data.level}})</span></div>
                        <div style="font-size:13px; color:#b8b8d1;">Cartas obtenidas abriendo Mystery Booster Packs al subir de nivel 🔥</div>
                    </div>
                    <div style="font-size:15px;">
                        🃏 <b>${{data.total_cards}}</b> cartas totales &nbsp;|&nbsp; ✨ <b>${{data.unique_cards}}</b> únicas
                    </div>
                `;
                const tiers = ['Todas', 'Secreta / SIR', 'Ilustración Rara', 'Ultra Rara', 'Rara', 'Infrecuente', 'Común'];
                document.getElementById('filterBar').innerHTML = tiers.map(t =>
                    `<button class="filter-btn ${{t === currentFilter ? 'active' : ''}}" onclick="setFilter('${{t}}')">${{t}}</button>`
                ).join('');
                renderGrid();
            }}

            function setFilter(t) {{
                currentFilter = t;
                loadCollection();
            }}

            loadCollection();
        </script>
    </body>
    </html>
    """


@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>SNAP! Portal & Arcade de Victini 🔥</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {
                --bg: #0f1020;
                --card: #191b33;
                --border: #ff6b35;
                --accent: #ff9f1c;
                --danger: #e71d36;
                --text: #f4f4f9;
            }
            body {
                text-align: center;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: radial-gradient(circle at top, #1f1b3a 0%, #0f1020 75%);
                color: var(--text);
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            h1 {
                color: var(--accent);
                margin-bottom: 6px;
                text-shadow: 0 3px 10px rgba(255, 107, 53, 0.5);
            }
            .subtitle {
                color: #b8b8d1;
                margin-top: 0;
                margin-bottom: 20px;
            }
            .container {
                width: 920px;
                max-width: 100%;
                margin: 0 auto;
            }
            .card {
                background: var(--card);
                border: 2px solid rgba(255, 107, 53, 0.35);
                border-radius: 14px;
                padding: 22px;
                margin-bottom: 20px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.45);
            }
            .tabs {
                display: flex;
                justify-content: center;
                gap: 10px;
                margin-bottom: 18px;
                flex-wrap: wrap;
            }
            button {
                padding: 11px 22px;
                font-size: 15px;
                background: linear-gradient(135deg, #ff6b35, #e71d36);
                color: white;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
                transition: transform 0.15s, opacity 0.15s;
            }
            button:hover {
                transform: translateY(-2px);
                opacity: 0.95;
            }
            button.secondary {
                background: #2b2e52;
                border: 1px solid #ff6b35;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
                font-size: 14px;
            }
            th, td {
                padding: 10px 12px;
                text-align: left;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            th {
                color: var(--accent);
                text-transform: uppercase;
                font-size: 12px;
                letter-spacing: 0.05em;
            }
            .progress-bar {
                background: #101225;
                border-radius: 999px;
                height: 8px;
                width: 110px;
                overflow: hidden;
                display: inline-block;
                vertical-align: middle;
                margin-right: 6px;
            }
            .progress-fill {
                background: linear-gradient(90deg, #ff9f1c, #e71d36);
                height: 100%;
            }
            #gameCanvas {
                border: 3px solid var(--border);
                border-radius: 10px;
                width: 100%;
                background: linear-gradient(to bottom, #1e1a3d 0%, #2c1e4a 68%, #3c222e 68%, #22131a 100%);
                box-shadow: 0 8px 18px rgba(0, 0, 0, 0.5);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔥 Portal SNAP! & Arcade de Victini ✌️</h1>
            <p class="subtitle">Centro de Ranking de Niveles y Minijuego V-Create de la comunidad SNAP!</p>

            <div class="tabs">
                <button onclick="showTab('rankingTab')">🏆 Ranking SNAP! en Vivo</button>
                <button class="secondary" onclick="showTab('arcadeTab')">🎮 Victini V-Create Challenge</button>
            </div>

            <!-- TAB 1: RANKING EN VIVO -->
            <div id="rankingTab" class="card">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">
                    <h2 style="margin:0; color:#ff9f1c;">🌀 Tabla de Posiciones SNAP-LEVEL</h2>
                    <button class="secondary" style="padding:7px 14px; font-size:13px;" onclick="loadLeaderboard()">🔄 Actualizar</button>
                </div>
                <div id="leaderboardContent" style="margin-top:12px;">
                    Cargando ranking...
                </div>
            </div>

            <!-- TAB 2: ARCADE DE VICTINI -->
            <div id="arcadeTab" class="card" style="display:none;">
                <h2 style="margin-top:0; color:#ff9f1c;">🏃‍♂️ Victini V-Create Challenge 🔥</h2>
                <p style="font-size:14px; color:#ccc;">
                    Presioná <b>Espacio</b>, <b>Flecha Arriba</b> o tocá la pantalla para saltar las llamas oscuras.
                </p>
                <canvas id="gameCanvas" width="620" height="220"></canvas>
                <div style="margin-top:12px; font-size:16px; font-weight:bold;">
                    Puntos: <span id="scoreVal" style="color:#ff9f1c;">0</span> |
                    Récord: <span id="highScoreVal" style="color:#2ec4b6;">0</span>
                </div>
                <div style="margin-top:12px;">
                    <button onclick="startArcade()">▶ Iniciar Partida</button>
                </div>
            </div>
        </div>

        <script>
            function showTab(tabId) {
                document.getElementById('rankingTab').style.display = tabId === 'rankingTab' ? 'block' : 'none';
                document.getElementById('arcadeTab').style.display = tabId === 'arcadeTab' ? 'block' : 'none';
            }

            async function loadLeaderboard() {
                const container = document.getElementById('leaderboardContent');
                try {
                    const res = await fetch('/api/leaderboard');
                    const data = await res.json();
                    if (!data.length) {
                        container.innerHTML = '<p style="color:#aaa;">Todavía no hay jugadores con XP registrado. ¡Hablá en el servidor SNAP! para sumar experiencia!</p>';
                        return;
                    }
                    const medals = {1: '🥇', 2: '🥈', 3: '🥉'};
                    let html = '<div style="overflow-x:auto;"><table><thead><tr><th>Pos</th><th>Usuario</th><th>Nivel</th><th>Experiencia</th><th>Pokéballs</th><th>Equipo Pokémon</th><th>Colección TCG</th></tr></thead><tbody>';
                    for (const row of data) {
                        const pos = medals[row.rank] || ('#' + row.rank);
                        const pct = Math.min(100, Math.round((row.xp / row.next_xp) * 100));
                        let teamHtml = '<span style="color:#666; font-size:12px;">Sin Pokémon</span>';
                        if (row.team && row.team.length) {
                            teamHtml = '<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">';
                            for (const mon of row.team) {
                                const shinyPath = mon.is_shiny ? 'shiny/' : '';
                                const imgUrl = `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${shinyPath}${mon.pokedex_id}.png`;
                                const lvlTag = mon.poke_level ? ` Nv.${mon.poke_level}` : '';
                                const badgeTitle = `${mon.is_shiny ? '✨ ' : ''}${mon.name}${lvlTag} (${mon.rarity})`;
                                teamHtml += `<div title="${badgeTitle}" style="display:inline-flex; align-items:center; gap:4px; background:#101225; border:1px solid rgba(255,159,28,0.35); border-radius:999px; padding:2px 8px 2px 4px; font-size:12px;">
                                    <img src="${imgUrl}" alt="${mon.name}" style="width:24px; height:24px; object-fit:contain;">
                                    <span>${mon.is_shiny ? '✨' : ''}${mon.name}</span>
                                    <span style="color:#ff9f1c; font-weight:bold; font-size:11px;">${lvlTag}</span>
                                </div>`;
                            }
                            teamHtml += '</div>';
                        }
                        const tcgTotal = row.tcg_total ?? 0;
                        const tcgUnique = row.tcg_unique ?? 0;
                        const colUrl = `/coleccion/${row.guild_id}/${row.user_id}`;
                        const tcgHtml = `<a href="${colUrl}" style="display:inline-flex; align-items:center; gap:6px; padding:5px 10px; border-radius:8px; background:#23264a; border:1px solid rgba(255,159,28,0.45); color:#ffcf70; text-decoration:none; font-size:12px; font-weight:bold; white-space:nowrap;">🃏 ${tcgTotal} (${tcgUnique}) • Ver colección →</a>`;
                        html += `<tr>
                            <td><b>${pos}</b></td>
                            <td><b>${row.username}</b></td>
                            <td><b style="color:#ff9f1c;">Nv. ${row.level}</b></td>
                            <td>
                                <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                                <span style="font-size:12px; color:#ccc;">${row.xp}/${row.next_xp} XP</span>
                            </td>
                            <td><span style="font-weight:bold; color:#ff6b35;">🎱 ${row.pokeballs ?? 0}</span></td>
                            <td>${teamHtml}</td>
                            <td>${tcgHtml}</td>
                        </tr>`;
                    }
                    html += '</tbody></table></div>';
                    container.innerHTML = html;
                } catch (err) {
                    container.innerHTML = '<p style="color:#e71d36;">No se pudo cargar el ranking.</p>';
                }
            }

            // Arcade de Victini
            const canvas = document.getElementById('gameCanvas');
            const ctx = canvas.getContext('2d');
            let gameRunning = false;
            let score = 0;
            let highScore = Number(localStorage.getItem('victini_best') || 0);
            document.getElementById('highScoreVal').innerText = highScore;

            let victini = { x: 65, y: 120, vy: 0, size: 28, grounded: true };
            let obstacles = [];
            let frame = 0;

            function jump() {
                if (!gameRunning) {
                    startArcade();
                    return;
                }
                if (victini.grounded) {
                    victini.vy = -10.5;
                    victini.grounded = false;
                }
            }

            window.addEventListener('keydown', (e) => {
                if (e.code === 'Space' || e.code === 'ArrowUp') {
                    e.preventDefault();
                    jump();
                }
            });
            canvas.addEventListener('pointerdown', jump);

            function startArcade() {
                victini = { x: 65, y: 120, vy: 0, size: 28, grounded: true };
                obstacles = [];
                score = 0;
                frame = 0;
                gameRunning = true;
                requestAnimationFrame(loop);
            }

            function loop() {
                if (!gameRunning) return;
                frame++;
                ctx.clearRect(0, 0, canvas.width, canvas.height);

                ctx.fillStyle = '#ff6b35';
                ctx.fillRect(0, 150, canvas.width, 3);

                victini.vy += 0.55;
                victini.y += victini.vy;
                if (victini.y >= 122) {
                    victini.y = 122;
                    victini.vy = 0;
                    victini.grounded = true;
                }

                ctx.fillStyle = '#ffb703';
                ctx.fillRect(victini.x, victini.y, victini.size, victini.size);
                ctx.fillStyle = '#fb5607';
                ctx.beginPath();
                ctx.moveTo(victini.x + 2, victini.y);
                ctx.lineTo(victini.x - 4, victini.y - 14);
                ctx.lineTo(victini.x + 12, victini.y);
                ctx.moveTo(victini.x + 16, victini.y);
                ctx.lineTo(victini.x + 32, victini.y - 14);
                ctx.lineTo(victini.x + 26, victini.y);
                ctx.fill();

                if (frame % 75 === 0) {
                    obstacles.push({ x: canvas.width, y: 124, w: 20, h: 26 });
                }

                for (let i = obstacles.length - 1; i >= 0; i--) {
                    let ob = obstacles[i];
                    ob.x -= (5 + Math.min(4, score / 200));
                    ctx.fillStyle = '#e71d36';
                    ctx.fillRect(ob.x, ob.y, ob.w, ob.h);

                    if (
                        victini.x < ob.x + ob.w &&
                        victini.x + victini.size > ob.x &&
                        victini.y < ob.y + ob.h &&
                        victini.y + victini.size > ob.y
                    ) {
                        gameRunning = false;
                        if (score > highScore) {
                            highScore = score;
                            localStorage.setItem('victini_best', highScore);
                            document.getElementById('highScoreVal').innerText = highScore;
                        }
                        ctx.fillStyle = 'rgba(0,0,0,0.65)';
                        ctx.fillRect(0, 0, canvas.width, canvas.height);
                        ctx.fillStyle = '#fff';
                        ctx.font = 'bold 20px Segoe UI';
                        ctx.fillText('💥 ¡Mis llamas te atraparon! Tocá para reintentar 🔥', 85, 110);
                        return;
                    }

                    if (ob.x + ob.w < 0) {
                        obstacles.splice(i, 1);
                    }
                }

                score++;
                document.getElementById('scoreVal').innerText = score;
                requestAnimationFrame(loop);
            }

            loadLeaderboard();
        </script>
    </body>
    </html>
    """


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def self_ping_loop():
    """
    Envía un ping externo cada 8 minutos a la URL pública de Render
    para evitar que el plan gratuito de Render suspenda (spin down) el contenedor tras 15 min de inactividad.
    """
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "https://victini.onrender.com").rstrip("/")
    ping_url = f"{external_url}/health"
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(
                ping_url,
                headers={"User-Agent": "Victini-KeepAlive/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                _ = resp.read()
        except Exception as e:
            print(f"⚠️ Self-ping warning: {e}")
        time.sleep(480)  # Cada 8 minutos


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
    p = Thread(target=self_ping_loop, daemon=True)
    p.start()
