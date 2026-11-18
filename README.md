# 🔥 Victini Bot — Mascota oficial de SNAP!

Bot de Discord diseñado para el servidor **SNAP!** con sistema de bienvenida personalizada, sistema de niveles con base de datos SQLite y ranking paginado con botón **"Ver más..."**.

---

## ✨ Funcionalidades

1. **Bienvenida en `🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺`**:
   - Cada vez que entra un nuevo miembro al servidor, Victini Bot envía automáticamente:
     > *"Bienvenido @username, acá vas a poder hacer muchas cosas y conocer gente muy copada, pero no te pases de vivo/a porque estoy viendo todo"*

2. **Sistema de Niveles en `🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀`**:
   - Los usuarios ganan entre `15` y `25` XP por mensaje (con un cooldown anti-spam de 45 segundos).
   - Cuando un miembro sube de nivel, el aviso se envía **únicamente** por el canal `🌀𝑺𝑵𝑨𝑷-𝑳𝑬𝑽𝑬𝑳🌀`:
     > *"@username ha subido al nivel X. Espero que haya sido de forma legal 👀 o mis llamas actuarán rápidamente con severas consecuencias 🔥😈"*

3. **Comando `/nivel`**:
   - Si estás en el **Top 10**:
     > *"Tu nivel es X, ¡felicitaciones! Estás entre los primeros 10 🔥 (Puesto #N • XP/MAX XP)"*
   - Si estás fuera del Top 10:
     > *"Tu nivel es X, aún te queda mucho camino por recorrer. (Puesto #N • XP/MAX XP)"*

4. **Comando `/ranking`**:
   - Muestra una tabla de posiciones con el **Top 10** (Puesto, Usuario, Nivel y Experiencia).
   - Incluye un botón interactivo **"Ver más... 🔥"** (y **"⬅️ Anterior"**) para ver las siguientes páginas de la tabla de posiciones.

---

## 🚀 Requisitos previos en Discord Developer Portal

1. Entrá a [Discord Developer Portal](https://discord.com/developers/applications) y creá una aplicación llamada **Victini Bot**.
2. En la pestaña **Bot**:
   - Copiá el **Token** para pegarlo en tu archivo `.env`.
   - Activá los siguientes **Privileged Gateway Intents**:
     - ✅ **SERVER MEMBERS INTENT** *(obligatorio para detectar nuevos miembros en `🫂𝑩𝑰𝑬𝑵𝑽𝑬𝑵𝑰𝑫𝑰𝑻𝑻𝑶𝑺`)*
     - ✅ **MESSAGE CONTENT INTENT** *(obligatorio para sumar XP al escribir mensajes)*
3. En **OAuth2 -> URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `View Channels`, `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`
   - Copiá la URL generada e invitá a **Victini Bot** a tu servidor **SNAP!**.

---

## 🛠️ Instalación y Ejecución

```powershell
cd C:\Users\LUCA\.gemini\antigravity\scratch\victini-bot

# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Crear el archivo .env con tu token
copy .env.example .env
# Editá .env y reemplazá TU_TOKEN_DE_DISCORD_AQUI por el token real de tu bot

# 3. Iniciar a Victini Bot
python bot.py
```
