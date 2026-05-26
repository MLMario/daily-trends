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

Any **new** Claude Code skill implemented as part of this project must be tracked in git and submitted with the PR that introduces it. The `.claude/` directory is gitignored by default; scope the ignore to re-include only the new skill (e.g. `!.claude/skills/<name>/`) so bundled/global skills and `settings.local.json` stay untracked. This applies only to skills authored for this project — never commit pre-existing global or vendored skills.
