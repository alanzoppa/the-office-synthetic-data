#!/usr/bin/env python3
"""
Import The Office episode scripts into a Hindsight bank.

Reads the markdown episode files and air_dates.yml from this repo,
creates a new Hindsight bank, and imports each episode as a document
with:
  - timestamp set to the original air date (ISO 8601)
  - tags: season and episode tags (e.g. #S02 #E01) plus source tag
  - document_id: the filename without .md extension
  - context: "Season X / Episode Y"

Usage:
  1. Ensure Hindsight is running and accessible at HINDSIGHT_API
  2. Set BANK_ID if you want a different bank name (default: the-office)
  3. Run from the repo root: python3 import_to_hindsight.py

  To re-import (e.g. after data changes):
  1. Delete the bank: curl -X DELETE http://127.0.0.1:8888/v1/default/banks/{BANK_ID}
  2. Re-run this script

Requires: Python 3.10+, curl on PATH
No pip dependencies — uses only stdlib + curl subprocess calls.
"""
import os, sys, re, json, time, subprocess, glob

# === CONFIG ===
HINDSIGHT_API = os.environ.get("HINDSIGHT_API", "http://127.0.0.1:8888")
BANK_ID = os.environ.get("HINDSIGHT_BANK", "the-office")
BANK_NAME = "The Office Scripts"
REPO_DIR = os.path.dirname(os.path.abspath(__file__))

BANK_REFLECT_MISSION = (
    "This bank documents the daily interactions and personal lives of "
    "employees at Dunder Mifflin in Scranton, PA, spanning 2005 to 2013. "
    "When reflecting, synthesize across episodes to build a genuine "
    "understanding of each person:\n"
    "\n"
    "  — Who is this person? What do they want, what are they afraid of,\n"
    "    and how do they protect themselves?\n"
    "  — What patterns repeat in their relationships and emotional life?\n"
    "  — How do they handle conflict, vulnerability, rejection, intimacy?\n"
    "  — What experiences shaped them — and how do those experiences show\n"
    "    up in their present behavior?\n"
    "  — Where is there growth, regression, or unresolved pain?\n"
    "\n"
    "Treat every event as true and every person as real. Prioritize "
    "emotional and psychological insight over plot summary. When asked "
    "about a person, draw from their full history in the bank — not just "
    "a single moment. Surface the deeper currents: what someone says vs. "
    "what they mean, what they do vs. what they feel, who they are when "
    "no one is watching vs. who they perform for others."
)

# CRITICAL: retain_mission controls LLM entity subject assignment.
# Without it, the bank name leaks into experience entities.
BANK_RETAIN_MISSION = (
    "These are episode transcripts documenting the daily lives and "
    "interactions of employees at Dunder Mifflin, a paper company in "
    "Scranton, PA. Each document is one full day or event. Extract facts "
    "about:\n"
    "\n"
    "  — Emotional states and reactions: how characters feel during and "
    "after\n"
    "    events, what triggers strong responses, how they cope or deflect\n"
    "  — Interpersonal dynamics: who supports whom, who conflicts with "
    "whom,\n"
    "    power imbalances, unspoken tensions, acts of kindness or cruelty\n"
    "  — Personal history and identity: what characters reveal about "
    "their\n"
    "    upbringing, families, values, insecurities, hopes, and self-image\n"
    "  — Relationship arcs: how relationships form, deepen, fracture, or\n"
    "    repair over time — romantic, platonic, professional, familial\n"
    "  — Behavioral patterns: recurring coping strategies, avoidance,\n"
    "    overcompensation, people-pleasing, boundary violations, growth\n"
    "\n"
    "Use each character's name as the entity — Michael, Jim, Pam, "
    "Dwight,\n"
    "Angela, Kevin, Oscar, Andy, Ryan, Kelly, Creed, Darryl, Phyllis, "
    "Stanley,\n"
    "Toby, Erin, Jan, Holly, Roy, David Wallace, and others as they "
    "appear.\n"
    "\n"
    "Extract earnestly. These are real events happening to real people. "
    "Do\n"
    "not treat them as comedy or fiction. Record what happened, how "
    "people\n"
    "felt, and what it reveals about who they are. Skip scene transitions "
    "and\n"
    "production metadata."
)

CREATE_BANK = True
IMPORT_DELAY_SECONDS = 0.3
IMPORT_BATCH_DELAY_EVERY = 10  # delay every N episodes


# === YAML PARSER (minimal, for air_dates.yml) ===
def parse_air_dates(filepath):
    """Parse the air_dates.yml file into a dict: {filename_key: 'YYYY-MM-DD'}."""
    dates = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Pattern: S01E01-pilot: "2005-03-24"
            m = re.match(r'^(\S+):\s*"(\d{4}-\d{2}-\d{2})"', line)
            if m:
                dates[m.group(1)] = m.group(2)
    return dates


# === EPISODE PARSER ===
def parse_episode(filepath):
    """Parse an episode markdown file. Returns (title, season, episode, body)."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract title from first line: "# Title"
    title_match = re.match(r'^#\s+(.+)$', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else os.path.basename(filepath).replace(".md", "")

    # Extract season and episode from: "**Season X · Episode Y**"
    meta_match = re.search(r'\*\*Season\s+(\d+)\s*·\s*Episode\s+(\d+)\*\*', content)
    season = int(meta_match.group(1)) if meta_match else 0
    episode = int(meta_match.group(2)) if meta_match else 0

    return title, season, episode, content


# === BANK CREATION + VERIFICATION ===
def create_bank(bank_api):
    """Create bank with name + missions, then verify and PATCH if fields didn't stick.

    Hindsight's PUT often returns "could not resize shared memory segment" — the bank
    IS created but name/missions are NOT applied. Always verify and PATCH.
    """
    print(f"\n=== Phase 0: Creating bank '{BANK_ID}' ===")
    bank_payload = {
        "name": BANK_NAME,
        "reflect_mission": BANK_REFLECT_MISSION,
        "retain_mission": BANK_RETAIN_MISSION,
        "retain_extraction_mode": "concise",
    }
    r = subprocess.run(
        ["curl", "-s", "-X", "PUT", bank_api,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(bank_payload)],
        capture_output=True, text=True, timeout=30
    )
    print(f"Bank creation response: {r.stdout[:300]}")
    time.sleep(2)

    # Verify name and missions were set
    r = subprocess.run(
        ["curl", "-s", f"{HINDSIGHT_API}/v1/default/banks"],
        capture_output=True, text=True, timeout=10
    )
    banks = json.loads(r.stdout).get("banks", [])
    bank = next((b for b in banks if b["bank_id"] == BANK_ID), {})
    bank_name = bank.get("name", "")
    bank_mission = bank.get("mission", "")

    needs_patch = []
    if bank_name != BANK_NAME:
        needs_patch.append(("name", BANK_NAME))
    if not bank_mission:
        needs_patch.append(("reflect_mission", BANK_REFLECT_MISSION))

    # Check retain_mission in config
    r = subprocess.run(
        ["curl", "-s", f"{bank_api}/config"],
        capture_output=True, text=True, timeout=10
    )
    config = json.loads(r.stdout).get("config", {})
    if not config.get("retain_mission"):
        needs_patch.append(("retain_mission", BANK_RETAIN_MISSION))

    if needs_patch:
        print(f"  PATCHing fields that didn't stick: {[f for f, _ in needs_patch]}")
        for field, value in needs_patch:
            r = subprocess.run(
                ["curl", "-s", "-X", "PATCH", bank_api,
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({field: value})],
                capture_output=True, text=True, timeout=10
            )
            print(f"  PATCH {field}: {r.stdout[:100]}")
    else:
        print("  All fields set correctly on first try.")


# === MAIN ===
def main():
    # Load air dates
    air_dates_path = os.path.join(REPO_DIR, "air_dates.yml")
    if not os.path.exists(air_dates_path):
        print(f"ERROR: air_dates.yml not found at {air_dates_path}")
        sys.exit(1)
    air_dates = parse_air_dates(air_dates_path)
    print(f"Loaded {len(air_dates)} air dates from air_dates.yml")

    # Find all episode markdown files
    md_files = sorted(glob.glob(os.path.join(REPO_DIR, "S*.md")))
    print(f"Found {len(md_files)} episode files")

    bank_api = f"{HINDSIGHT_API}/v1/default/banks/{BANK_ID}"

    if CREATE_BANK:
        create_bank(bank_api)

    # === IMPORT ===
    print(f"\n=== Phase 1: Importing {len(md_files)} episodes ===")
    imported = 0
    errors = 0
    skipped = 0
    no_date = 0
    date_from_yaml = 0

    for i, filepath in enumerate(md_files):
        filename = os.path.basename(filepath)
        file_key = filename.replace(".md", "")  # e.g., S03E02-the-convention

        try:
            title, season, episode, content = parse_episode(filepath)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ERROR parsing {filename}: {e}")
            continue

        if len(content.strip()) < 50:
            skipped += 1
            continue

        # Get air date from YAML — convert to ISO 8601 timestamp
        air_date = air_dates.get(file_key)
        if air_date:
            timestamp = f"{air_date}T00:00:00Z"
            date_from_yaml += 1
        else:
            no_date += 1
            timestamp = "unset"

        # Build tags: season + episode + source
        tags = [
            f"S{season:02d}",
            f"E{episode:02d}",
            "source:the-office",
            "the-office",
        ]

        # Context: season / episode
        context = f"Season {season} / Episode {episode}"

        # Document ID: filename without .md (enables traceability + upsert)
        doc_id = f"the-office:{file_key}"

        payload = {
            "items": [{
                "content": content,
                "document_id": doc_id,
                "tags": tags,
                "context": context,
                "timestamp": timestamp,
            }],
            "async": True
        }

        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{bank_api}/memories",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=30
        )

        if r.stdout and '"error"' not in r.stdout.lower():
            imported += 1
            if imported % 25 == 0:
                print(f"  Progress: {imported}/{len(md_files)} imported")
        else:
            errors += 1
            if errors <= 10:
                print(f"  ERROR importing {filename}: {r.stdout[:200]}")

        if i > 0 and i % IMPORT_BATCH_DELAY_EVERY == 0:
            time.sleep(IMPORT_DELAY_SECONDS)

    print(f"\n=== Complete ===")
    print(f"Imported: {imported}")
    print(f"Skipped (too short): {skipped}")
    print(f"Errors: {errors}")
    print(f"Date from air_dates.yml: {date_from_yaml}")
    print(f"No date found (used 'unset'): {no_date}")
    print(f"Total processed: {len(md_files)}")

    # === Stats ===
    r = subprocess.run(["curl", "-s", f"{bank_api}/stats"], capture_output=True, text=True, timeout=10)
    print(f"\nBank stats: {r.stdout[:500]}")

    # === Verification: check a few documents ===
    print(f"\n=== Verification ===")
    r = subprocess.run(
        ["curl", "-s", f"{bank_api}/documents?limit=5"],
        capture_output=True, text=True, timeout=10
    )
    try:
        docs = json.loads(r.stdout).get("documents", [])
        for doc in docs[:3]:
            doc_id = doc.get("document_id", "?")
            doc_tags = doc.get("tags", [])
            doc_ts = doc.get("timestamp", "?")
            print(f"  {doc_id} | tags={doc_tags} | ts={doc_ts}")
    except json.JSONDecodeError:
        print(f"  (could not parse document list: {r.stdout[:200]})")

    print(f"\nNext steps:")
    print(f"  - Check pending ops: curl -s {bank_api}/operations | python3 -m json.tool")
    print(f"  - Test recall: curl -s -X POST {bank_api}/memories/recall "
          f"-H 'Content-Type: application/json' -d '{{\"query\": \"Dwight fire\"}}'")
    print(f"  - Control Plane UI: check bank '{BANK_ID}' in the Hindsight UI")


if __name__ == "__main__":
    main()