# The Office — Synthetic Data

Episode scripts and synthetic therapy transcripts for characters from *The Office* (US), used as a POC dataset for testing memory and recall in clinical AI tools at SimplePractice.

## Contents

### `episode-scripts/`
All 186 episodes of *The Office* (US) as readable markdown scripts, converted from the [Scrantonicity](https://scrantonicity.co) transcript dataset. Each file is named `S##E##-episode-name.md` and includes an `air_dates.yml` with original air dates. Also includes `import_to_hindsight.py` for importing episodes into a Hindsight memory bank.

### `therapy-transcripts/`
Synthetic therapy session transcripts for Office characters, designed to test whether an AI agent can recall and synthesize information about a therapist-client alliance across multiple sessions.

**Characters in progress:**
- **Michael Scott** — 25 sessions (sessions 1-3 written, arc outlined)
- **Jim Halpert** — 25 sessions (planned)
- **Pam Beesly** — 25 sessions (planned)

See [`therapy-transcripts/README.md`](therapy-transcripts/README.md) for format details, timeline, and therapist profile.

## Source

Episode data: `https://scrantonicity.co/data/the-office.min.json`