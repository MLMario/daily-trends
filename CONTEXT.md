# daily-trends

A daily content-discovery pipeline that gathers AI-focused signal from a few source families (news, vendor blogs, Instagram Reels), clusters it into topics, and emails the operator a digest plus per-channel content ideas.

## Language

### Pipeline shape

**Run**:
One end-to-end invocation of the pipeline. Identified by a UTC-minute timestamp and materialised as a single immutable `runs/<run_id>/` directory; no run ever modifies another.
_Avoid_: job, execution, batch.

**Slice**:
An additive build phase of the pipeline. Slice A (news + vendor blogs) shipped; Slice B (Instagram Reels) is being built; Slice C (X) is deferred. Each slice extends the same shared modules — it never restructures them.
_Avoid_: phase, milestone, release.

**Corpus**:
The day's normalized union of all source records that survived the per-source filters. The single input the clustering and recommendations subagents read. Lives at `runs/<run_id>/corpus.json` as a JSON array of items with shape `{id, source, account_or_outlet, posted_at, text, url}`.
_Avoid_: dataset, feed, items list.

**Corpus item**:
One record inside the corpus. Every source produces corpus items in the same schema — no source-specific fields. The `text` field is a single blob the LLM reads; per-source nuance is encoded by composing into that blob, never by extending the schema.
_Avoid_: document, entry, post.

**Topic**:
A cluster of ≥ 2 corpus items that the clustering subagent has decided are about the same underlying story. Singletons are not topics — they land in `other_notable`.
_Avoid_: cluster, group, theme.

### Deliverables

**Digest**:
The per-run email deliverable: a topic-card HTML body rendered deterministically by `EmailRenderer` from `trending_topics.json` + `content_recommendations.json` (full path) or a light-signal layout (slow day), then dispatched via Gmail. The run's primary output; the Report rides along as an attachment.
_Avoid_: email (too generic — the Digest is the *content*; the email is the envelope), newsletter, summary.

**Report**:
A per-run, idea-centric HTML deliverable grouped by **Channel**, produced by a dedicated report subagent alongside the Digest and attached to the same Digest email. Materialised as `runs/<run_id>/report.html` — the subagent's sole artifact (it emits HTML directly; see `docs/adr/0004-*`). One section per Channel, each a three-column **Idea | Resources | Virality** table, one row per Topic. Produced only on the full path; a slow day writes no Report.
_Avoid_: digest (the Digest is the email body, distinct), scorecard, dashboard.

**Idea**:
One per-Channel content suggestion for a Topic — the cell the Report leads with. Sourced from a recommendation's `ideas` map keyed by Channel (`ideas[<channel>]`). The same `Idea` vocabulary the recommendations subagent already produces; the Report surfaces it per Channel rather than per Topic card.
_Avoid_: recommendation (reserved for the subagent/file), suggestion, post.

**Virality score**:
The per-row signal of how likely a Topic's Idea is to spread on a given Channel — the Report's third column. A 1–10 composite the report subagent computes per **rubric** from the Idea text + Topic context only (no source-post engagement metrics), backed by five per-dimension sub-scores and a 2-sentence justification, rendered as a color-coded **Virality badge** (red ≤4, amber 5–7, green ≥8). Scoring is per-Channel and **rubric-keyed**: a Channel with a rubric is scored and its section sorts by composite descending; a Channel without one (e.g. `substack`) reads the literal em dash `—` and stays in Topic order. `linkedin` scoring shipped; `instagram` follows; the band/weight/badge math is the tested `scripts/lib/virality_badge.py`.
_Avoid_: engagement, reach, popularity, score (qualify it — always "Virality score").

**Rubric**:
A Channel-specific, weighted set of 1–10 dimensions the report subagent scores an Idea against to produce its **Virality score**. The LinkedIn rubric is Hook Tension 25%, Opinion Sharpness 25%, Narrative Structure 20%, Niche Fit 20%, Saveability 10%; its 1→10 anchor descriptions live in `prompts/report_prompt.md`, its weights + composite/band math in `scripts/lib/virality_badge.py`. A Channel either has a rubric (scored) or does not (scoreless `—`) — the rubric's *presence* is what keys that split, never a channel name.
_Avoid_: criteria, scorecard, formula.

**Sources**:
A Topic's resolved corpus members rendered as links in the Report's **Resources** column (and the Digest's member list): each `member_id` resolved against `corpus.json` to its corpus item, rendered as **Outlet → url**. Ids absent from the corpus are skipped silently, identically in the Report and the Digest.
_Avoid_: references, citations, links (links is the rendering, not the concept), members (member_ids is the raw input; Sources is the resolved output).

### Sources

**Source**:
A family of inputs that produces corpus items. Slice A has `news` (Hacker News + TechCrunch AI) and `vendor_blogs` (Anthropic + OpenAI Devs). Slice B adds `instagram`. Each source is a separate fetcher with its own opt-in config; downstream stages are source-agnostic.
_Avoid_: provider, channel (channel is reserved — see below).

**Channel**:
A publishing destination the recommendations step writes ideas for — currently `substack`, `linkedin`, `instagram`. Channels are configured per-operator; they have nothing to do with where the corpus came from.
_Avoid_: platform, outlet (outlet is reserved — see `account_or_outlet`).

**Outlet**:
The human-readable label for the entity that produced a corpus item — `"Hacker News"`, `"Anthropic Blog"`, `"@hellovidya"`. Stored as the `account_or_outlet` field. Always a label, never a URL or numeric id.
_Avoid_: publisher, author, handle (handle is one shape an outlet can take — the IG-creator shape).

### Instagram-specific

**Reel**:
A single Instagram short-form video post. The Bright Data dataset we use is reels-only by definition; non-Reel Instagram posts (photos, carousels) are out of scope. One Reel produces at most one corpus item.
_Avoid_: post, video, clip.

**Creator**:
An Instagram account on the curated `creators/accounts.json[instagram]` list whose Reels we scrape. Identified by handle, written `@hellovidya` in the corpus' `account_or_outlet` field.
_Avoid_: influencer, user, account (account is overloaded — only use inside `account_or_outlet`).

**Caption**:
The creator-written description attached to a Reel. May be empty or null. In the corpus' `text` field it appears suffixed to the transcript as `\n\n[Caption: <description>]`, never as the primary signal.
_Avoid_: description, body, copy.

**Transcript**:
The Whisper-produced text of a Reel's audio. A Reel without a transcript does not enter the corpus — transcript is the load-bearing signal; caption alone is insufficient. Two-pass when the Reel is non-English: pass 1 produces the native-language `text`, pass 2 produces `text_en` and is what the corpus carries.
_Avoid_: subtitles, captions (captions ≠ Caption above), STT output.

**Snapshot**:
Bright Data's term for the asynchronous result of a discover-by-profile call — a batch of Reel metadata records keyed by `snapshot_id`. Triggered by `POST /datasets/v3/trigger`, polled via `/progress/{snapshot_id}`, fetched via `/snapshot/{snapshot_id}`.
_Avoid_: scrape, fetch, batch (Bright Data's own term wins).

**Lookback window**:
The date range passed to a snapshot trigger as `start_date`/`end_date` in MM-DD-YYYY format. Driven by `config.instagram_lookback_days` (default 7).
_Avoid_: time range, date window.

## Example dialogue

> **Dev:** When the clustering subagent runs, does it see different field sets for a Hacker News article vs. an Instagram Reel?
>
> **Domain expert:** No — that's the point of the **corpus**. By the time clustering runs, every record is a **corpus item** with the same six fields. A Reel's **transcript** has been merged with its **caption** into the single `text` field upstream, in the IG **source** reader. Clustering doesn't know "Reel" exists; it sees text.
>
> **Dev:** So if a Reel's Whisper run failed, what does the corpus see?
>
> **Domain expert:** Nothing — that Reel is dropped at normalize time and a warning is logged. **Transcript** is load-bearing; **caption** alone doesn't carry enough signal to cluster on. We'd rather lose the Reel than feed a topic on the strength of "AI is wild 🤯".
>
> **Dev:** And the **snapshot** — when do we know it's done?
>
> **Domain expert:** We poll `/progress/{snapshot_id}` every 30 s until status flips to `ready` or `failed`. Then we GET the snapshot, write each record to `<post_id>.meta.json`, and hand the `.mp4` URLs to yt-dlp. Snapshot is purely Bright Data's term — once we've fetched it, we're back in our domain (Reels, **creators**, **outlets**).
