Google Cloud Vision API — signup checklist for NEXT-STEPS-2.md
=================================================================

One prerequisite stands between `NEXT-STEPS-2.md`'s spec and it actually working
end-to-end: a Vision API key. This should take about 10 minutes, not an Oracle-length
ordeal — the account itself is free, and this project's real usage should sit almost
entirely inside the free tier (see the pricing comparison in `NEXT-STEPS-2.md`).

Steps
-----
1. Go to https://console.cloud.google.com/ and sign in with any Google account (a
   personal Gmail is fine, doesn't need to be a business account).
2. If this is your first time in Cloud Console: create a new Project (top-left project
   selector -> "New Project"). Name it anything, e.g. `pokestop-vision`.
3. In the search bar at the top, search "Cloud Vision API" and open it. Click **Enable**.
4. Google will ask you to link a billing account before the API can be enabled, even
   though you're staying inside the free tier. This is the same non-charging shape as
   Oracle's card-for-verification step tonight - nothing bills unless you exceed 1,000
   Web Detection calls in a calendar month, which this project's normal volume won't
   come close to.
5. **Before doing anything else, set a budget alert:** Billing -> Budgets & alerts ->
   Create Budget. Set it to something small, e.g. $1. This isn't required for the free
   tier to work, it's a tripwire so you get an email if anything unexpected ever
   happens, same spirit as double-checking Oracle's cost estimator earlier tonight.
6. Create a restricted API key: APIs & Services -> Credentials -> Create Credentials ->
   API key. Once created, click into it and under "API restrictions" choose **"Restrict
   key"** and select only **Cloud Vision API**. This means even if the key ever leaked,
   it couldn't be used for anything else on your Google account.
7. Copy the key value.

Where it goes (never in code, never in git, never in the brain)
------------------------------------------------------------------
Open (or create) `C:\Users\Marvin\.claude\local-secrets\low-sale-finder.env.local` and
add a new line:

```
GOOGLE_VISION_API_KEY=<paste the key here>
```

This is the exact same file that already holds `DISCORD_BOT_TOKEN` and the Facebook
burner credentials - same vault, same rule, nothing new to set up structurally.

After that
----------
Post in `AGENT-RELAY.md` (or just tell Claude Code directly) that the key is in place.
Codex's `NEXT-STEPS-2.md` build should already be waiting on exactly this - once it's
confirmed, the one blocked acceptance criterion (the live Meloetta re-run proving real
Coverage improvement) can actually run.
