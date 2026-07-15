"""
bot.py — Discord bot for Yujin's Pokestop.

Features:
  - React to any auction message (any emoji) -> that auction is TRACKED and
    gets the ~10-min-before-end reminder (fired by fb_feed, gated tracked=1).
    Un-react to stop.
  - Slash commands (no privileged intent): /dashboard /help /status
  - Owner-only "." prefix commands (needs Message Content Intent): .help
    .dashboard .status

Token comes from local-secrets via config (never in the repo).
Runs gracefully whether or not Message Content Intent is enabled: if it's off,
the "." prefix is disabled but everything else still works.
Run:  python bot.py     (or via loop.bat bot)
"""
import socket
import sqlite3
import time

import discord
from discord import app_commands

import config

OWNER_ID = 581075477406679061   # only Yujin can use the prefix commands
PREFIX = "."

HELP_TEXT = (
    "**🎯 Yujin's Pokestop — commands**\n"
    "`.help` / `/help` — this list\n"
    "`.dashboard` / `/dashboard` — dashboard links (PC + phone)\n"
    "`.status` / `/status` — feed online/offline + next scan\n\n"
    "**React** to any auction message with any emoji to **track** it — "
    "I'll remind you ~10 min before it ends. Un-react to stop."
)


def _lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _dashboard_text():
    return ("🎯 **Yujin's Pokestop — dashboard**\n"
            "💻 On this PC: http://127.0.0.1:5000\n"
            f"📱 Phone (same WiFi): http://{_lan_ip()}:5000")


def _feed_status_line():
    import json, os
    p = os.path.join(os.path.dirname(__file__), "feed_status.json")
    try:
        s = json.load(open(p, encoding="utf-8"))
    except Exception:
        return "feed status unknown"
    nxt = s.get("next_scan_at") or 0
    online = (s.get("state") == "scanning") or (nxt and time.time() < nxt + 180)
    when = f" · next scan <t:{int(nxt)}:R>" if nxt else ""
    return ("🟢 Carousell feed ONLINE" if online else "🔴 Carousell feed OFFLINE") + when


# ── auction tracking DB helpers ───────────────────────────────────────
def _conn():
    return sqlite3.connect(config.SEEN_DB_PATH)

def _auction_for_msg(msg_id):
    conn = _conn()
    try:
        return conn.execute("SELECT url, title, end_ts FROM fb_auctions WHERE msg_id=?",
                            (str(msg_id),)).fetchone()
    finally:
        conn.close()

def _set_tracked(msg_id, value):
    conn = _conn()
    try:
        conn.execute("UPDATE fb_auctions SET tracked=? WHERE msg_id=?", (value, str(msg_id)))
        conn.commit()
    finally:
        conn.close()


def build(with_message_content: bool):
    """Create a client+tree with all handlers registered."""
    intents = discord.Intents.default()
    if with_message_content:
        intents.message_content = True
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready():
        print(f"[bot] logged in as {client.user} "
              f"(prefix commands {'ON' if with_message_content else 'OFF'})")
        for g in client.guilds:
            try:
                tree.copy_global_to(guild=g)
                await tree.sync(guild=g)
            except Exception as e:
                print(f"[bot] command sync failed for {g.name}: {e}")

    @tree.command(name="dashboard", description="Get the dashboard link")
    async def dashboard(interaction: discord.Interaction):
        await interaction.response.send_message(_dashboard_text(), ephemeral=True)

    @tree.command(name="help", description="Yujin's Pokestop — command list")
    async def help_cmd(interaction: discord.Interaction):
        await interaction.response.send_message(HELP_TEXT, ephemeral=True)

    @tree.command(name="status", description="Feed online/offline + next scan")
    async def status_cmd(interaction: discord.Interaction):
        await interaction.response.send_message(_feed_status_line(), ephemeral=True)

    if with_message_content:
        @client.event
        async def on_message(msg):
            if msg.author.id != OWNER_ID or not msg.content.startswith(PREFIX):
                return
            cmd = msg.content[len(PREFIX):].strip().lower()
            if cmd in ("help", "h", "commands"):
                await msg.channel.send(HELP_TEXT)
            elif cmd in ("dashboard", "dash"):
                await msg.channel.send(_dashboard_text())
            elif cmd in ("status", "stat"):
                await msg.channel.send(_feed_status_line())

    @client.event
    async def on_raw_reaction_add(payload):
        if payload.user_id == client.user.id:
            return
        row = _auction_for_msg(payload.message_id)
        if not row:
            return
        url, title, end_ts = row
        _set_tracked(payload.message_id, 1)
        ends = f"<t:{int(end_ts)}:F> (<t:{int(end_ts)}:R>)" if end_ts else "unknown"
        try:
            channel = client.get_channel(payload.channel_id) \
                or await client.fetch_channel(payload.channel_id)
            await channel.send(
                f"🔔 <@{payload.user_id}> now **tracking** this auction — "
                f"I'll remind you ~{getattr(config,'FB_AUCTION_WARN_MINUTES',10)} "
                f"min before it ends.\n**{title}**\n⏰ Ends {ends}\n{url}")
            print(f"[bot] tracking: {title[:50]}")
        except Exception as e:
            print(f"[bot] reply error: {e}")

    @client.event
    async def on_raw_reaction_remove(payload):
        row = _auction_for_msg(payload.message_id)
        if row:
            _set_tracked(payload.message_id, 0)
            print(f"[bot] untracked: {row[1][:50]}")

    return client, tree


def main():
    token = getattr(config, "DISCORD_BOT_TOKEN", "")
    if not token:
        print("[bot] no DISCORD_BOT_TOKEN in local-secrets — cannot start")
        return
    # try with prefix commands (needs Message Content Intent); if that intent
    # isn't enabled in the portal, fall back to slash+reactions only so the
    # bot still runs.
    try:
        client, _ = build(with_message_content=True)
        client.run(token)
    except discord.errors.PrivilegedIntentsRequired:
        print("[bot] Message Content Intent is OFF -> running slash + reactions "
              "only. Enable it (Bot tab -> Privileged Gateway Intents) to use "
              "the '.' prefix commands.")
        client, _ = build(with_message_content=False)
        client.run(token)


if __name__ == "__main__":
    main()
