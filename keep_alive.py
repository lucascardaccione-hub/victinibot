import os
import time
import urllib.request
from threading import Thread
from flask import Flask, jsonify
from database import get_global_web_leaderboard

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
    return jsonify(get_global_web_leaderboard(limit=25))


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
                width: 680px;
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
                    let html = '<table><thead><tr><th>Pos</th><th>Usuario</th><th>Nivel</th><th>Experiencia</th></tr></thead><tbody>';
                    for (const row of data) {
                        const pos = medals[row.rank] || ('#' + row.rank);
                        const pct = Math.min(100, Math.round((row.xp / row.next_xp) * 100));
                        html += `<tr>
                            <td><b>${pos}</b></td>
                            <td>${row.username}</td>
                            <td><b style="color:#ff9f1c;">Nv. ${row.level}</b></td>
                            <td>
                                <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                                <span style="font-size:12px; color:#ccc;">${row.xp}/${row.next_xp} XP</span>
                            </td>
                        </tr>`;
                    }
                    html += '</tbody></table>';
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
