# VISION.md — Product North Star (Yujin's own spec, 2026-07-18)

This is Yujin's own product vision, written verbatim by him, plus CC's translation of
what it means for sequencing given where the system actually is today. Keep this file
as the standing reference for "why does this project exist and where is it going" —
`DIRECTIVE.md` covers identification philosophy, `NEXT-STEPS*.md` covers specific
build units, this covers the whole arc.

## North Star

> The system finds an underpriced Pokémon listing almost immediately, identifies
> everything correctly, explains why it is a steal, warns us about possible risks,
> recommends the correct offer, and helps us contact the seller before competing
> buyers. The goal is not merely to collect listings. The goal is to build an
> increasingly intelligent deal-hunting system that recognizes value faster and more
> accurately than the market.

## What it should eventually monitor

Facebook, Facebook Marketplace, Facebook groups, Lazada, Shopee, Carousell, and eBay
Philippines — detecting newly posted listings ideally within one minute, then
determining: what's being sold, authenticity, set/number/rarity/language/condition/
grading, fair market value, PH-market value, max buy price, whether it's a genuine
steal, and how urgent/trustworthy the opportunity looks.

## Yujin's own priority ordering, in his words

> The reason we have an identification system and I'm very intensely firm on
> perfecting it [is] so that the system knows one day automatically what they see,
> what its worth, WHAT it should be worth as a steal price, then automatically have a
> system (soon hopefully) to automatically reply [to] simple inquiries... To snipe at
> cheap pokemon auctions via facebook groups.

**Translation: identification accuracy is the foundation everything else is built on,
not one phase among many.** A fast scraper feeding a shaky identifier just produces
confident wrong answers faster — the current work (Evidence Levels, collision
detection, the Google Vision artwork corroboration in `NEXT-STEPS-2.md`) IS the
correct thing to keep investing in before scaling scraper breadth.

## Development Phases (Yujin's structure)

1. **Pokémon Intelligence** — card/sealed-product ID, price database, condition &
   authenticity, PH-market valuation, steal scoring, manual review/corrections.
   **This is the current phase, in progress. Not done. Not even near done (Yujin's
   own words, 2026-07-19) — do not treat identification as solved.**
2. **Real-Time Deal Discovery** — near-real-time monitoring, duplicate-listing
   detection, saved searches, instant high-priority alerts, auction-ending alerts.
   **Partially live today** (Carousell + FB groups feeds, react-to-track auctions).
   Lazada, Shopee, eBay PH are **not started** — each is a real, separate scraper
   build, not a config toggle.
3. **Seller Assistance** — suggested questions/replies, negotiation templates, max-offer
   rules, seller/listing risk checks, **human approval before any message sends**.
   Not started. Yujin's own spec already requires the human-approval gate — keep it.
   **Concrete mechanic, clarified 2026-07-19:** short canned quick-reply starters (the
   Facebook-Page-style opener pattern) — "How much", "Location", "Still available" —
   not a full negotiation AI to start. Think templated first-touch, not autonomous
   conversation.
4. **Assisted Sniping** — compliant initial inquiries, auction monitoring/bidding
   assistance, automatic escalation of exceptional deals, purchase/profit tracking.
   Not started. Highest-risk phase (real money, real messages sent under Yujin's
   name/accounts) — needs the most caution and the most explicit sign-off per action.
5. **Expansion** — One Piece TCG, Hot Wheels, other TCGs/collectibles, once the
   Pokémon engine is proven accurate and profitable. Not started, correctly gated on
   Phase 1-4 actually working first. **Restated 2026-07-19: "not there yet, not even
   near" — do not begin scoping this until Yujin explicitly says Pokémon is done.**

## Personal Inventory Intelligence — a DISTINCT track from marketplace hunting (added 2026-07-19)

Everything above is about finding/evaluating listings **other people** are selling.
This track is about Yujin's **own collection** — same identification/valuation engine,
pointed inward. Sequenced separately because it doesn't need new scrapers or new
marketplaces, only the identification+pricing core that's already Phase 1's focus —
this can mature in parallel with Phase 1, not strictly after it.

**Yujin's own words on the goal (2026-07-19):** "how much its worth to sell/buy...
eventually have an auto pricer... how much I am profiting?" — **explicitly NOT asking
for full automation of the actual selling/posting.** The automation target is the
PRICE/PROFIT CALCULATION, not the act of listing or selling. Keep this boundary
sharp — a future session must not read "auto pricer" as "auto-lister."

**The concrete sequence, in his words, condensed:**
1. **Auto-pricer / profit calculator** — given an identified card + condition:
   current PH market value, what he actually paid (from memory or old records),
   resulting profit if sold now. This is the identification+valuator stack already
   being built, applied to cards he OWNS rather than cards he's evaluating to buy.
2. **The spreadsheet rebuild — gated on HIS OWN sign-off, not a target date.** His
   current Pokémon inventory spreadsheet is outdated (mentioned repeatedly across
   sessions — bulk/lot purchases were never broken into per-card records, a known
   operational gap, see `identity.md`/`last-session.md` in the brain). **He will
   decide when the system is "ready and fit to use"** — at that point, rebuild the
   spreadsheet WITH the system's help: purchase price (from memory/old data where
   available), current sell estimate (given condition), assisted not silently
   auto-run.
3. **Condition identifier — not built, a real future capability, not a detail.**
   Resale value depends heavily on condition; there's no dedicated path today (see
   `PROGRESS.md` "Known limits" — graded slabs have no path, condition checker was
   already on the roadmap as "whitening-first, L17"). This needs to exist before
   step 2's per-card pricing can be trusted at scale.
4. **Full automated ongoing inventory tracking** — once 1-3 are proven, the
   spreadsheet-rebuild-once becomes continuous: the system tracks his inventory and
   its pricing on an ongoing basis, not a one-time export.

**Then, and only then** — Phase 2's marketplace-scraper breadth (steal-hunting on
Lazada/Shopee/eBay PH) and Phase 3's outreach templates connect to this: the same
"is this a steal" and "what's my profit" logic serves both directions (buying
underpriced listings, and knowing what his own cards are actually worth to sell).

## Honest constraints worth naming now, not discovering later

- **Ban/detection risk multiplies with every new marketplace**, not just adds up
  linearly — each platform has its own anti-bot posture, and running automated
  presence on six of them simultaneously (all tied back to identifiable accounts/
  devices/IPs) is a materially bigger risk surface than today's Carousell+FB pair.
  Already living this tradeoff with the FB burner account tonight (see
  `AGENT-RELAY.md`'s ban-risk discussion) — it compounds per platform added.
- **Sub-1-minute detection across 6 platforms** is a real infrastructure demand, not
  just "poll faster" — some of these platforms (Lazada, Shopee, eBay) have official
  APIs that may fit better than scraping; each needs its own investigation before
  assuming the Carousell/FB approach ports over directly.
- **Auto-reply and auto-negotiate (Phase 3/4) are real risk surfaces**, not just
  features — sending messages or making purchase decisions under Yujin's identity
  needs hard approval gates, which his own spec already correctly requires. Don't
  relax that requirement for convenience later.
- **Free/cheapest-viable is the explicit standing rule, not a nice-to-have** (Yujin's
  own words: "we want everything to be free. or cheap as possible"). Same discipline
  as Oracle and Google Vision tonight applies to every future integration: free tier
  first, real pricing checked before committing, budget alerts as tripwires. Official
  APIs aren't always an option even when free would be preferred — **TCGplayer no
  longer grants API access** (Yujin confirmed this directly), which is why this
  project already leans on scraping/PriceCharting/pokemontcg.io instead of a clean
  TCGplayer API integration. Assume the same "check if the official API still exists
  and what it costs" step is needed before building against Lazada/Shopee/eBay PH —
  don't assume any of them still offer what worked when this was last researched.

## What's actually next, in sequence

1. **Finish `NEXT-STEPS-2.md`** (Google Vision web-artwork corroboration) — already
   in progress, currently blocked on the `GOOGLE_VISION_API_KEY` vault-vs-env-var bug
   found in review.
2. **Yujin's stress test tomorrow** (2026-07-19) — real-world evidence on where the
   identification engine actually stands, before committing to any new marketplace
   scraper. Don't build Lazada/Shopee/eBay PH scrapers before this happens — it would
   be scaling breadth before confirming the foundation is solid, exactly backwards
   from Yujin's own stated priority.
3. **Only after that:** pick ONE new marketplace to prototype (probably eBay PH or
   Shopee, likely to have a usable API vs. needing Facebook-style browser automation),
   scoped the same way every unit tonight was — real tests, honest before/after,
   collision-analysis-style guardrails against false confidence.

## Beyond Pokémon: "Kino" (added 2026-07-19 — aspirational, not a build target)

Yujin's own stated end-state, verbatim-close: after Pokémon TCG intelligence is
actually proven (not soon), extend the same identification+valuation+deal-hunting
architecture to other TCGs and collectibles — then converge everything he's building
(this system, his other projects) into **one integrated personal assistant, "Kino,"**
usable from his phone, wherever he is.

**This is named here so it isn't lost, and so no future session mistakes it for a
near-term unit.** It's the "why we're doing this right" behind the current
architectural discipline (Evidence Providers, honest evidence levels, real
verification over confident guessing) — build Pokémon TCG intelligence correctly
BECAUSE it's the template every future system reuses, not because Pokémon cards are
the whole goal. Nothing about "Kino" is actionable today; it's context for why
today's rigor matters, not a phase to start scoping.

## Standing rules for this file

This file should get updated as phases actually complete — not treated as a locked
contract. Yujin's own standing rule applies here too: nothing gets marked "done"
except by him.
