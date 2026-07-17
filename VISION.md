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
   **This is the current phase, in progress.**
2. **Real-Time Deal Discovery** — near-real-time monitoring, duplicate-listing
   detection, saved searches, instant high-priority alerts, auction-ending alerts.
   **Partially live today** (Carousell + FB groups feeds, react-to-track auctions).
   Lazada, Shopee, eBay PH are **not started** — each is a real, separate scraper
   build, not a config toggle.
3. **Seller Assistance** — suggested questions/replies, negotiation templates, max-offer
   rules, seller/listing risk checks, **human approval before any message sends**.
   Not started. Yujin's own spec already requires the human-approval gate — keep it.
4. **Assisted Sniping** — compliant initial inquiries, auction monitoring/bidding
   assistance, automatic escalation of exceptional deals, purchase/profit tracking.
   Not started. Highest-risk phase (real money, real messages sent under Yujin's
   name/accounts) — needs the most caution and the most explicit sign-off per action.
5. **Expansion** — One Piece TCG, Hot Wheels, other TCGs/collectibles, once the
   Pokémon engine is proven accurate and profitable. Not started, correctly gated on
   Phase 1-4 actually working first.

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

This file should get updated as phases actually complete — not treated as a locked
contract. Yujin's own standing rule applies here too: nothing gets marked "done"
except by him.
