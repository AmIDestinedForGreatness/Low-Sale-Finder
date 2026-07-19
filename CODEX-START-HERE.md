# Start-here prompt — paste this as your first message

Read `CODEX-IDENTIFICATION-NEXT-PROMPT.md` in this repo's root in full, then
follow it exactly. Do not summarize it back to me — begin executing it.

Before you start: also read `AGENT-RELAY.md` (newest entries first, bottom
of the file) so you have the full context of what the previous session
(security/reliability hardening, 6 units) and the one before that
(identification-audit + HASH-FIRST) already did. Do not repeat that work.

One correction to make going in: `CODEX-IDENTIFICATION-NEXT-PROMPT.md`
Section 0 states this was written for "Mom's PC" with no `fingerprints.sqlite`
and no real photos in `uploads/`. Check whether that's still true on
whatever machine you're actually running on right now — if this is Personal
PC, those assets likely exist, which changes the balance between Priority 1
(footer OCR) and Priority 2 (HASH-FIRST real-photo acceptance). Follow the
prompt's own instruction to verify this yourself rather than assume.

Begin by verifying the prompt's claimed failure counts against the actual
`FAILURES.md`, then proceed per the prompt.
