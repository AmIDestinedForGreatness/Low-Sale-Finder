Deploying to Oracle Cloud (Always Free ARM instance)
=====================================================

What this covers: moving all 4 always-on processes (Carousell feed, Facebook
feed, Discord bot, dashboard) from local Windows console windows to a
systemd-managed Ubuntu VM. Written while the Oracle instance itself was still
blocked on "out of host capacity" - files are ready, nothing here has been
run against a real server yet.

Order of operations
--------------------
1. Get the Oracle instance running (blocked on capacity as of this writing -
   retry Create Instance later; region is Singapore, shape VM.Standard.A1.Flex
   4 OCPU/24GB, image Ubuntu 24.04 Minimal aarch64).
2. Attach a public IP to the instance (deferred at creation time - do this
   from the instance's own page: Attached VNICs -> the VNIC -> assign a
   public IP).
3. Add an Ingress Rule for TCP port 5000 on the VCN's Security List (for the
   dashboard) and for TCP port 22 (SSH - usually open by default).
4. SSH in: `ssh -i <private key path> ubuntu@<public ip>`
5. Copy the repo over (scp or git clone - the repo isn't public, so scp from
   this machine is simplest: `scp -r -i <key> C:\Users\Marvin\low-sale-finder
   ubuntu@<ip>:/home/ubuntu/`). Exclude `venv/`, `__pycache__/`, and anything
   already gitignored - those get rebuilt on the VM.
6. Run `bash deploy/setup.sh` on the VM (installs Python, Playwright +
   Chromium, the systemd unit files, opens the VM's own firewall for :5000).
7. Move secrets over (see below) - setup.sh does NOT do this, it's manual on
   purpose, secrets never belong in a script or in git.
8. `sudo systemctl enable --now pokestop-feed pokestop-fb pokestop-bot pokestop-dash`
9. Watch `logs/*.log` and the Discord channels to confirm real activity, same
   verification standard as any other change to this project - don't declare
   it working until a real webhook fires.
10. Only once (9) is confirmed stable: stop `run_sniper.bat`'s Startup entry
    on this PC so it stops double-running the same feeds from two places.

Secrets that must move, and how
--------------------------------
None of these should ever be typed into a script, committed, or written into
the brain/claude-context repo. Copy them by hand over SSH (scp) or paste
directly into files on the VM via SSH.

- **`config.py`** (this repo's root, gitignored) - has DISCORD_WEBHOOK_URL,
  PRICE_SOURCE, POKEMONPRICETRACKER_API_KEY, PRICECHARTING_TOKEN,
  FB_AUCTION_WEBHOOK, CAROUSELL_COUNTRY, and more. Copy the whole file as-is
  from this machine to `/home/ubuntu/low-sale-finder/config.py`.

- **`~/.claude/local-secrets/low-sale-finder.env.local`** - has
    FB_BURNER_NAME, FB_BURNER_EMAIL, DISCORD_BOT_TOKEN, GOOGLE_VISION_API_KEY. `config.py`'s
  `_load_bot_token()` reads this exact path via `os.path.expanduser`, which
  resolves correctly on Linux too (`/home/ubuntu/.claude/local-secrets/...`)
  - so recreate the identical file at that path on the VM, same filename,
  same format. Do NOT put this file in the git repo.

- **`fb_profile/`** (this repo's root) - the actual logged-in Facebook
  browser session (cookies, local storage) for the burner account. This is
  the trickiest piece - see the risk note below before copying it.

⚠️ Real risk, not yet resolved: moving the Facebook session to a new IP
------------------------------------------------------------------------
`fb_feed.py`'s own code comment already accepts the burner account WILL
eventually get banned. But there's a *specific* risk in this migration that's
separate from that slow decay: Facebook's security systems flag a login
session that suddenly appears from a brand-new IP address, especially a
datacenter IP (Oracle Singapore) when the session was built on a residential
Philippines IP. That mismatch alone can trigger an immediate checkpoint /
forced re-verification, independent of anything the scraper does once
running - it happens the moment `fb_feed.py` starts on the new machine.

This was already flagged as a tradeoff before Yujin decided "move all 4" -
he chose simplicity over minimizing this risk, so it's a known and accepted
cost, not an oversight. Worth watching for on first run: if `fb_feed.py`'s
log shows a login/checkpoint error instead of normal scraping, that's this
risk materializing, and the fix is re-running `fb_login.py` fresh *on the
VM itself* (so the session is native to that IP from the start) rather than
copying the old Windows-built session over.

What's NOT done yet (as of this file being written)
-----------------------------------------------------
- The Oracle instance itself (blocked on capacity/rate-limit).
- Actually running any of this against a real server - everything above is
  prepared, none of it is verified end-to-end yet.
- Deciding whether to keep local run_sniper.bat as a cold-standby fallback
  or fully remove it once Oracle is confirmed stable - Yujin's call, not
  decided here.
