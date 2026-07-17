# Core Directive — Evidence-First Identification

Adopted 2026-07-17. Supersedes the informal "confidence %" system used through V0.9.2.

## Mission

The purpose of this project is **not** to maximize the number of identified
cards. The purpose is to **minimize the probability of an incorrect
identification**. A difficult card that gets correctly flagged as uncertain
is more valuable than an easy card, because it exposes and then closes a
real weakness in the system. Accuracy > speed. Evidence > confidence.
Verification > assumption.

## Rule 1 — No silent inference

Every inferred value must say so, in the output, not just in a code comment.
`024a/119` presented bare is a failure even if it's correct. The system must
show its work:

> OCR could not read the suffix. Catalog search returned exactly one
> candidate carrying this base number. Classified as **Inference (Level C)**.
> Confidence reduced until visual confirmation.

## Rule 2 — Every conclusion carries its evidence chain

No skipped reasoning. The full chain, per card:

```
Artwork → HP → Attack names → Ability → Expansion symbol →
Card number → Language → Holo pattern → Catalog match → Final ID
```

A step that wasn't checked is reported as **not checked**, not silently
omitted.

## Rule 3 — Banned language

Never: *"This is probably..."*
Required: *"I know because..."* or *"I cannot prove because..."*

## Rule 4 — Every uncertainty becomes a research problem

A failure is not "couldn't identify." A failure is a structured record:

```
Problem → Cause → How it was solved (or: not yet solved) →
How to detect automatically next time → Prompt improvement →
Algorithm improvement → OCR improvement → Dataset improvement
```

Nothing fails twice. Every closed failure becomes a permanent test AND a
LESSONS.md entry — this part of the existing compound-interest system stays.

## Evidence Levels — replaces the old 0-100% confidence number

| Level | Name | Definition |
|---|---|---|
| **A** | Verified | Every identifying feature directly visible and read: artwork, number, set, language, printing. Zero inference. Gold standard. |
| **B** | Human Eye Verified | Automated OCR failed; manual (assistant) visual inspection succeeded and is exact — not a guess, a read. |
| **C** | Catalog Forced | OCR incomplete, but exactly one catalog candidate exists for the fragment that WAS read. Requires an explicit explanation of the forcing logic. |
| **D** | Partial | Identity (name) known. Printing (exact number) not established. Must never be presented as final in a listing. |
| **E** | Unknown | Insufficient evidence. Requires additional images/angles — the Required Failure Report format below applies. |

## Required Failure Report (replaces "couldn't identify")

For every Level D or E card:
1. Exactly which feature is missing (name? number? set code? language?).
2. Would another image/angle solve it?
3. Would a different OCR pass (different crop, different zoom) solve it?
4. Would removing glare/reflection help?
5. Would a different language database help?
6. Would a scan instead of a photo help?
7. Which single piece of evidence is the blocker?

## Confidence calibration

A confidence number, when still used at all, must list what it's built from
— not asserted. "99%" needs: artwork matched, HP matched, attack matched,
number matched, set matched, language matched, catalog matched, no
conflicting printings exist. Confidence is earned per-feature, not declared.

## Scientific-thinking check

Before finalizing any ID, the system asks: **"What evidence would prove me
wrong?"** — not "what evidence supports this?" This is the single check
most responsible for preventing hallucinated IDs going forward.
