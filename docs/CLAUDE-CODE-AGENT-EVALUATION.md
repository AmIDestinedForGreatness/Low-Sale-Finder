# Claude Code Agent Evaluation

**Repository:** `AmIDestinedForGreatness/Low-Sale-Finder`

**Evaluation date:** 2026-07-19 (Asia/Shanghai)

**Reviewed local head:** `9f04482` before this evaluation's changes

**Branch state at intake:** `main`, clean, three commits ahead of `origin/main`

**Scope:** repository, governing documents, vision, implementation, tests, saved datasets,
deployment notes, and agent handoff history. No live messages, purchases, offers, account
actions, remote deployment, or GitHub push were performed.

## 1. Executive assessment

The repository has a strong and unusually explicit product principle: a card identifier
must prefer an honest unread over a plausible but unsupported answer. The best prior work
supports that principle. In particular, collision analysis, A-E evidence levels,
separation of evidence coverage from prediction confidence, bounded Facebook pacing,
candidate retention, permanent regression lessons, and human confirmation are useful
foundations. The vision also makes two important product boundaries clear:

1. identification accuracy is the foundation for deal discovery; and
2. inventory intelligence is distinct from marketplace hunting, while seller messaging
   and purchasing remain human-approved future work.

The implementation is not yet reliable enough to call the identification foundation
"solved," and the vision correctly says so. The largest product risk is not a weak OCR
model by itself; it is **inconsistent behavior between duplicate identification paths**.
`profile_dataset.identify()` contains the canonical, heavily tested logic, while
`app.py` independently reconstructs much of it for the single-card route. The same
set-code-as-name defect had been fixed in the canonical path but remained in the live
dashboard route. This evaluation reproduced that mismatch with a failing route test and
then applied the smallest parity fix.

The largest operational risk is the dashboard deployment model. `app.py` binds to every
interface and exposes unauthenticated mutation/control endpoints, including process
restart, webhook replacement, user-confirmation writes, remote URL fetching, and scrape
starts. `deploy/README.md` and `deploy/setup.sh` instruct opening TCP/5000 publicly. This
is a release blocker for any internet-facing deployment.

The previous agent's work should therefore be described with four different evidence
labels:

| Label | Meaning | Current examples |
|---|---|---|
| Implemented | Source exists and can be inspected | collision analysis, evidence providers, contour probing, WebArtwork provider |
| Test-proven locally | Deterministic test exercised the intended branch on this machine | 117-test suite, 40-test offline scraper/parser replay, route set-code rejection, hash-first contour wiring |
| Observed on one real sample | Relay contains a concrete live observation but it was not reproducible here | prior 12-card binder and individual-card reports |
| Proven for the product | Repeatable acceptance corpus, calibrated metrics, failure bounds, and operational controls exist | **no major identification or pricing capability meets this bar yet** |

The relay sometimes collapses these levels. For example, the perspective-warp work was
reported as four passing tests, but at the reviewed head one of those four tests skipped
because the synthetic scene did not produce two contours. The implementation existed;
the claimed proof did not. This evaluation made that wiring test deterministic and
keeps real-photo/catalog acceptance explicitly open.

## 2. Architecture and product-track map

### Track A: listing discovery and evaluation (implemented, incomplete)

```text
Carousell / Facebook sources
        |
        v
scraper.py, profile_dataset.py, fb_feed.py
        |
        +--> classification / dedup / pacing
        |
        v
valuator.py + profile_dataset.identify()
        |
        +--> OCR / number / name / attack fingerprint / catalog candidates
        +--> collision.py adversarial candidate search
        +--> providers/* corroborating evidence
        +--> evidence.py A-E level, coverage, provisional confidence
        |
        v
prices.py / tcg_price.py / pc_price.py / exchange_rate.py
        |
        v
dashboard, logs, and Discord notifications
```

The core value is in the identifier/evidence boundary, not in the dashboard. That
boundary is currently blurred: the dashboard route duplicates identification logic,
the evidence layer can write production failure state during a request, and several
modules own JSON persistence directly.

### Track B: personal inventory and seller workflow (vision only)

Track B does not yet exist as a coherent implementation, which is appropriate. It will
eventually reuse exact card identity and pricing, then add purchase basis, condition,
fees, inventory events, and profit calculations. It must not be smuggled into Track A
as another scraper mode. Its data model and acceptance rules differ:

```text
owned item -> verified identity -> human-reviewed condition -> price interval
           -> purchase basis -> fees/shipping -> realized/unrealized profit
           -> inventory history / export
```

Seller assistance remains draft-only and human-approved. Nothing in this review
authorizes automatic seller messages, offers, bids, purchases, or listing publication.

## 3. Verification ledger

### Environment

- Windows, Python 3.14.4 at
  `C:\Users\MARVIN-LI\AppData\Local\Python\bin\python.exe`.
- The Windows `python` alias is not a usable project interpreter on this machine.
- No isolated project virtual environment or CI workflow is present.
- `fingerprints.sqlite`: absent.
- `dataset/images`: zero files.
- Saved JSON inputs parse successfully:
  `carousell_profile.json` (20 records), `training_search_0717.json` (20 records),
  `for_u_to_do_while_im_asleep.json` (32 top-level keys), and `failures.json`
  (46 top-level keys).
- `requirements.txt` is pinned but omits the Google Vision package used by
  `providers/web_artwork.py`.

### Baseline at `9f04482`

Command, run from an isolated `git archive` snapshot with `config.example.py` copied to
`config.py`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\MARVIN-LI\AppData\Local\Python\bin\python.exe' tests.py
```

Result: **116 total: 111 passed, 1 failed, 4 skipped**. The failure was
`TestValuatorOcrRoute.test_dropped_mechanic_glyph_is_recovered_via_suffix_retry`:
expected `123/124`, received `None`. The test depended on a machine-local catalog and
wrote to the production upload/failure paths. One skipped test was
`TestCardWarp.test_probe_contours_hash_hit_skips_ocr`; therefore the relay's earlier
"all four pass" claim was not true on this machine.

### After the focused correction

Full suite:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\MARVIN-LI\AppData\Local\Python\bin\python.exe' tests.py
```

Result: **117 total: 114 passed, 3 skipped, 0 failed in 0.388 seconds**.

Offline scraper/parser replay:

```powershell
& 'C:\Users\MARVIN-LI\AppData\Local\Python\bin\python.exe' -m unittest -v `
  tests.TestClassify tests.TestMerchFilter tests.TestAuctionVsDistress `
  tests.TestMetaAndDeadend tests.TestParsePrice tests.TestParseEndTime `
  tests.TestParseAuction tests.TestFacebookFeedPace tests.TestTcgMatching `
  tests.TestPriceChartingPrecision
```

Result: **40/40 passed in 0.009 seconds**. This is a deterministic offline replay of
saved examples and adversarial strings, not a live marketplace acceptance test.

Additional checks:

- all 31 Python files parsed with `ast.parse`;
- the one inline dashboard JavaScript block passed `node --check`;
- all four tracked dataset JSON files parsed;
- `git diff --check` returned success (line-ending conversion warnings only);
- `build_fingerprints.py` emitted a Python 3.14 `SyntaxWarning` for an invalid escape in
  its module docstring.

### What was not verified

- no real-photo identification replay could run because this checkout has no images or
  fingerprint database;
- no live Google Vision call ran because no usable configured client/dependency/key was
  available;
- no live Carousell, Facebook, TCGplayer, PriceCharting, Discord, or exchange-rate call
  was used as acceptance evidence;
- no Linux/Oracle deployment, multi-process endurance, account-ban behavior, or public
  network exposure test was performed;
- pricing accuracy, PH-market calibration, authenticity, condition, holo/finish, and
  seller trust were not measured.

## 4. Evidence-based findings

### F-01 — High — Correctness / architecture: duplicated identifier paths drift

**Evidence.** `profile_dataset.py:463` already rejects a set-code-shaped OCR token as a
card name. The single-card route at `app.py:211` explicitly builds its own identification
result and evidence rather than calling `profile_dataset.identify()`. Before this review,
an OCR result of `m20` plus the colliding number `222/193` returned `name: "m20"` from
the route even though the canonical path returned no name. `AGENT-RELAY.md` documents
other route-only drift around mechanic suffixes and language.

**Impact/failure mode.** The UI can confidently display different identities for the
same card depending on entry point. Fixes and evidence rules applied to one path do not
protect the other.

**Reproduction.** POST a temporary image to `/api/valuator/ocr`, mock OCR as
`["m20", "222/193"]`, and return multiple cross-region exact-number candidates. Before
the fix, the response presents `m20` as the name.

**Correction in this review.** Preserve the original query as a search trace, but blank
the displayed name when it is only a set-code-shaped hint and no catalog route upgraded
it. The route also now closes the Pillow image handle. Tests isolate uploads and failure
logging.

**Acceptance.** The new route regression passes and the full suite is green.

**Required follow-up/regression.** Extract one canonical identification service with a
versioned result schema; keep Flask routes as adapters. Add parity tests that feed the
same evidence into every public entry point and compare identity, candidates, evidence
level, and abstention.

### F-02 — High — Test integrity: tests wrote production evidence and skipped proof

**Evidence.** The baseline route test used `app.UPLOAD_DIR`, called the real evidence
builder/logger, and depended on machine-local binder/catalog signals. Running it created
card/crop files and appended a failure record. The warp/hash integration test called the
real contour detector and used `skipTest` when its synthetic drawing did not yield two
regions.

**Impact/failure mode.** A test run can contaminate the learning corpus, pass/fail by
machine, or turn a missing exercised branch into a reported success. That damages both
software confidence and training data provenance.

**Reproduction.** Run the baseline suite without `fingerprints.sqlite`; inspect
`FAILURES.md`, `dataset/failures.json`, and `uploads/`, then run the focused warp class
and observe the skip.

**Correction in this review.** Route tests now use a temporary upload directory, patch
failure logging, and control binder/catalog signals. The warp test supplies deterministic
regions/quads while still exercising warp variants, hash lookup, and the "hash hit skips
OCR" behavior. Known test artifacts from this evaluation were removed.

**Acceptance.** The 117-test suite has 114 passes and three unrelated explicit
skips; focused route tests
are 2/2 and warp tests are 4/4.

**Required follow-up/regression.** Give all persistence components injectable paths and
make the suite fail if tracked datasets or the repository upload directory change. Use a
temporary repository state fixture by default.

**Correction status (2026-07-19).** Route, failure, upload, confirmation, and durability
tests use temporary paths for their mutable records. Module setup/teardown now hashes
`FAILURES.md` and the full top-level `dataset/*.json` file set; changed, created, or
deleted corpus files fail focused and full runs without requiring an initially clean
source tree. A dedicated regression proves changed/created detection, and the 142-test
suite left the corpus unchanged. Private upload contents are deliberately not hashed, so
an explicit upload-directory invariant remains open rather than being implied.

The same module boundary now records and rejects Requests plus raw socket
`connect`/`connect_ex`, failing teardown even if application code catches the injected
exception. It exposed live exchange-rate attempts in three authorization-route calls and
one valuation test; all four now inject deterministic rates. The default 143-test run has
no recorded in-process Python network attempt. Live integration is explicit via
`POKESTOP_TEST_ALLOW_NETWORK=1`; subprocess/external-tool networking is not claimed to be
intercepted by this Python boundary.

### F-03 — Critical — Operations/security: public unauthenticated control plane

**Evidence.** `app.py:1497` binds `0.0.0.0:5000`. `deploy/README.md:18` and
`deploy/setup.sh:34` instruct opening that port. No authentication or authorization layer
is present. Mutation/control routes include `/api/restart` (`app.py:190`),
`/api/valuator/from_url` (`app.py:394`), `/api/valuator/confirm` (`app.py:485`),
`/api/webhook` and `/api/webhook/test`, and `/api/scrape` (`app.py:625`). Uploaded photos
are served back by filename.

**Impact/failure mode.** Anyone who can reach the service can kill processes, change the
Discord webhook, trigger expensive OCR/scraping/outbound requests, and write confirmed
training examples. This creates denial-of-service, secret redirection, data-poisoning,
and privacy risks.

**Reproduction.** Start the dashboard on a reachable host and call the routes without a
session or token; no authorization challenge occurs.

**Correction.** Do not expose port 5000 publicly. Use a private VPN/tunnel or reverse
proxy with TLS and identity-aware authentication. Add server-side role checks, CSRF
protection for browser mutations, rate/cost limits, audit logging, and safe restart
mechanics. Separate the read-only dashboard from control actions.

**Acceptance/regression.** From an unauthenticated client, every mutation route returns
401/403; from the public internet, the raw Flask port is unreachable; authorized actions
are audited and bounded. Add endpoint authorization tests and a deployment smoke test.

### F-04 — High — Input/network safety: weak URL validation and unbounded uploads

**Evidence.** `app.py:402` accepts a URL when the raw string contains `carousell`,
`facebook.com`, `fb.com`, or `fb.watch`; it does not parse and validate the hostname.
The route fetches page and image URLs. `/api/valuator/ocr` checks only the filename
extension, has no Flask `MAX_CONTENT_LENGTH`, saves before validating image content, and
uses second-resolution filenames (`app.py:219`).

**Impact/failure mode.** Crafted URLs may bypass the intended host restriction or cause
server-side requests to unexpected destinations. Large/malformed files can consume disk,
memory, CPU, or OCR time. Same-second uploads can collide.

**Reproduction.** Submit a URL whose path/query contains an allowed token but whose
parsed hostname is not allowed. Submit an oversized file with an allowed extension or
two uploads in one second.

**Correction.** Parse with `urllib.parse`, allowlist normalized hostnames and expected
subdomains, resolve/deny private and link-local IP ranges, revalidate redirects and every
downloaded image URL, cap bytes/count/time, and validate decoded image dimensions/type.
Use random identifiers and a retention policy for uploads.

**Acceptance/regression.** Table-driven tests cover allowed hosts, deceptive hosts,
redirects, private IPs, oversized files, decompression bombs, bad image bytes, and name
collisions. Resource ceilings are observable in logs/metrics.

**Correction status (2026-07-19).** Parsed-host/DNS/redirect and bounded-fetch guards
are implemented with documented DNS-rebinding/browser-subresource residuals. Flask now
caps requests at 12 MB before OCR; direct uploads and downloaded listing photos share
actual-format, dimension, integrity, and bounded-decode validation with UUID filenames
and rejected-file cleanup. `TestUrlSafety` is 8/8 and `TestUploadSafety` is 4/4. Upload
retention and resource logging/metrics remain open, so the original acceptance is only
partially closed rather than overstated.

### F-05 — High — Integration correctness: Google WebArtwork is mock-shaped, not live-ready

**Evidence.** `providers/web_artwork.py:79` sends a local Windows path as Google
Vision's `image_uri`. A remote Vision service cannot fetch that path; local bytes should
be sent as image content or the image must first be placed at a reachable URI.
`providers/web_artwork.py:75` imports `google.cloud.vision`, but `requirements.txt` does
not install it. Relay entries repeatedly state that live acceptance did not run.

**Impact/failure mode.** The optional corroborator may return an error/not-checked in the
real configuration despite passing injected-client tests. Calling it "finished" would
inflate identification confidence.

**Reproduction.** Install the declared requirements only and invoke the default client
path with a local image: the dependency or image source is unusable.

**Correction.** Put the dependency in an explicit optional requirement group, construct
the API request with file bytes, bound size/cost, make cache/usage writes atomic, and
record request status separately from match status.

**Acceptance/regression.** A fake client asserts content bytes, not a path URI. A
credentialed opt-in integration test processes one known image and one negative image,
records cost/latency, and cannot promote identity by itself. Until then label the feature
"implemented and mock-tested; live acceptance pending."

### F-06 — High — Evidence governance: Level A contradicts the governing directive

**Evidence.** `DIRECTIVE.md:58` defines Level A as every identifying feature directly
visible/read with zero inference. `evidence.py:137-149` defines
`_provably_unique_inferred_name()`, and `evidence.py:368-374` permits such an inferred
name to reach A when other gates pass. The relay calls this a deliberate loosening, but
the governing document was not changed.

**Impact/failure mode.** Users and future agents cannot know what A guarantees. A
catalog-unique inference is valuable, but it is not the same observation class as a
direct read. Downstream automation may treat both as equally verified.

**Reproduction.** Build an identity with an inferred attack-fingerprint name, confirmed
number/catalog, and a clean collision search; it can receive A despite the documented
zero-inference rule.

**Correction.** Make a product decision explicitly. Recommended: preserve literal A for
direct observation and introduce a distinct label/status for catalog-verified inference
(for example A-direct vs B-verified-inference), or cap inference below A. Do not change
thresholds silently in code.

**Acceptance/regression.** One versioned evidence contract maps every observation type
to a level; directive, UI, API, tests, and saved datasets agree; migration is explicit;
ambiguous and collision cases still abstain.

### F-07 — High — Reproducible framework added; real full-card corpus still absent

**Evidence.** `acceptance/corpus-v1/` now contains a versioned JSONL manifest,
checksummed assets, a separate source/retention inventory, an offline state-isolated
runner, and machine/human reports. Eleven permanent tests reject malformed and duplicate
records, missing/changed/undecodable assets, footer/full-card mixing, unknown retention,
network attempts, and zero-execution success; they also verify deterministic replay. The
current full suite is 156 total, 153 passed, 3 asset-dependent skips, 0 failed.

The retained real corpus is deliberately small: 0 full-card samples and 1 footer-only
crop. Forty-four of 45 historical per-card failure records have no durable source asset.
A newly acquired eBay M Blastoise-EX front/back pair was not admitted because the
third-party seller photographs had no explicit reusable license or commit permission;
privacy cropping would not create that permission. Coalossal's temporary originals did
not survive. Neither source is silently reused.

**Measured baseline.** The frozen run executed 1/1 manifest asset with 0 unavailable and
0 errors. Local OCR of the retained Mime Jr. crop returned partial `086/PCG`, so exact
footer OCR is 0/1. The checksummed frozen deep-OCR trace parses exact `086/PCG-P`, so
parser replay is 1/1. Footer samples counted as full-card successes: 0. Full-card
precision, coverage, abstention, and high-confidence false positives are all 0/0 because
no full-card sample executed. Network attempts: 0. Production-state changes: 0.
HASH-FIRST executions: 0. The runner records raw per-sample timings and explicitly omits
p50/p90/p95 because percentiles are not meaningful at n=1. A repeated real run produced
the same deterministic evaluation hash.

**Residual impact/failure mode.** The framework closes the reproducibility and accounting
gap, but it does not establish product-level accuracy. A single footer crop cannot measure
exact-printing precision, collision recall, evidence-level confusion, or hash hit rate.
The current acceptance result is false, not a skipped or implied pass.

**Next acceptance.** Add independently grounded, retention-permitted full-card sources
with frozen offline catalog dependencies. Then report exact-printing counts, false
positives, abstentions, evidence behavior, and raw latencies until each benchmark has at
least five real samples. Keep F-06's Level-A policy contradiction visible rather than
changing it inside corpus work.

### F-08 — Medium — Scraping reliability: sensible pacing, weak replay contract

**Evidence.** The Facebook work now has one sequential browser, a collection budget,
short hover timeout, between-target maintenance, and regression coverage for a prior
catastrophic PriceCharting regex. These are good corrections. However, live HTML parsing
and Playwright selectors remain coupled to current page shape, and the repository lacks
a dated/redacted page-snapshot fixture set with retrieval status, source, and parser
version.

**Impact/failure mode.** Markup drift can silently reduce recall, misclassify posts, or
produce stale/duplicate alerts even while string-level tests remain green.

**Reproduction.** Current offline tests exercise constructed snippets, not saved complete
responses for each supported source/state.

**Correction.** Add permitted/redacted HTML/JSON snapshots for normal, sold, reserved,
auction, dead-end, login-wall, throttled, and changed-markup cases. Separate retrieval
from parsing and store `retrieval_status`, source URL/host, timestamp, parser version,
and stable source ID. Make replays idempotent.

**Acceptance/regression.** Snapshot replay yields expected normalized listings without
network access; a structural-drift fixture fails loudly; duplicate replay produces no new
alert; timeouts and fairness budgets remain bounded.

### F-09 — High — Pricing/product truth: valuation is not yet a PH profit model

**Evidence.** The repository has improved matching precision, fetch-status handling,
retry/fallback logic, and live USD/PHP caching. It does not model condition, language/
finish adjustments, listing recency/sample size, seller fees, shipping, negotiation,
liquidity, or acquisition basis. The vision explicitly calls condition a future
capability and distinguishes PH-market value from global reference prices.

**Impact/failure mode.** A single converted reference price can be presented as a fair
market value or "steal" even when the actual realizable PH price/profit interval is much
wider.

**Reproduction.** Value the same printing under materially different condition, finish,
fees, and sales channels; the current inputs cannot represent the differences.

**Correction.** Return source observations and a price interval with timestamp, currency,
condition/finish assumptions, sample count, fees/shipping, liquidity caveat, and PH
adjustment separately. Track B should add purchase basis and realized profit only after
identity and condition are human-verified.

**Acceptance/regression.** Backtest frozen historical examples without look-ahead;
publish error/coverage by card/value band and a maximum-age policy. Missing condition or
thin data must widen the range or abstain, never silently default to a precise figure.

### F-10 — Medium — Durability/concurrency: persistence has multiple unsafe writers

**Evidence.** `evidence.py`, `profile_dataset.py`, `reaudit.py`, and `app.py` perform
direct JSON read-modify-write operations. Several always-on processes share SQLite, but
no consistent WAL/busy-timeout policy is visible. Confirmation/failure JSON updates are
not locked or atomically replaced. Route tests demonstrated that these writes are easy
to trigger accidentally.

**Impact/failure mode.** Concurrent requests/processes can lose updates, corrupt JSON,
or observe half-written state. A crash during write can destroy the learning/handoff
record.

**Reproduction.** Run simultaneous confirmations/failure logs or terminate during a JSON
write; the last writer wins and no transaction protects the file.

**Correction.** Centralize repositories for state, use temp-file + fsync + atomic replace
and a process lock for JSON, or migrate mutable records to SQLite with transactions,
WAL, busy timeout, and schema migrations. Keep generated reports derived from the store.

**Acceptance/regression.** Concurrent-writer tests preserve every unique record;
crash-injection leaves either the old or complete new state; migrations are repeatable;
test stores are isolated.

**Correction status (2026-07-19).** `state_store.py` now serializes threads and OS
processes across the entire JSON mutation and uses flushed/fsynced same-directory
temporary files plus atomic replacement. Failure JSON/Markdown/rebuilds and dashboard
confirmations use it. Four isolated tests cover two simultaneous failure records, two
separate writer processes, replace-failure preservation/cleanup, and confirmation-route
persistence. `profile_dataset.py`, `reaudit.py`, other JSON writers, schema migrations,
and consistent SQLite WAL/busy-timeout policy remain open, so F-10 is partially—not
fully—closed.

### F-11 — Medium — Maintainability: one-file dashboard couples UI, control, and core logic

**Evidence.** `app.py` is about 1,500 lines and embeds HTML/JavaScript, process control,
network fetching, persistence, OCR, identification, evidence, and pricing adapters.
`tests.py` is over 1,600 lines. No lint/type/test configuration or CI workflow exists.

**Impact/failure mode.** Small changes have broad side effects, route logic drifts from
the canonical pipeline, and review ownership is unclear.

**Reproduction.** The set-code regression required tracing near-duplicate logic across
`app.py`, `profile_dataset.py`, `valuator.py`, and `evidence.py`.

**Correction.** Do not rewrite the application wholesale. First extract the canonical
identifier interface behind parity tests. Next split persistence/network adapters from
pure parsing/evidence rules. Finally split tests by subsystem while retaining lesson
traceability.

**Acceptance/regression.** Routes contain validation/translation only; core functions
have no Flask globals or production writes; the same test vectors run through all
adapters; CI runs the deterministic suite on a documented Python version.

### F-12 — Medium — Agent coordination: strong memory, excessive and conflicting status

**Evidence.** `LESSONS.md` is valuable permanent memory, and many relay entries contain
real commands and limitations. `AGENT-RELAY.md` also contains repeated unchanged blocked
updates, stale test counts, work requests mixed with completion claims, and conflicting
definitions of evidence. README still calls a partly implemented unit "ACTIVE."

**Impact/failure mode.** A new agent spends substantial time reconstructing current truth
and may repeat or trust stale claims. Documentation churn becomes a substitute for
measured progress.

**Reproduction.** Compare README's 123-test statement, the baseline suite's 116 tests,
and the relay's different counts/claims.

**Correction.** Maintain one concise current-state section with commit, environment,
verified commands, known blockers, next acceptance, and owner decisions. Append relay
entries only when state changes. Separate decisions, experiments, and completed work;
archive superseded unit specs.

**Acceptance/regression.** A fresh agent can answer "what is proven, what is blocked,
and what is next" from README/PROGRESS/current relay in under ten minutes, and every
numeric claim names its command/corpus/commit.

## 5. Dedicated component assessment

Dedicated providers are justified only when they supply independent evidence or isolate
a measured failure class. Empty abstractions do not improve confidence.

| Component | Recommendation | Reason / gate |
|---|---|---|
| Artwork verifier | Keep and harden | Independent visual corroboration is useful; calibrate local pHash and fix/live-test WebArtwork |
| Collector number / set-code parser | Keep as explicit pure component | High-value direct evidence with known cross-region collisions; needs shared canonical use |
| Language detector | Keep bounded | Affects catalog region and price; must expose observed marker vs inferred route |
| Expansion/set-symbol verifier | Build only from a labeled failure corpus | Potential independent evidence, but no current measured acceptance corpus |
| HP / ability verifier | Do not build as generic stubs | Attack/ability fingerprints already help; add specific extraction only when it closes named collisions |
| Holo/finish verifier | Defer | Needs paired normal/reverse-holo/foil photos under controlled lighting and calibration |
| Condition/authenticity | Separate future subsystem | Essential to Track B and pricing, but materially different imaging/data problem; human gate first |
| Seller automation | Do not implement now | Not authorized by the vision or this review; draft-only with per-action approval later |

The evidence response should eventually expose versioned, machine-readable top-level
fields such as `evidence_quality`, `contradiction_count`, `candidate_margin`,
`abstention_reason`, and `verification_status`. Some information already exists inside
`evidence_chain`, `collision_analysis`, `evidence_coverage`, and
`provisional_prediction_confidence`; do not add aliases casually. Design one schema and
migrate consumers after failure data shows which fields are needed.

## 6. Guidance for Claude Code and future agents

1. Start every unit by naming the governing requirement, the current reproducible
   baseline, and the exact failure class. Do not start from the latest relay adjective.
2. Use this evidence vocabulary precisely: implemented, test-proven, observed once, and
   corpus-proven. Never substitute one for another.
3. Add a failing test before a correctness fix. The test must fail for the intended
   reason and must not write production state or require hidden machine files unless it
   is explicitly an integration test.
4. Prefer one canonical path. If an adapter must differ, encode the difference in its
   schema and parity tests rather than copying business logic.
5. Treat skips as unexecuted acceptance, not passes. A unit's acceptance tests must fail
   or run; optional environment tests should be reported separately.
6. Preserve contradictions and candidates. Abstention is a product result, not an error
   to optimize away.
7. Do not broaden marketplace scraping, evidence providers, or inventory workflows until
   the current unit has a named corpus, measurement, and rollback.
8. Make no external messages, offers, purchases, bids, webhook changes, deployments, or
   pushes without the owner's explicit authorization. Seller assistance must remain
   draft-only and human-approved.
9. Keep commits small and local. The relay entry should state commit, changed behavior,
   commands/results, limitations, and the single next acceptance step.
10. When documentation and code disagree, stop promotion of the affected evidence level
    or capability until the owner/policy source is reconciled.

## 7. Prioritized remediation plan

### Immediate blockers

1. **Block public dashboard exposure.** Remove public port-5000 instructions or put the
   service behind authenticated private access before any deployment.
2. **Reconcile Level A policy.** Decide whether unique inference can ever be A, then make
   directive, code, UI, tests, and datasets agree.
3. **Unify dashboard/canonical identification.** Begin with parity tests, then replace the
   inline route logic with one service result.
4. **Fix input/network boundaries.** Parsed hostname allowlist, redirect/IP checks,
   upload limits/content validation, random filenames, and request rate/cost limits.
5. **Stop tests from touching production state.** Inject all stores/paths and add a
   repository-clean assertion.

### Short horizon

1. Build a reproducible real-photo acceptance manifest with checksums and expected
   direct/inferred fields; rerun perspective-warp/hash acceptance and measure latency.
2. Fix WebArtwork to send image bytes, declare its optional dependency, and run one
   opt-in credentialed acceptance pair with cost accounting.
3. Add CI for deterministic tests, JSON validation, Python parse/compile, inline JS
   syntax, and `git diff --check` on a documented Python version.
4. Version the identifier/evidence response and add route parity/golden tests.
5. Replace direct mutable JSON writers with one atomic/locked state layer.

### Medium horizon

1. Add source snapshot replays for each scraper and explicit retrieval/parser statuses.
2. Calibrate identification metrics on a frozen corpus; publish false-positive and
   abstention results, not only Level-A counts.
3. Build price observations/ranges with provenance, age, condition/finish assumptions,
   PH adjustment, and transaction costs.
4. Split `app.py` and `tests.py` along established interfaces after parity protection is
   in place.
5. Add operational metrics for queue time, OCR time, scraper drift, outbound cost,
   SQLite contention, and alert idempotency.

### Long horizon

1. Add a human-reviewed condition subsystem and paired image corpus.
2. Define Track B's inventory event/basis/profit schema and assisted import/export.
3. Calibrate holo/finish and authenticity only with appropriate imaging and labels.
4. Prototype one additional marketplace only after Track A identification/pricing gates
   are met and legal/ToS/account-risk research is current.

### Explicitly not now

- no automatic seller messages, negotiations, bids, purchases, or listings;
- no broad rewrite or framework migration;
- no Lazada/Shopee/eBay breadth while core acceptance is incomplete;
- no new generic evidence-provider stubs without a measured failure corpus;
- no claim that identification, condition, authenticity, pricing, or public deployment
  is production-ready.

## 8. Definition of Done

### Identification

- One canonical service handles single photos, listing photos, and binder cells.
- Every output distinguishes direct observation, normalized observation, catalog
  inference, user confirmation, and unavailable evidence.
- Exact-printing precision, false-positive rate, abstention rate, collision recall, and
  p50/p95 latency meet owner-approved thresholds on a frozen, replayable corpus.
- No acceptance test skips; hidden machine assets have a documented build/fetch manifest
  and checksums.
- All entry points pass golden parity tests.

### Scraping

- Retrieval and parsing are separate, bounded, observable stages.
- Each supported source has saved permitted snapshots for success and failure states.
- Normalized records have stable source IDs, source/retrieval timestamps, parser version,
  and explicit sold/reserved/auction/retrieval status.
- Replays are network-free and idempotent; duplicate inputs do not duplicate alerts.
- Fairness, rate, timeout, account-risk, and ToS constraints are documented and tested.

### Pricing

- Every quote names source, retrieval time, currency/FX source, sample count, printing,
  condition/finish assumption, and limitations.
- The system returns a range or abstains when evidence is thin; it does not present a
  converted global price as precise PH fair value.
- Backtests publish error and coverage by segment without look-ahead.
- Profit includes purchase basis and transaction costs only when those inputs are known
  and human-confirmed.

### Evidence

- One versioned contract defines levels/statuses and agrees with `DIRECTIVE.md` and UI.
- Contradictions, strongest alternative, candidate margin, coverage, inference source,
  abstention reason, verification status, and overturn condition are retained.
- Missing providers reduce coverage, not correctness confidence by implication.
- User confirmation is auditable and cannot silently overwrite raw evidence.

### Testing and operations

- Tests use isolated stores/paths and leave the working tree and runtime data unchanged.
- Deterministic CI runs on clean checkout; optional live tests are separate and report
  cost/environment requirements.
- Public mutation endpoints require authenticated authorization and CSRF protection;
  raw Flask is not internet-exposed.
- Uploads/outbound requests have content, size, destination, redirect, time, concurrency,
  and retention limits.
- Persistence survives concurrent writers and crash injection without losing records.

### Documentation and handoff

- README/PROGRESS state the same test count, current unit, environment requirements, and
  limitations.
- Every completion claim includes commit, command, corpus, numeric result, skips, and
  unverified scope.
- Relay updates occur only when state changes; superseded work units are archived.
- Only the owner marks a vision phase complete.

### Seller safety

- Suggested messages are drafts until the owner approves each send.
- No account action, offer, bid, purchase, listing, or webhook mutation occurs from an
  analysis/identification result alone.
- Approval, identity, price ceiling, target, and action are visible together before any
  future execution, with an audit record and kill switch.

## 9. Bottom line

Claude Code's strongest contributions are the collision/evidence discipline, permanent
regressions, bounded scraper corrections, and honest recognition that identification is
still in progress. Its weakest pattern is allowing duplicated paths, mock/synthetic
proof, and relay claims to outrun reproducible acceptance. The right next move is not
more marketplace breadth or more heuristics. It is to make one identification contract
consistent, isolated, replayable, measurable, and safe to expose.
