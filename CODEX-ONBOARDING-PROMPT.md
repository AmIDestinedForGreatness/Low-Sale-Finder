# Codex onboarding prompt — paste this as your first message

I want you to work on this repo (Yujin's Pokestop — a Pokémon TCG deal-finding and
card-identification system). Before doing anything else:

1. Read `README.md` (system map — what to read in what order), `DIRECTIVE.md`
   (governing rules: evidence levels A-E, no silent inference, banned language),
   `VISION.md` (product north star — read ALL of it, including the "Personal
   Inventory Intelligence" and "Kino" sections added 2026-07-19), `PROGRESS.md`
   (version history, current limits), and `AGENT-RELAY.md` bottom-up (chronological
   work log between me/Claude Code — read the newest entries first, they're at the
   bottom).
2. Check `git log --oneline -15` and `git status` — confirm you understand what's
   already built vs. in progress before proposing anything.

## Working agreement (already in `README.md`, restating because it's non-negotiable)

- Every unit: implement -> verify against REAL data (not just unit tests) -> honest
  numbers in `AGENT-RELAY.md` (numbers, not adjectives) -> local commit.
- **Never push to GitHub without my explicit instruction, every single time.**
- Every closed mistake becomes a permanent test in `tests.py` + a lesson in
  `LESSONS.md`. Nothing fails twice.
- Full suite must stay green: `python tests.py`.
- Follow `DIRECTIVE.md`: a wrong confident answer is worse than an honest "I don't
  know." Never loosen a match/confidence gate just to produce more results.

## Current state, so you don't duplicate work

- **Identification engine (Phase 1, "Pokémon Intelligence") is in progress, NOT
  done, not even close** — my own words. Don't treat it as solved.
- The most recent unit (`HASH-FIRST-NEXT.md`, implemented tonight on Mom's PC,
  commit `a5ca3a9`, local only) is **geometry-verified but NOT real-photo verified**
  — it needs `fingerprints.sqlite` and `uploads/`, which only exist on my Personal
  PC. If you're running on Personal PC: that's the first thing to actually finish —
  steps are at the bottom of `AGENT-RELAY.md`'s most recent Mom's-PC entry.

## What I actually want, long-term (full version is in `VISION.md` now — read it,
don't just take this summary)

Two separate tracks, don't conflate them:

**Track A — finding deals other people are selling** (Phases 2-5 in `VISION.md`):
monitor Facebook/FB Marketplace/FB groups/Lazada/Shopee/Carousell/eBay PH, identify
every listing, price it, flag steals, eventually help me start a conversation with
simple canned openers ("How much", "Location", "Still available") — NOT autonomous
negotiation, and NEVER auto-send a message without my explicit approval per message.

**Track B — pricing MY OWN collection** ("Personal Inventory Intelligence" in
`VISION.md`, new tonight): I want an auto-pricer that tells me, for a card I already
own: what it's worth now, what I paid, my profit. I am **explicitly NOT asking for
automated selling/posting** — only automated pricing/valuation. Once I decide the
system is accurate enough, I'll use it to rebuild my outdated Pokémon spreadsheet
(with the system's help, not fully unattended), eventually with a condition
identifier feeding the pricing, eventually as continuous auto-tracking instead of a
one-time rebuild.

**After Pokémon TCG is actually proven** (not soon) — same architecture extends to
other TCGs/collectibles, eventually converging into one integrated assistant
("Kino") I can use from my phone anywhere. This is context for why the current
identification rigor matters — it is NOT something to start building now.

## What I want from you right now

Don't start building Track B or the marketplace expansion yet. First: read
everything above, then give me your own honest assessment — same kind of review
you're doing for the ChatGPT/ Sol 5.6 pass — of where the codebase actually stands
against this full vision, and propose the single next concrete unit, scoped and
verifiable the way every past unit in `AGENT-RELAY.md` was. I'd rather you tell me
what's missing or risky than start writing code for the whole roadmap at once.
