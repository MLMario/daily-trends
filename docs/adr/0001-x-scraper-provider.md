# ADR 0001 — X scraping pathway (deferred)

**Status:** deferred (2026-05-28). Re-evaluate only when an authenticated X provider is funded.

## Decision

Do not pursue the X-posts source in the daily-trends pipeline at this time. Slice C (X) in `process_design.md` is documented but not on the active build path.

## Context

Slice B (originally X, swapped ahead of Instagram on 2026-05-26 in a now-abandoned branch) was implementation-attempted across three sessions in 2026-05-27 → 2026-05-28. The attempt produced a Bright Data client, an XScraper transform, opt-in gating, and a per-source word-count floor — all subsequently rewound from `main` on 2026-05-28 along with this ADR's prior "accepted" version. This is the post-rewind record of what the investigation found.

## Investigation results (2026-05-27 → 2026-05-28)

Three unauthenticated providers were tested against the same two account classes: small AI-researcher accounts (`@gaosiki666`, `@ClaudeDevs`) and a firehose control (`@elonmusk`).

| Provider | Small accounts | Firehose control |
|---|---|---|
| **Bright Data** `gd_lwxkxvnf1cynvib9co` | 0 records; `dead_page` / `wait_element_timeout` errors across 4 snapshots | 151 records on a wide window (works) |
| **Apify Free plan** `apidojo~tweet-scraper` | Inconclusive — actor blocked by paywall in run log: *"You cannot use the API with the Free Plan"* (emitted `[{noResults:true}]×10` sentinel + HTTP 201 — looked like success but wasn't) | Same paywall |
| **scrapegraphAI v2** `/api/crawl` + `/api/history` | `data: {}` — empty extraction | Posts returned **but stale**: latest `@elonmusk` = 2024-11-06, `@erikbryn` = 2024-09-24 (today = 2026-05-28). 18+ months of staleness. Unusable for "daily trends" even ignoring the gate. |

## Root cause

X.com's logged-out content gate (a) hides smaller accounts entirely from unauthenticated scrapers, (b) serves stale cached snapshots for large accounts. Every unauthenticated provider inherits both problems — they are not solvable inside the provider seam, they are solvable only by authenticating the session.

## When this ADR would be re-opened

Re-evaluate when one of the following is funded:

- **Paid Apify with session-pool actor** (~$49/mo). Session pool authenticates against logged-in X cookies, bypassing the gate.
- **X official API Basic** ($200/mo, 10k posts/mo cap). First-party, no scraping, but quota-constrained for a curated-account use case.
- **Self-hosted Playwright with logged-in cookies**. Engineering-heavy; account-ban risk; no managed-service support.

None is recommended without explicit cost approval. The decision to re-open is the operator's, not an implementation question.

## Consequences

- No `x` source in `CorpusNormalizer`'s `_sources()`, no `scrape_x.py`, no `lib/x_scraper.py`, no `lib/bright_data.py`, no `creators/accounts.json[x]`, no `x_lookback_days` config key, no per-source word-count floor on `main`.
- `BRIGHT_DATA_KEY`, `APIFY_KEY`, and `SCRAPEGRAPHAI_KEY` may remain in `.env` — all three were proven authentic during the investigation and cost nothing to keep. A future re-opening shouldn't have to re-acquire credentials.
- `process_design.md` Slice C section preserves the Bright Data choice as documented future surface; this ADR documents why that surface stayed un-built.

## Considered alternatives at the time of investigation

- **Bright Data over Apify Free** — original 2026-05-26 choice based on Bright Data's confirmed discover-by-profile date-range support. Falsified: Bright Data fails on small accounts due to the X gate, not due to API capability.
- **Apify Free as a fallback** — falsified: Apify Free actor is paywalled in practice despite being labeled "free."
- **scrapegraphAI as a generic web extractor** — falsified: serves stale cached pages, unsuitable for any "today's posts" use case.

All three falsifications trace to the same root cause; switching providers within the unauthenticated category cannot succeed.
