# Therapy Transcripts

Synthetic therapy session transcripts for characters from *The Office* (US), designed as a POC dataset for testing memory and recall in clinical AI tools at SimplePractice.

## Structure

```
therapy-transcripts/
  michael-scott/
    outline.md              # 25-session arc outline
    treatment-plan.md       # Written after session 3
    session-01/
      transcript.txt         # Diarized session transcript
      note.txt              # SOAP progress note
    session-02/
      transcript.txt
      note.txt
    session-03/
      transcript.txt
      note.txt
    ...
  jim-halpert/              # TBD
  pam-beesly/               # TBD
```

## Format

### Transcripts
- Diarized format: `clinician:` / `client:` speaker labels
- Plain text, no markdown, no timestamps
- Short-to-medium turns, naturalistic speech with interruptions and tangents
- Target length: ~3000 words per session

### Notes
- SOAP format (Subjective, Objective, Assessment, Plan)
- Written from the clinician's perspective
- Reference treatment plan goals by number

## Timeline

Sessions run within the show's timeline (Seasons 2-4), roughly late Season 3 through the Season 4 finale (Nov 2006 – May 2008 in show time). Canon events from the show are referenced naturally by the client; the therapist does not know the show.

## Therapist

All three characters see the same therapist: **Dr. Karen Mitchell, LCSW** — a competent, unflashy, integrative clinician who uses MI reflections, CBT techniques, and attachment-informed psychodynamic awareness.

## Generation

- **Model:** GLM-5.2 Xhigh via Ollama Cloud
- **Pipeline:** Sequential (session N depends on session N-1's transcript and note), parallel across characters
- **Source repo for episode scripts:** `episode-scripts/` directory (186 episodes, all 9 seasons)