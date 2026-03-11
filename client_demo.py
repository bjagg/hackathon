"""Client demo — Entitlement-based access to Portable Learner Memory.

Demonstrates least-privilege grants scoped by entitlement, requester, and duration.
"""

import httpx
import json
import sys
import textwrap

BASE = "http://localhost:8000"
client = httpx.Client(base_url=BASE, timeout=10)

SUBJECT = "learner_maya_2026"
W = 78


def banner(msg):
    print(f"\n{'━'*W}\n  {msg}\n{'━'*W}")


def sub(msg):
    print(f"\n{'─'*W}\n  {msg}\n{'─'*W}")


def indent(text, prefix="  "):
    for line in text.splitlines():
        print(textwrap.fill(line, W, initial_indent=prefix, subsequent_indent=prefix) if line.strip() else "")


def check(resp, expected=200):
    if resp.status_code != expected:
        print(f"  FAIL {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)


def create(doc, heading, kind, content, **kw):
    payload = {
        "document": doc, "heading": heading, "kind": kind, "content": content,
        "declared_by": kw.get("declared_by", "user"),
        "provenance": kw.get("provenance", "explicit_statement"),
        "confidence": kw.get("confidence", 1.0),
        "classification": kw.get("classification", "private"),
    }
    for k in ("source_ref", "evidence_refs"):
        if k in kw:
            payload[k] = kw[k]
    resp = client.post(f"/sections/{SUBJECT}", json=payload)
    check(resp, 201)
    return resp.json()["id"]


def show_doc(doc_type):
    resp = client.get(f"/docs/{SUBJECT}/{doc_type}/markdown")
    check(resp)
    indent(resp.json()["markdown"])


def show_bundle(bundle):
    print(f"\n  Bundle:      {bundle['bundle_id']}")
    print(f"  Entitlement: {bundle['entitlement']}")
    print(f"  Requester:   {bundle['requester']}")
    print(f"  Grant:       {bundle['grant_id']}")
    print(f"  Expires:     {bundle.get('allowed_until', 'N/A')}")
    print(f"  Items:       {len(bundle['items'])}")
    if bundle["redacted_documents"]:
        print(f"  Redacted docs:  {bundle['redacted_documents']}")
    if bundle["redacted_kinds"]:
        print(f"  Redacted kinds: {bundle['redacted_kinds']}")
    print()
    for item in bundle["items"]:
        preview = item["content"][:100].replace("\n", " ")
        print(f"    [{item['document']:8s}] {item['heading'][:42]:42s}  {item['kind']:18s} conf={item['confidence']}")
        print(f"             {preview}...")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 1: Populate learner memory across all 6 documents")
# ═══════════════════════════════════════════════════════════════════════

# --- AGENTS ---
create("AGENTS", "District AI Usage Policy", "policy",
    "Per District 456 AI Usage Policy v2 (effective February 2026): No AI-generated "
    "content may be presented to students as instructional material without prior teacher "
    "review and approval. AI tutoring systems may ask questions and provide hints but must "
    "not generate full explanations or worked solutions autonomously. All AI interactions "
    "must be logged and available for teacher review within 24 hours.",
    declared_by="institution", provenance="district_policy",
    source_ref="district_456_ai_policy_v2", classification="restricted")

create("AGENTS", "Data Sharing Constraints", "constraint",
    "Maya's parent has specified that no learning data may be shared with third-party "
    "tools without explicit per-tool consent. Health-related information (including anxiety "
    "indicators and stress responses) must never be shared outside the primary learning "
    "platform and the school counselor. Assessment raw scores may be shared with authorized "
    "tutoring tools but only in aggregate form, not item-level responses.",
    declared_by="guardian", provenance="parent_data_agreement",
    source_ref="consent_form_2026_01_20", classification="restricted")

create("AGENTS", "Session Interaction Protocol", "policy",
    "When interacting with Maya, AI agents should: (1) Never use language that implies "
    "judgment about intelligence or ability — use growth-oriented framing. (2) Always "
    "offer a hint before revealing an answer. (3) If Maya appears disengaged (response "
    "time > 2 minutes or three consecutive skips), gently suggest a break or topic change "
    "rather than pushing forward. (4) Begin each session by acknowledging where she left "
    "off last time. (5) End each session with a brief summary of what was accomplished.",
    declared_by="tutor", provenance="tutor_guidelines", source_ref="mr_okafor_session_protocol")
print("  AGENTS.md: 3 sections")

# --- SOUL ---
create("SOUL", "Learning Philosophy", "belief",
    "Maya believes that understanding why something works matters more than getting the "
    "right answer quickly. In a goal-setting conversation she said: 'I don't want to just "
    "memorize steps — I want to actually get it.' She has expressed frustration with "
    "platforms that reward speed over understanding, and she gravitates toward tools that "
    "let her explore concepts at her own pace.",
    provenance="student_goal_setting", source_ref="session_2026_03_03_goals")

create("SOUL", "Relationship to Challenge", "trait",
    "Maya has a complicated relationship with difficulty. She genuinely wants to tackle "
    "hard problems and expresses pride when she solves something challenging. However, she "
    "has a low tolerance for sustained confusion — if she cannot make progress within about "
    "90 seconds, her confidence drops quickly. Her tutor describes her as 'brave but brittle' "
    "when it comes to mathematical challenge.",
    declared_by="tutor", provenance="tutor_observation", source_ref="mr_okafor_notes_2026_03")

create("SOUL", "Core Values in Learning", "value",
    "Fairness and effort matter deeply to Maya. She becomes upset when she perceives that "
    "a system is not giving her credit for partial understanding. She has said: 'It's not "
    "fair that I get zero points when I knew most of it.' She values being seen for her "
    "process, not just her product. She also cares about helping others — she voluntarily "
    "explains fraction operations to her study group peers.",
    declared_by="tutor", provenance="classroom_observation", source_ref="teacher_notes_2026_02")
print("  SOUL.md: 3 sections")

# --- IDENTITY ---
create("IDENTITY", "School and Grade", "fact",
    "Maya is an 11-year-old 6th grader at Riverside Middle School in District 456. She "
    "transferred from Oak Park Elementary at the start of the 2025-2026 school year. She "
    "was in the advanced math track at her previous school but has been placed in the "
    "general math track at Riverside due to different placement criteria. Her parent noted "
    "that Maya has an older sibling who struggled with math anxiety.",
    declared_by="guardian", provenance="parent_onboarding", source_ref="onboarding_form_2026_01_15")

create("IDENTITY", "Current Academic Goals", "goal",
    "During a goal-setting conversation on March 3, Maya said she wants to get back into "
    "the advanced math track by next school year. She identified two specific targets: "
    "'I want to be able to do the word problems without getting confused' and 'I want to "
    "understand the fraction stuff with variables.' Her teacher framed these as improving "
    "word-problem translation to 0.75+ and rational expressions to 0.70+ by semester end.",
    provenance="student_goal_setting", source_ref="session_2026_03_03_goals")

create("IDENTITY", "Key Relationships", "relationship",
    "Maya works with tutor Mr. Okafor twice weekly (Tuesdays and Thursdays). She responds "
    "well to his approach of narrating his own problem-solving thinking aloud. She has "
    "expressed reluctance to work with substitute tutors. Maya also participates in a "
    "small peer study group with Aiden and Priya on Fridays, where she often takes on the "
    "role of explaining fraction operations to the others.",
    declared_by="tutor", provenance="tutor_session_notes",
    source_ref="session_2026_03_07_notes", confidence=0.85, classification="restricted")
print("  IDENTITY.md: 3 sections")

# --- USER ---
create("USER", "Learning Modality Preferences", "preference",
    "Maya strongly prefers seeing a fully worked example before attempting a new problem "
    "type. During a March 2 tutoring session she said: 'I need to see how someone else "
    "does it first, then I can try.' She also prefers audiobooks and read-aloud modes — "
    "her reading comprehension scores are approximately 15% higher on passages she listens "
    "to versus reads silently.",
    provenance="tutor_observation", source_ref="session_2026_03_02_tutoring")

create("USER", "Extended Time Accommodation", "accessibility",
    "Maya has a documented accommodation for extended time (1.5x) on all timed activities, "
    "per her IEP updated January 2026. Her parent emphasized that time pressure causes "
    "significant anxiety. The accommodation applies to quizzes, tests, and any timed "
    "practice mode. Countdown timers should not be displayed unless Maya explicitly opts in.",
    declared_by="guardian", provenance="iep_accommodation", source_ref="iep_accommodation_2026_01")

create("USER", "Communication Style", "preference",
    "Maya responds best to warm, encouraging language that acknowledges effort. She shuts "
    "down when feedback feels clinical or evaluative. Effective: 'You're on the right track "
    "— let's look at this one part together.' She has explicitly asked not to be told "
    "'That's easy' or 'You should know this by now.'",
    declared_by="tutor", provenance="tutor_observation", source_ref="mr_okafor_notes_2026_02")
print("  USER.md: 3 sections")

# --- TOOLS ---
create("TOOLS", "Fantasy Academy — AI Tutor", "tool_config",
    "Fantasy Academy is authorized as Maya's primary AI tutoring platform for math, "
    "approved by District 456 on February 10, 2026. Sessions are 30 minutes, Tuesday and "
    "Thursday, following Mr. Okafor's tutoring sessions. The tool should use the session "
    "interaction protocol defined in AGENTS.md. API integration uses OAuth2.",
    declared_by="institution", provenance="district_tool_approval",
    source_ref="tool_approval_2026_02_10", classification="restricted")

create("TOOLS", "MathWorld — Adaptive Practice", "tool_config",
    "MathWorld is authorized for adaptive practice sessions, approved by Maya's parent "
    "on March 1, 2026. The tool adapts difficulty in real-time and should reduce difficulty "
    "immediately upon detecting disengagement. Practice sessions are self-paced with a "
    "recommended 20-minute limit. Parent has requested weekly progress reports.",
    declared_by="guardian", provenance="parent_tool_approval",
    source_ref="parent_consent_2026_03_01", classification="restricted")

create("TOOLS", "Riverside SIS Integration", "integration",
    "Maya's official records are maintained in the Riverside Middle School SIS (PowerSchool). "
    "Grade data, attendance, and formal assessment scores sync nightly. IEP accommodations "
    "are sourced from the SIS and should be treated as authoritative.",
    declared_by="institution", provenance="sis_integration_config",
    source_ref="sis_config_2026_01", classification="restricted")
print("  TOOLS.md: 3 sections")

# --- MEMORY ---
create("MEMORY", "Math Mastery Snapshot — March 2026", "mastery",
    "Based on the March 1 adaptive assessment (42 items, 35 minutes):\n"
    "- Fractions operations: 0.91 — Strong fluency. Minor hesitation on division by mixed numbers.\n"
    "- Linear equations: 0.82 — Solves one- and two-step equations reliably.\n"
    "- Rational expressions: 0.55 — Emerging but inconsistent.\n"
    "- Word problem translation: 0.48 — Difficulty converting narrative to algebraic expressions.",
    declared_by="system", provenance="assessment_result",
    source_ref="assessment_2026_03_01", confidence=0.9, classification="restricted")

error_pattern_id = create("MEMORY", "Error Pattern — Multi-step Word Problems", "error_pattern",
    "Across three recent quizzes and one tutoring session, Maya shows a recurring pattern "
    "with multi-step word problems. She correctly identifies the relevant quantities but "
    "frequently sets up the relationships incorrectly when the problem requires more than "
    "two steps. In quiz 882 she solved 4/5 one-step problems but 1/4 multi-step problems. "
    "She tends to start solving before fully reading the problem.",
    declared_by="system", provenance="derived_from_quiz_history",
    evidence_refs=["quiz_882", "quiz_901", "quiz_915", "session_2026_03_05"],
    confidence=0.72, classification="restricted")

create("MEMORY", "Engagement Cycle Pattern", "inference",
    "Analysis of six recent sessions suggests a consistent engagement cycle. Maya starts "
    "with high energy for 10-12 minutes. Around the 15-minute mark, if she encounters a "
    "problem she cannot solve within 90 seconds, her response rate drops sharply. If she "
    "fails two consecutive problems after the 15-minute mark, she tends to disengage "
    "entirely. Sessions where difficulty was adaptively reduced after the first failure "
    "showed sustained engagement for the full 30 minutes.",
    declared_by="system", provenance="interaction_pattern_analysis",
    evidence_refs=["session_2026_03_02", "session_2026_03_05", "session_2026_03_07",
                   "session_2026_03_09", "quiz_882", "quiz_901"],
    confidence=0.68, classification="restricted")

create("MEMORY", "Session Log — March 9 Tutoring", "interaction_event",
    "March 9 tutoring session with Mr. Okafor (30 min, Fantasy Academy):\n\n"
    "Maya arrived energized and asked to work on word problems. Problem 1 (two-step, total "
    "cost with tax): solved correctly in 45 seconds. Problem 2 (unit conversion in a rate "
    "problem): set up the rate correctly but applied conversion factor backwards; self-"
    "corrected when asked to re-read. Problem 3 (three-step, percentages + fractions): "
    "stopped and said 'I don't even know where to start.' Mr. Okafor broke it into sub-"
    "questions — Maya solved each individually but couldn't reassemble without guidance.\n\n"
    "By problem 5, Maya was identifying sub-steps herself. Mr. Okafor noted: 'The key "
    "unlock was asking her to circle each question the problem is really asking before "
    "she picks up her pencil.'",
    declared_by="system", provenance="session_transcript_summary",
    source_ref="session_2026_03_09", confidence=0.95, classification="restricted")

create("MEMORY", "Session Log — March 7 Peer Study Group", "interaction_event",
    "March 7 study group with Aiden and Priya (25 min, classroom):\n\n"
    "Maya took charge, using a pizza analogy to explain why you can't add fractions with "
    "different denominators directly. She walked Priya through finding the LCD step by "
    "step. Teacher noted Maya's explanation was clearer than the textbook's. Maya solved "
    "3/4 problems correctly but forgot to convert a mixed number before finding the common "
    "denominator. When Priya pointed it out, Maya laughed: 'I always forget that part.' "
    "Teacher noted this as a mechanical gap, not a conceptual one.",
    declared_by="tutor", provenance="teacher_observation",
    source_ref="study_group_2026_03_07", confidence=0.9, classification="restricted")
print("  MEMORY.md: 5 sections")

print(f"\n  Total: 20 sections across 6 documents")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 2: View the entitlements catalog")
# ═══════════════════════════════════════════════════════════════════════

resp = client.get("/entitlements")
check(resp)
catalog = resp.json()

for name, info in catalog.items():
    docs = info["allowed_documents"]
    kinds = info["allowed_kinds"]
    kind_str = ", ".join(kinds) if isinstance(kinds, list) else kinds
    print(f"\n  {name}")
    print(f"    docs:  {docs}")
    print(f"    kinds: {kind_str}")
    indent(info["description"], prefix="    ")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 3: Entitlement-scoped context retrieval")
# ═══════════════════════════════════════════════════════════════════════


# --- Transcript ---
sub("TRANSCRIPT — requesting without a grant (should be denied)")

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "new_school_admin", "entitlement": "transcript",
})
check(resp)
bundle = resp.json()
print(f"\n  Items: {len(bundle['items'])} (no grant = denied)")
print(f"  Grant ID: {bundle['grant_id']}")
print(f"  Redacted docs: {bundle['redacted_documents']}")


sub("TRANSCRIPT — grant for 24 hours, new school admin")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "new_school_admin",
    "entitlement": "transcript",
    "duration_hours": 24,
    "institution": "lincoln_middle_school",
    "justification": "Student transfer enrollment review",
})
check(resp)
grant = resp.json()
print(f"\n  Grant:       {grant['id']}")
print(f"  Entitlement: {grant['entitlement']}")
print(f"  Requester:   {grant['requester']}")
print(f"  Duration:    {grant['duration_hours']}h (remaining: {grant['time_remaining']})")
print(f"  Docs:        {grant['allowed_documents']}")
print(f"  Kinds:       {grant['allowed_kinds']}")
print(f"  Justification: {grant['justification']}")

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "new_school_admin", "entitlement": "transcript",
})
check(resp)
bundle = resp.json()
print(f"\n  TRANSCRIPT bundle — least privilege: only facts, mastery, goals from IDENTITY + MEMORY")
show_bundle(bundle)


# --- Tutoring session ---
sub("TUTORING SESSION — 1 hour grant for Fantasy Academy")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "app_fantasy_academy",
    "entitlement": "tutoring_session",
    "duration_hours": 1,
    "institution": "district_456",
    "justification": "Scheduled Tuesday algebra tutoring",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "app_fantasy_academy", "entitlement": "tutoring_session",
})
check(resp)
bundle = resp.json()
print(f"\n  TUTORING SESSION — preferences, accessibility, mastery, errors, inferences, goals")
show_bundle(bundle)


# --- Adaptive practice (broader) ---
sub("ADAPTIVE PRACTICE — 24h grant for MathWorld (broader than tutoring)")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "app_mathworld",
    "entitlement": "adaptive_practice",
    "duration_hours": 24,
    "justification": "Ongoing adaptive practice — parent approved",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "app_mathworld", "entitlement": "adaptive_practice",
})
check(resp)
bundle = resp.json()
print(f"\n  ADAPTIVE PRACTICE — includes interaction events and AGENTS policies (more than tutoring)")
show_bundle(bundle)


# --- Assessment (very narrow) ---
sub("ASSESSMENT — only accessibility + constraints (no learning data)")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "assessment_platform",
    "entitlement": "assessment",
    "duration_hours": 2,
    "institution": "district_456",
    "justification": "End-of-quarter math assessment",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "assessment_platform", "entitlement": "assessment",
})
check(resp)
bundle = resp.json()
print(f"\n  ASSESSMENT — narrowest entitlement: no mastery, no preferences, no behavioral data")
show_bundle(bundle)


# --- School transfer (broad, time-limited) ---
sub("SCHOOL TRANSFER — 72h grant for new district")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "lincoln_district_sis",
    "entitlement": "school_transfer",
    "duration_hours": 72,
    "institution": "lincoln_unified_district",
    "justification": "Inter-district transfer: placement review and accommodation setup",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "lincoln_district_sis", "entitlement": "school_transfer",
})
check(resp)
bundle = resp.json()
print(f"\n  SCHOOL TRANSFER — identity, mastery, goals, accessibility, constraints, relationships")
show_bundle(bundle)


# --- Parent review (broadest) ---
sub("PARENT REVIEW — full access (inspection right)")

resp = client.post("/grants", json={
    "subject": SUBJECT,
    "requester": "maya_parent",
    "entitlement": "parent_review",
    "duration_hours": 720,
    "justification": "Standing parental inspection right",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "maya_parent", "entitlement": "parent_review",
})
check(resp)
bundle = resp.json()
print(f"\n  PARENT REVIEW — full access to all documents and section kinds")
show_bundle(bundle)


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 4: Compare entitlements side by side")
# ═══════════════════════════════════════════════════════════════════════

entitlements_tested = [
    ("transcript",       "new_school_admin"),
    ("tutoring_session", "app_fantasy_academy"),
    ("adaptive_practice","app_mathworld"),
    ("assessment",       "assessment_platform"),
    ("school_transfer",  "lincoln_district_sis"),
    ("parent_review",    "maya_parent"),
]

print(f"\n  {'Entitlement':<22s} {'Requester':<25s} {'Items':>5s}  {'Redacted Docs'}")
print(f"  {'─'*22} {'─'*25} {'─'*5}  {'─'*30}")
for ent, req in entitlements_tested:
    resp = client.post("/context", json={
        "subject": SUBJECT, "requester": req, "entitlement": ent,
    })
    b = resp.json()
    print(f"  {ent:<22s} {req:<25s} {len(b['items']):>5d}  {b['redacted_documents']}")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 5: Correction, revocation, and audit")
# ═══════════════════════════════════════════════════════════════════════

sub("Parent corrects an inference in MEMORY")

resp = client.get(f"/sections/{SUBJECT}/MEMORY/{error_pattern_id}")
check(resp)
before = resp.json()
print(f"\n  Section: {before['heading']} (v{before['version']}, conf={before['confidence']})")

resp = client.patch(f"/sections/{SUBJECT}/MEMORY/{error_pattern_id}", json={
    "content": (
        "After discussion with Maya and her parent on March 10, the original inference has been "
        "refined. Maya does not struggle with all multi-step word problems — she handles them "
        "well when the steps involve operations she is confident in. The difficulty is specifically "
        "with problems that require unit conversion or translating between representations. Her "
        "parent noted that Maya has always found unit conversion confusing. The tutor confirmed "
        "that when he pre-teaches the conversion step, Maya completes the full problem independently."
    ),
    "confidence": 0.88,
    "correction_reason": "Parent and tutor clarified after reviewing specific problem examples",
})
check(resp)
after = resp.json()
print(f"  Corrected: v{before['version']} -> v{after['version']}, conf {before['confidence']} -> {after['confidence']}")


sub("Revoke transcript grant and verify")

transcript_grants = [g for g in client.get(f"/grants?requester=new_school_admin").json()
                     if g["entitlement"] == "transcript" and not g["revoked"]]
grant_id = transcript_grants[0]["id"]
resp = client.delete(f"/grants/{grant_id}")
check(resp)
print(f"\n  Revoked: {grant_id}")

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "new_school_admin", "entitlement": "transcript",
})
check(resp)
print(f"  Items after revocation: {len(resp.json()['items'])} (expected 0)")


sub("All active grants")

resp = client.get(f"/grants?subject={SUBJECT}")
check(resp)
for g in resp.json():
    status = "REVOKED" if g["revoked"] else ("VALID" if g["valid"] else "EXPIRED")
    print(f"  [{status:7s}] {g['id']} | {g['entitlement']:20s} | {g['requester']:25s} | {g['time_remaining']}")


sub("Audit trail summary")

resp = client.get(f"/audit?subject={SUBJECT}")
check(resp)
entries = resp.json()
from collections import Counter
actions = Counter(e["action"] for e in entries)
print(f"\n  Total entries: {len(entries)}")
for action, count in actions.most_common():
    print(f"    {action:25s} {count}")


banner("DEMO COMPLETE")
print(f"\n  Entitlement-based, least-privilege access verified across 6 use cases.")
print(f"  Same learner data, different entitlements = different access scopes.")
print(f"  Server: {BASE}/docs")
print()
