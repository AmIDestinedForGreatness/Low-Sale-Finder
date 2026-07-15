"""
bot.py — Discord bot for react-to-track auctions.

React to any auction message the feed posts (any emoji) and the bot flags
that auction as TRACKED. Tracked auctions get the 10-min-before-end reminder
(fired by fb_feed.check_auction_warnings, gated on tracked=1). Un-react to
stop tracking.

Token comes from local-secrets via config (never in the repo).
Run:  python bot.py     (or via loop.bat bot)
"""
import sqlite3
import time

import discord

import config

# default intents include guild message reactions (what we need); we never
# read message CONTENT, so no privileged intents are required.
intents = discord.Intents.default()
client = discord.Client(intents=intents)


def _conn():
    return sqlite3.connect(config.SEEN_DB_PATH)


def _auction_for_msg(msg_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT url, title, end_ts FROM fb_auctions WHERE msg_id=?",
            (str(msg_id),)).fetchone()
    finally:
        conn.close()


def _set_tracked(msg_id, value):
    conn = _conn()
    try:
        conn.execute("UPDATE fb_auctions SET tracked=? WHERE msg_id=?",
                     (value, str(msg_id)))
        conn.commit()
    finally:
        conn.close()


@client.event
async def on_ready():
    print(f"[bot] logged in as {client.user} — watching auction reactions")


@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return
    row = _auction_for_msg(payload.message_id)
    if not row:
        return  # not an auction message we posted
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
        print(f"[bot] tracking auction: {title[:50]}")
    except Exception as e:
        print(f"[bot] reply error: {e}")


@client.event
async def on_raw_reaction_remove(payload):
    row = _auction_for_msg(payload.message_id)
    if row:
        _set_tracked(payload.message_id, 0)
        print(f"[bot] untracked auction: {row[1][:50]}")


def main():
    token = getattr(config, "DISCORD_BOT_TOKEN", "")
    if not token:
        print("[bot] no DISCORD_BOT_TOKEN in local-secrets — cannot start")
        return
    client.run(token)


if __name__ == "__main__":
    main()
