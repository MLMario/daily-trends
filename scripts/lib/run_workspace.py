"""Per-run output directory with typed paths for every pipeline artifact.

Paths:
  - news/articles.json              (news subagent output)
  - vendor_blogs/posts.json         (vendor-blogs subagent output)
  - corpus.json                     (normalized union of sources)
  - lineage.json                    (recluster provenance: {source_run_id, reused, created_at})
  - skipped_clustering.json         (slow-day flag: {reason, corpus_size})
  - trending_topics.json            (clustering subagent output)
  - content_recommendations.json    (recommendations subagent output)
  - email_sent.html                 (archived rendered HTML)
  - errors.log                      (JSON-lines event log)

Later slices add fields here (e.g. trending_topics.json), not new call sites.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _utc_minute_run_id(now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    return when.strftime("%Y-%m-%dT%H-%MZ")


def lineage_record(
    source_run_id: str, *, reused: Iterable[str], now: datetime | None = None
) -> dict:
    """Provenance record for a recluster — which run its inputs came from and when.

    Canonical schema for `lineage.json`: the source run id, the artifacts reused
    byte-for-byte from it, and the new run's creation time. `now` is injectable so
    the record is deterministic under test.
    """
    when = now or datetime.now(timezone.utc)
    return {
        "source_run_id": source_run_id,
        "reused": list(reused),
        "created_at": when.isoformat(),
    }


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    path: Path

    @classmethod
    def new_run(cls, runs_root: Path, *, now: datetime | None = None) -> "RunWorkspace":
        run_id = _utc_minute_run_id(now)
        path = Path(runs_root) / run_id
        if path.exists():
            raise FileExistsError(
                f"run {run_id} already exists at {path} — wait until the next UTC minute"
            )
        (path / "news").mkdir(parents=True, exist_ok=False)
        (path / "vendor_blogs").mkdir(exist_ok=False)
        return cls(run_id=run_id, path=path)

    @classmethod
    def existing_run(cls, runs_root: Path, run_id: str) -> "RunWorkspace":
        path = Path(runs_root) / run_id
        if not path.is_dir():
            raise FileNotFoundError(f"run directory not found: {path}")
        return cls(run_id=run_id, path=path)

    @property
    def news_articles(self) -> Path:
        return self.path / "news" / "articles.json"

    @property
    def vendor_blogs_posts(self) -> Path:
        return self.path / "vendor_blogs" / "posts.json"

    @property
    def corpus(self) -> Path:
        return self.path / "corpus.json"

    @property
    def lineage(self) -> Path:
        return self.path / "lineage.json"

    @property
    def skipped_clustering(self) -> Path:
        return self.path / "skipped_clustering.json"

    @property
    def trending_topics(self) -> Path:
        return self.path / "trending_topics.json"

    @property
    def content_recommendations(self) -> Path:
        return self.path / "content_recommendations.json"

    @property
    def email_sent(self) -> Path:
        return self.path / "email_sent.html"

    @property
    def errors(self) -> Path:
        return self.path / "errors.log"
