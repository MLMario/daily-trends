# daily-trends

## Agent skills

### Issue tracker

Issues are tracked as GitHub Issues at `MLMario/daily-trends` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the canonical five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context repo — one `CONTEXT.md` + `docs/adr/` at the root (created lazily by `/grill-with-docs`). See `docs/agents/domain.md`.

## PR procedure

When creating a PR, target `main` (seed it from current HEAD if origin lacks it) and structure the work as atomic commits — one per module/concern, in TDD/build order — never a single squash. PR body must include Summary, any spec deviations called out explicitly, an Acceptance Criteria checklist mirroring the issue, and a Test plan.
