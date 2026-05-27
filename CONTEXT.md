# daily-trends

A daily AI-trend digest pipeline: it pulls content from several **sources**, unions them into one **corpus**, clusters the corpus into topics, generates per-channel content ideas, and emails the operator a digest. Built and shipped in additive **slices**.

## Language

**Source**:
One content origin feeding the corpus — `news`, `vendor_blogs`, and (later) `x`, `instagram`. Each source writes its own raw fetch file under `runs/<run_id>/<source>/`, and `CorpusNormalizer` unions them. Adding a source is one new reader, no other module changes.

**Corpus**:
The single normalized, source-agnostic union of all fetched items for a run (`corpus.json`), schema `{id, source, account_or_outlet, posted_at, text, url}`. Everything downstream (clustering, recommendations) sees only the corpus, never a source's raw shape.

**Account** vs **Outlet**:
The two kinds of thing that fill a corpus item's `account_or_outlet` slot. An **account** is a tracked individual creator on a social source (an X handle in `creators/accounts.json[x]`); an **outlet** is a news site or vendor blog. Same field, two origins — the `source` tag disambiguates.

**X post**:
The unit the `x` source contributes to the corpus: an **original top-level** tweet from a tracked account. Replies (to others), quote tweets, and pure reposts are excluded at the scraper before normalization. A multi-tweet **thread** counts as one X post.

**Thread**:
A chain of self-replies from one account (each reply's parent is that account's own prior post). Stitched into a single corpus item — root text plus continuations concatenated in order — keyed on the root tweet's URL. The continuation tweets never appear as standalone corpus items.

**Slice**:
An additive, end-to-end increment of the pipeline that adds one **source family**. Slice A = News + Vendor blogs (shipped). **Slice B = X posts. Slice C = Instagram Reels + Whisper transcription.** Each slice is itself a working pipeline; later slices add sources without restructuring shared modules.
_Note_: B/C were swapped from the original `process_design.md` ordering on 2026-05-26 to match build order (X before Instagram).

**Implementation increment**:
A numbered vertical step *within* a slice, tracked as a GitHub issue and a `slice-<n>-<topic>` branch (e.g. `slice-7-recluster`). These integers are unrelated to the slice *letters* above — Slice A was delivered across increments 1–7.
_Avoid_: calling a numbered increment a "slice B/C" or vice-versa.

## Flagged ambiguities

- **"slice"** is overloaded: a *letter* slice (A/B/C) is a source-family milestone; a *numbered* slice (`slice-7-…`) is an implementation increment / branch. When unqualified, "slice" means the letter slice. Resolved 2026-05-26.
