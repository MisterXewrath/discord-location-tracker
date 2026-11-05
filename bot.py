"""
Discord Location Bot — Cloud Hosted (Railway / Fly.io)
=======================================================
Receives GPS from OwnTracks (HTTP POST), reverse geocodes to city/state,
tracks miles moved, and updates the bot's Discord status.

Phone (OwnTracks) → Railway (this bot) → Discord
"""

import os
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from math import radians, cos, sin, asin, sqrt
from threading import Thread
import urllib.request
import urllib.error

import discord
from flask import Flask, request, jsonify

# ─── Config (env vars for cloud, fallback to config.json for local) ───────────

def get_config():
    token = os.environ.get("BOT_TOKEN", "")
    if token:
        return {
            "bot_token": token,
            "channel_id": os.environ.get("CHANNEL_ID", ""),
            "post_interval_minutes": int(os.environ.get("POST_INTERVAL_MINUTES", "30")),
            "secret_token": os.environ.get("SECRET_TOKEN", ""),
            "port": int(os.environ.get("PORT", "5055")),
        }

    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
        cfg["port"] = int(os.environ.get("PORT", cfg.get("port", 5055)))
        return cfg

    print("⚠️  Set BOT_TOKEN env var or create config.json")
    raise SystemExit(1)


# ─── State ────────────────────────────────────────────────────────────────────

STATE_PATH = Path(__file__).parent / "state.json"


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "total_miles": 0.0,
        "session_miles": 0.0,
        "last_lat": None,
        "last_lon": None,
        "last_city": "Unknown",
        "last_state": "Unknown",
        "last_update": None,
    }


def save_state(st):
    STATE_PATH.write_text(json.dumps(st, indent=2))


# ─── Haversine ────────────────────────────────────────────────────────────────

def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 3956 * asin(sqrt(a))


# ─── Reverse geocoding ───────────────────────────────────────────────────────

def reverse_geocode(lat, lon):
    url = (
        f"https://nominatim.openstreetmap.org/reverse"
        f"?lat={lat}&lon={lon}&format=json&zoom=10"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "discord-location-bot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            addr = data.get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("hamlet")
                or addr.get("county", "Unknown")
            )
            region = addr.get("state", addr.get("region", "Unknown"))
            return city, region
    except Exception as e:
        print(f"  ⚠️  Geocode error: {e}")
        return "Unknown", "Unknown"


# ─── Globals ──────────────────────────────────────────────────────────────────

config = get_config()
state = load_state()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
last_channel_post = 0

webapp = Flask(__name__)


# ─── Process incoming location ────────────────────────────────────────────────

def process_location(lat, lon):
    lat, lon = float(lat), float(lon)
    print(f"\n📡 GPS: {lat:.4f}, {lon:.4f}")

    city, region = reverse_geocode(lat, lon)
    print(f"  📍 {city}, {region}")

    if state["last_lat"] is not None and state["last_lon"] is not None:
        dist = haversine_miles(state["last_lat"], state["last_lon"], lat, lon)
        if dist > 0.01:
            state["total_miles"] += dist
            state["session_miles"] += dist
            print(f"  🚗 +{dist:.2f} mi (total: {state['total_miles']:.1f})")

    state["last_lat"] = lat
    state["last_lon"] = lon
    state["last_city"] = city
    state["last_state"] = region
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    if client.is_ready():
        asyncio.run_coroutine_threadsafe(update_bot_status(), client.loop)

    return city, region


async def update_bot_status():
    global last_channel_post

    city = state.get("last_city", "Unknown")
    region = state.get("last_state", "Unknown")
    total = state.get("total_miles", 0)

    status_text = f"📍 {city}, {region} • 🚗 {total:.1f} mi"
    activity = discord.Activity(
        type=discord.ActivityType.watching,
        name=status_text,
    )
    await client.change_presence(activity=activity)
    print(f"  ✅ Status: {status_text}")

    channel_id = config.get("channel_id", "")
    post_interval = config.get("post_interval_minutes", 30) * 60
    if channel_id and (time.time() - last_channel_post) > post_interval:
        try:
            channel = client.get_channel(int(channel_id))
            if channel:
                embed = discord.Embed(
                    title="📍 Location Update",
                    color=0x3498db,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="Location", value=f"{city}, {region}", inline=True)
                embed.add_field(name="Total Miles", value=f"{state['total_miles']:.1f}", inline=True)
                embed.add_field(name="Session Miles", value=f"{state['session_miles']:.1f}", inline=True)
                await channel.send(embed=embed)
                last_channel_post = time.time()
                print(f"  📢 Posted to channel")
        except Exception as e:
            print(f"  ⚠️  Channel post error: {e}")


# ─── Flask routes ─────────────────────────────────────────────────────────────

@webapp.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "running",
        "location": f"{state.get('last_city')}, {state.get('last_state')}",
        "total_miles": state.get("total_miles", 0),
        "last_update": state.get("last_update"),
    })


@webapp.route("/location", methods=["POST"])
def receive_location():
    token = config.get("secret_token", "")
    if token:
        data = request.json or {}
        auth = request.headers.get("Authorization", "")
        body_token = data.get("token", "")
        if token not in (auth, f"Bearer {token}", body_token):
            return jsonify({"error": "unauthorized"}), 401

    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return jsonify({"error": "missing lat/lon"}), 400

    city, region = process_location(lat, lon)

    return jsonify({
        "status": "ok",
        "city": city,
        "state": region,
        "total_miles": state["total_miles"],
    })


@webapp.route("/reset-session", methods=["POST"])
def reset_session():
    state["session_miles"] = 0.0
    save_state(state)
    return jsonify({"status": "session reset"})


@webapp.route("/reset-total", methods=["POST"])
def reset_total():
    state["total_miles"] = 0.0
    state["session_miles"] = 0.0
    save_state(state)
    return jsonify({"status": "all reset"})


# ─── Discord events ──────────────────────────────────────────────────────────

@client.event
async def on_ready():
    print(f"✅ Bot connected as {client.user}")
    print(f"   Invite: https://discord.com/oauth2/authorize?client_id={client.user.id}&scope=bot&permissions=2048")

    if state.get("last_city") and state["last_city"] != "Unknown":
        await update_bot_status()


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    cmd = message.content.strip()

    if cmd == "!location":
        embed = discord.Embed(title="🚛 Location Tracker", color=0x3498db)
        embed.add_field(name="📍 Location", value=f"{state.get('last_city', '?')}, {state.get('last_state', '?')}", inline=False)
        embed.add_field(name="🚗 Total Miles", value=f"{state.get('total_miles', 0):.1f}", inline=True)
        embed.add_field(name="📊 Session Miles", value=f"{state.get('session_miles', 0):.1f}", inline=True)
        updated = state.get("last_update", "never")
        if updated and updated != "never":
            updated = updated[:19].replace("T", " ") + " UTC"
        embed.add_field(name="🕐 Last Update", value=updated, inline=False)
        await message.channel.send(embed=embed)

    elif cmd == "!resetmiles":
        state["session_miles"] = 0.0
        save_state(state)
        await message.channel.send("✅ Session miles reset.")

    elif cmd == "!resettotal":
        state["total_miles"] = 0.0
        state["session_miles"] = 0.0
        save_state(state)
        await message.channel.send("✅ All miles reset.")

    elif cmd == "!help":
        await message.channel.send(
            "**🚛 Location Bot Commands**\n"
            "`!location` — Current location & miles\n"
            "`!resetmiles` — Reset session miles\n"
            "`!resettotal` — Reset all miles\n"
        )


# ─── Start both services ─────────────────────────────────────────────────────

def run_flask():
    port = config.get("port", 5055)
    print(f"🌐 HTTP server on port {port}")
    webapp.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    print("=" * 50)
    print("  🚛 Discord Location Bot (Cloud)")
    print("=" * 50)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    client.run(config["bot_token"])
