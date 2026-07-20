#!/usr/bin/env python3
"""
Import a client's complete therapy record into a Hindsight bank.

Reads the synthetic therapy files for one client and imports every session
transcript, every SOAP progress note, and both treatment-plan documents into
a new Hindsight bank. Each document is timestamped to its real session date,
tagged, and given a stable document_id for traceability and upsert.

Nothing is customized per individual. Every client goes through the same
path: the client name, clinician, bank id/name, and clinician tag are
derived from the client's own files, and the missions are generic — they
identify the client and clinician by name so entity extraction is anchored,
and otherwise leave all clinical and psychological interpretation to
Hindsight.

Document types imported:
  - session transcripts   (session-NN/transcript.txt)
  - session notes         (session-NN/note.txt, SOAP format)
  - treatment plan        (treatment-plan.md)
  - treatment plan update (treatment-plan-update-session-20.md)

Session dates are read from <client>/outline.md ("Week of Mon DD, YYYY").
Treatment-plan dates are read from each plan's "Date:" header.

Usage:
  1. Ensure Hindsight is running and accessible at HINDSIGHT_API
  2. Choose a client (default: michael-scott):
       python3 therapy-transcripts/import_therapy_to_hindsight.py pam-beesly
     or set HINDSIGHT_CLIENT=pam-beesly
     Optionally override the bank id with HINDSIGHT_BANK.
  3. Run from anywhere; paths resolve relative to this script.

  Adding a new client (e.g. jim-halpert): just drop the client's directory
  (same layout: outline.md, session-NN/, treatment-plan*.md) next to this
  script and run it with that directory name. No code changes needed.

  To re-import (e.g. after data changes):
  1. Delete the bank:
     curl -X DELETE http://127.0.0.1:8888/v1/default/banks/{BANK_ID}
  2. Re-run this script

Requires: Python 3.10+, curl on PATH
No pip dependencies — uses only stdlib + curl subprocess calls.
"""
import os, sys, re, json, time, subprocess, glob
from datetime import datetime

# === CONFIG ===
HINDSIGHT_API = os.environ.get("HINDSIGHT_API", "http://127.0.0.1:8888")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CREATE_BANK = True
IMPORT_DELAY_SECONDS = 0.3
IMPORT_BATCH_DELAY_EVERY = 10  # delay every N documents


# === CLIENT CONFIG (derived from files — nothing customized per individual) ===
def _clinician_tag(clinician_short):
    """'Dr. James Pierce' -> 'therapist:dr-pierce' (last name-ish token)."""
    tokens = re.findall(r"[A-Za-z]+", clinician_short)
    last = tokens[-1].lower() if tokens else "clinician"
    return f"therapist:dr-{last}"


def client_config(client_key, client_dir):
    """Build a client's config from the files on disk. The client and
    clinician names come from outline.md, with a fallback to the intake
    note header; everything else is a deterministic template."""
    client_name = None
    clinician_name = None

    outline_path = os.path.join(client_dir, "outline.md")
    if os.path.exists(outline_path):
        with open(outline_path, "r", encoding="utf-8") as f:
            outline = f.read()
        m = re.search(r'^#\s+(.+?)\s+Therapy Arc\s*$', outline, re.MULTILINE)
        if m:
            client_name = m.group(1).strip()
        m = re.search(r'\*\*Therapist:\*\*\s*(.+)', outline)
        if m:
            clinician_name = m.group(1).strip()

    # Fall back to / confirm from the intake note header.
    note_path = os.path.join(client_dir, "session-01", "note.txt")
    if os.path.exists(note_path):
        with open(note_path, "r", encoding="utf-8") as f:
            head = f.read(1000)
        if not client_name:
            m = re.search(r'^Client:\s*(.+)', head, re.MULTILINE)
            if m:
                client_name = m.group(1).strip()
        if not clinician_name:
            m = re.search(r'^Clinician:\s*(.+)', head, re.MULTILINE)
            if m:
                clinician_name = m.group(1).strip()

    if not client_name:
        # Last resort: title-case the key ("jim-halpert" -> "Jim Halpert").
        client_name = client_key.replace("-", " ").title()
    if not clinician_name:
        clinician_name = "the clinician"

    clinician_short = clinician_name.split(",")[0].strip()

    return {
        "client_name": client_name,
        "clinician_name": clinician_name,
        "clinician_short": clinician_short,
        "therapist_tag": _clinician_tag(clinician_short),
        "bank_id": f"{client_key}-therapy",
        "bank_name": f"{client_name} — Therapy Record",
    }


# === MISSION BUILDERS (generic; no per-individual detail) ===
def reality_disclaimer(c):
    """The disclaimer that must lead BOTH missions: treat this as a genuine
    clinical record of a real person, and any resemblance to fiction as
    coincidental."""
    return (
        f"IMPORTANT: This is a real clinical record documenting real therapy "
        f"sessions with a real client, {c['client_name']}, and the client's "
        f"real clinician, {c['clinician_name']}. These are real-life events. "
        f"Any resemblance to fictional characters, entities, or events is "
        f"purely coincidental. Treat every session, note, and clinical "
        f"observation as an authentic account of a real person's life and "
        f"treatment — never as fiction, parody, or comedy."
    )


def reflect_mission(c):
    return (
        reality_disclaimer(c) + "\n\n"
        f"This bank holds the complete course of therapy for "
        f"{c['client_name']}: session transcripts, SOAP progress notes, and "
        f"treatment plan documents. When reflecting, synthesize across the "
        f"full record to build a coherent clinical picture:\n"
        f"\n"
        f"  — Who is this client? What does the client want, what does the\n"
        f"    client fear, and how does the client self-protect?\n"
        f"  — What is the core cognitive schema, and how does it show up\n"
        f"    across sessions?\n"
        f"  — How do the treatment goals progress over time — what has\n"
        f"    shifted, what remains, and what is the evidence?\n"
        f"  — How does the therapeutic alliance develop, including ruptures,\n"
        f"    repairs, and transference?\n"
        f"  — What early attachment history shaped the client, and how does\n"
        f"    it recur in the client's present relationships?\n"
        f"\n"
        f"Prioritize clinical and psychological insight over event summary. "
        f"When asked about the client, draw from the full history across "
        f"every session — not a single moment. Surface the deeper currents: "
        f"what the client says vs. means, what the client performs vs. feels, "
        f"and who the client is when no one is watching."
    )


def retain_mission(c):
    # CRITICAL: retain_mission controls LLM entity subject assignment.
    # Without it, the bank name leaks into experience entities.
    return (
        reality_disclaimer(c) + "\n\n"
        f"Each document is one real clinical artifact: a session transcript, "
        f"a SOAP progress note, or a treatment plan for the client "
        f"{c['client_name']}. Extract facts about:\n"
        f"\n"
        f"  — Emotional states and reactions: how the client feels during "
        f"and\n"
        f"    after events, what triggers strong responses, how the client\n"
        f"    copes or deflects\n"
        f"  — Clinical content: presenting problems, symptoms, mental "
        f"status,\n"
        f"    diagnoses, core beliefs, treatment goals and their progress\n"
        f"  — The therapeutic alliance: rapport, ruptures, repairs, "
        f"transference,\n"
        f"    homework, behavioral experiments and their outcomes\n"
        f"  — Personal history and identity: family, upbringing, values,\n"
        f"    insecurities, hopes, self-image, and attachment history\n"
        f"  — Relationship patterns: how the client relates to others, and "
        f"how\n"
        f"    those patterns replay earlier attachment experiences\n"
        f"\n"
        f"Use the client's name, {c['client_name']}, as the entity, and use "
        f"the clinician's name, {c['clinician_short']}, where relevant. Other "
        f"real people in the client's life may appear as they come up.\n"
        f"\n"
        f"Extract earnestly. These are real events happening to real people. "
        f"Do not treat them as comedy, parody, or fiction, and do not treat "
        f"any resemblance to fictional characters as anything but "
        f"coincidental. Record what happened, how the client felt, and what "
        f"it reveals clinically. Skip formatting artifacts and boilerplate "
        f"headers."
    )


# === DATE PARSING ===
def parse_session_dates(outline_path):
    """Parse <client>/outline.md → {session_number: 'YYYY-MM-DD'}.

    Matches headers like:
      ### Session 1 — Intake ... (Week of Nov 20, 2006)
    """
    dates = {}
    pattern = re.compile(
        r'^###\s+Session\s+(\d+)\b.*?\(Week of\s+([A-Z][a-z]{2,})\s+(\d+),\s*(\d{4})\)'
    )
    with open(outline_path, "r", encoding="utf-8") as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m:
                continue
            n = int(m.group(1))
            month_abbr = m.group(2)[:3]  # "November" -> "Nov"
            dt = datetime.strptime(
                f"{month_abbr} {int(m.group(3))} {m.group(4)}", "%b %d %Y"
            )
            dates[n] = dt.strftime("%Y-%m-%d")
    return dates


def parse_plan_date(plan_path):
    """Parse a treatment plan's '(Week of Month DD, YYYY)' → 'YYYY-MM-DD'."""
    with open(plan_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'\(Week of\s+([A-Z][a-z]+)\s+(\d+),\s*(\d{4})\)', content)
    if not m:
        return None
    dt = datetime.strptime(
        f"{m.group(1)[:3]} {int(m.group(2))} {m.group(3)}", "%b %d %Y"
    )
    return dt.strftime("%Y-%m-%d")


def iso(date_str):
    """'YYYY-MM-DD' -> ISO 8601 timestamp, or 'unset' if None."""
    return f"{date_str}T00:00:00Z" if date_str else "unset"


# === BANK CREATION + VERIFICATION ===
def create_bank(bank_api, c):
    """Create bank with name + missions, then verify and PATCH if fields didn't stick.

    Hindsight's PUT often returns "could not resize shared memory segment" — the bank
    IS created but name/missions are NOT applied. Always verify and PATCH.
    """
    bank_id = c["bank_id"]
    bank_name = c["bank_name"]
    r_mission = reflect_mission(c)
    x_mission = retain_mission(c)

    print(f"\n=== Phase 0: Creating bank '{bank_id}' ===")
    bank_payload = {
        "name": bank_name,
        "reflect_mission": r_mission,
        "retain_mission": x_mission,
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
    bank = next((b for b in banks if b["bank_id"] == bank_id), {})
    got_name = bank.get("name", "")
    got_mission = bank.get("mission", "")

    needs_patch = []
    if got_name != bank_name:
        needs_patch.append(("name", bank_name))
    if not got_mission:
        needs_patch.append(("reflect_mission", r_mission))

    # Check retain_mission in config
    r = subprocess.run(
        ["curl", "-s", f"{bank_api}/config"],
        capture_output=True, text=True, timeout=10
    )
    config = json.loads(r.stdout).get("config", {})
    if not config.get("retain_mission"):
        needs_patch.append(("retain_mission", x_mission))

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


# === DOCUMENT COLLECTION ===
def collect_documents(client_dir, client_key, c, session_dates):
    """Build the list of documents to import.

    Each item: dict(content, document_id, tags, context, timestamp, label).
    """
    docs = []
    client_name = c["client_name"]
    base_tags = [client_key, "source:therapy", c["therapist_tag"]]

    # Session transcripts and notes
    session_dirs = sorted(glob.glob(os.path.join(client_dir, "session-*")))
    for d in session_dirs:
        m = re.search(r"session-(\d+)$", d)
        if not m:
            continue
        n = int(m.group(1))
        ts = iso(session_dates.get(n))

        for kind, fname in (("transcript", "transcript.txt"),
                            ("note", "note.txt")):
            path = os.path.join(d, fname)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content.strip()) < 50:
                continue
            kind_label = "transcript" if kind == "transcript" else "SOAP progress note"
            docs.append({
                "content": content,
                "document_id": f"{client_key}:session-{n:02d}:{kind}",
                "tags": base_tags + [f"session:{n:02d}", f"type:{kind}"],
                "context": f"{client_name} — Therapy Session {n} ({kind_label})",
                "timestamp": ts,
                "label": f"session-{n:02d}/{fname}",
            })

    # Treatment plan
    tp_path = os.path.join(client_dir, "treatment-plan.md")
    if os.path.exists(tp_path):
        with open(tp_path, "r", encoding="utf-8") as f:
            content = f.read()
        docs.append({
            "content": content,
            "document_id": f"{client_key}:treatment-plan",
            "tags": base_tags + ["type:treatment-plan", "session:03"],
            "context": f"{client_name} — Initial Treatment Plan (established session 3)",
            "timestamp": iso(parse_plan_date(tp_path)),
            "label": "treatment-plan.md",
        })

    # Treatment plan update (session 20)
    tpu_path = os.path.join(client_dir, "treatment-plan-update-session-20.md")
    if os.path.exists(tpu_path):
        with open(tpu_path, "r", encoding="utf-8") as f:
            content = f.read()
        docs.append({
            "content": content,
            "document_id": f"{client_key}:treatment-plan-update-20",
            "tags": base_tags + ["type:treatment-plan-update", "session:20"],
            "context": f"{client_name} — Treatment Plan Update (session 20)",
            "timestamp": iso(parse_plan_date(tpu_path)),
            "label": "treatment-plan-update-session-20.md",
        })

    return docs


# === MAIN ===
def main():
    client_key = (sys.argv[1] if len(sys.argv) > 1
                  else os.environ.get("HINDSIGHT_CLIENT", "michael-scott"))

    client_dir = os.path.join(SCRIPT_DIR, client_key)
    if not os.path.isdir(client_dir):
        known = ", ".join(sorted(
            d for d in os.listdir(SCRIPT_DIR)
            if os.path.isdir(os.path.join(SCRIPT_DIR, d, "session-01"))
        )) or "(none found)"
        print(f"ERROR: client directory not found: {client_dir}")
        print(f"Available client directories: {known}")
        sys.exit(1)

    c = client_config(client_key, client_dir)
    c["bank_id"] = os.environ.get("HINDSIGHT_BANK", c["bank_id"])

    outline_path = os.path.join(client_dir, "outline.md")
    if not os.path.exists(outline_path):
        print(f"ERROR: outline.md not found at {outline_path}")
        sys.exit(1)
    session_dates = parse_session_dates(outline_path)
    print(f"Client: {c['client_name']}  |  Clinician: {c['clinician_name']}")
    print(f"Bank: {c['bank_id']}")
    print(f"Loaded {len(session_dates)} session dates from outline.md")

    docs = collect_documents(client_dir, client_key, c, session_dates)
    if not docs:
        print("ERROR: no documents found to import.")
        sys.exit(1)
    print(f"Collected {len(docs)} documents to import")

    bank_api = f"{HINDSIGHT_API}/v1/default/banks/{c['bank_id']}"

    if CREATE_BANK:
        create_bank(bank_api, c)

    # === IMPORT ===
    print(f"\n=== Phase 1: Importing {len(docs)} documents ===")
    imported = 0
    errors = 0
    no_date = 0

    for i, doc in enumerate(docs):
        if doc["timestamp"] == "unset":
            no_date += 1

        payload = {
            "items": [{
                "content": doc["content"],
                "document_id": doc["document_id"],
                "tags": doc["tags"],
                "context": doc["context"],
                "timestamp": doc["timestamp"],
            }],
            "async": True,
        }

        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{bank_api}/memories",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=30
        )

        if r.stdout and '"error"' not in r.stdout.lower():
            imported += 1
        else:
            errors += 1
            if errors <= 10:
                print(f"  ERROR importing {doc['label']}: {r.stdout[:200]}")

        if i > 0 and i % IMPORT_BATCH_DELAY_EVERY == 0:
            time.sleep(IMPORT_DELAY_SECONDS)

    print(f"\n=== Complete ===")
    print(f"Imported: {imported}")
    print(f"Errors: {errors}")
    print(f"No date found (used 'unset'): {no_date}")
    print(f"Total processed: {len(docs)}")

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
        listed = json.loads(r.stdout).get("documents", [])
        for doc in listed[:3]:
            print(f"  {doc.get('document_id', '?')} | "
                  f"tags={doc.get('tags', [])} | ts={doc.get('timestamp', '?')}")
    except json.JSONDecodeError:
        print(f"  (could not parse document list: {r.stdout[:200]})")

    print(f"\nNext steps:")
    print(f"  - Check pending ops: curl -s {bank_api}/operations | python3 -m json.tool")
    print(f"  - Test recall: curl -s -X POST {bank_api}/memories/recall "
          f"-H 'Content-Type: application/json' -d '{{\"query\": \"core belief\"}}'")
    print(f"  - Control Plane UI: check bank '{c['bank_id']}' in the Hindsight UI")


if __name__ == "__main__":
    main()
