# CONTINUE — IDENTIFICATION ACCURACY SESSION (not security)

You've completed the evaluation and the security/reliability hardening pass
(6 units, all verified, `AGENT-RELAY.md` has the full record). That work was
real and needed, but it did not move the metric that actually matters:
**does the system identify cards more accurately.** This session's sole
objective is that metric. Do not start another security/infra unit unless
you reproduce a NEW identification-blocking defect while doing this work.

## Read first

`AGENT-RELAY.md` (bottom-up, especially your own 6 units and CC's HASH-FIRST
entry), `FAILURES.md` in full, `DIRECTIVE.md`, `HASH-FIRST-NEXT.md`,
`VISION.md`'s Phase 1 ("Pokémon Intelligence... not done, not even near
done").

## The evidence-backed priority order — mined from FAILURES.md, not guessed

I (the owner's Claude Code assistant) ran the numbers on the 45 real failure
records already in this repo. Two findings should set your priority order:

**Priority 1 — footer-region OCR is the single largest failure class: 16/45
records (35%), ALL with the identical cause "OCR did not read the footer; a
human eye reading the same footer succeeded."** Real cards this happened on:
Meloetta XY120, Victini XY117, Manaphy XY113, Yveltal-EX XY150, Magearna
XY186, M Manectric-EX 024a/119, Incineroar-GX 27/149, Weavile 238/236,
Wishiwashi 240/236, Stoutland 248/236, Excadrill 246/236, Mimikyu V 068/172,
Coalossal 117/100 (x2), M Blastoise-EX 22/108, Rota's Mime Jr. 086/PCG-P.

This is not "OCR is generally weak" — it's specifically the collector-number
footer strip (small text, often glare/tilt-affected, promo-letter or
JP-set-code formats). The fact that a human eye reads the SAME crop
correctly means the information is present in the pixels; the current OCR
pass on that region is losing it. Investigate:
- What crop/zoom/contrast variant does the current pipeline try for
  footers vs. what a human actually needs (higher zoom? different contrast
  curve? a footer-specific preprocessing pass distinct from the general
  card-text OCR pass)?
- Are any of these 16 cards' actual source images still available in
  `uploads/` or the dataset folders (check before assuming you need new
  photos — several came from the documented dataset runs)? If yes, use
  them as real regression fixtures, not synthetic approximations.
- Do NOT lower any confidence/match threshold to "fix" this — the fix must
  be that OCR reads MORE correctly, not that the system accepts LESS
  evidence.

**Priority 2 — artwork evidence is the most commonly cited missing
dimension: 10/45 records explicitly name it.** This is corroborating, not
contradicting, the direction HASH-FIRST already took. If `fingerprints.
sqlite` and `uploads/` exist on this machine: finish HASH-FIRST-NEXT's real
acceptance criteria properly (warped-hash hit rate on real photos, honest
match/miss counts, not just the geometry tests CC already closed). If those
assets do NOT exist here: do not fabricate results — instead, check whether
any of the 10 artwork-missing records have their source images already in
the repo's dataset folders and could serve as a smaller-scope real test of
the warp-then-hash pipeline specifically.

**Priority 3 — only after 1 and 2 have real numbers:** re-run
`reaudit.py` (no artificial time cap) and report whether either fix changed
any existing card's evidence level. A regression here (a previously-A card
dropping) is more important to catch than a new card going from D to C.

## Unit-level Definition of Done (same as your security session — keep this)

1. Reproduce the specific failure with a real record from `FAILURES.md` or
   a real available image — not a synthetic approximation, unless no real
   asset exists AND you say so explicitly.
2. A regression test fails for the expected reason before the fix.
3. Smallest robust correction — no threshold loosening, ever.
4. Test passes; surrounding tests pass; full `python tests.py` run with
   exact pass/fail/skip counts recorded.
5. `AGENT-RELAY.md` checkpoint: which of the 16 (or 10) real cards did this
   fix actually resolve — name it, don't just say "footer OCR improved."
6. `LESSONS.md` entry if this closes a mistake class.
7. `FAILURES.md`/`PROGRESS.md` updated to reflect which specific records
   moved from Pending to Resolved.
8. Local commit. No push.

## Hard boundaries (unchanged from your last session)

No push, no deployment, no marketplace actions, no threshold loosening to
force a match, no claiming real-photo verification when only geometry was
tested, no starting Track B/Kino/marketplace expansion. If you hit a wall
requiring assets this machine doesn't have, document the exact blocker and
move to the other priority (1 <-> 2) rather than inventing results.

## Anti-goal, explicit

Do not touch `app.py`'s auth/SSRF/upload code again unless you find a NEW
identification-blocking defect there. That surface is closed for this
session. The owner wants to see the failure COUNT in `FAILURES.md` go down
on real cards, not another round of infrastructure hardening.

## When you stop

Leave a handoff naming: which of the 16 footer-OCR cards and which of the
10 artwork-missing cards actually got resolved (by exact name), the new
`FAILURES.md` count, whether `reaudit.py` found any regression, and the
single best next unit if this priority order is exhausted.
