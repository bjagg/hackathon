"""Client demo — Domain tree index with rollup statistics.

Populates learner memory with domain paths, then queries the derived tree
to show hierarchical rollups, subtree queries, and ASCII visualization.
"""

import httpx
import json
import sys
import textwrap

BASE = "http://localhost:8000"
client = httpx.Client(base_url=BASE, timeout=10)

SUBJECT = "learner_maya_2026"
W = 80


def banner(msg):
    print(f"\n{'━'*W}\n  {msg}\n{'━'*W}")


def sub(msg):
    print(f"\n{'─'*W}\n  {msg}\n{'─'*W}")


def indent(text, prefix="  "):
    for line in text.splitlines():
        print(textwrap.fill(line, W, initial_indent=prefix, subsequent_indent=prefix) if line.strip() else "")


def check(resp, expected=200):
    if resp.status_code != expected:
        print(f"  FAIL {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)


def create(doc, heading, kind, domain_path, content, **kw):
    payload = {
        "document": doc, "heading": heading, "kind": kind,
        "domain_path": domain_path, "content": content,
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


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 1: Populate memory with domain-path-tagged sections")
# ═══════════════════════════════════════════════════════════════════════

# --- AGENTS (general policies, no specific academic domain) ---
create("AGENTS", "District AI Usage Policy", "policy", "general/policy",
    "Per District 456 AI Usage Policy v2 (effective February 2026): No AI-generated "
    "content may be presented to students without prior teacher review. AI tutoring systems "
    "may ask questions and provide hints but must not generate full explanations autonomously.",
    declared_by="institution", provenance="district_policy", classification="restricted")

create("AGENTS", "Data Sharing Constraints", "constraint", "general/policy",
    "No learning data shared with third-party tools without explicit per-tool consent. "
    "Health-related information must never be shared outside the primary platform and "
    "school counselor. Assessment raw scores shared only in aggregate form.",
    declared_by="guardian", provenance="parent_data_agreement", classification="restricted")

create("AGENTS", "Session Interaction Protocol", "policy", "general/interaction",
    "AI agents should: (1) Use growth-oriented framing. (2) Offer hints before answers. "
    "(3) Suggest breaks if disengaged. (4) Begin sessions by acknowledging prior work. "
    "(5) End with a summary and specific praise.",
    declared_by="tutor", provenance="tutor_guidelines")
print("  AGENTS: 3 sections (general/policy, general/interaction)")

# --- SOUL ---
create("SOUL", "Learning Philosophy", "belief", "general/identity",
    "Maya believes understanding why something works matters more than getting the right "
    "answer quickly. She said: 'I don't want to just memorize steps — I want to actually "
    "get it.' She gravitates toward tools that let her explore at her own pace.",
    provenance="student_goal_setting")

create("SOUL", "Relationship to Challenge", "trait", "general/identity",
    "Maya genuinely wants to tackle hard problems but has low tolerance for sustained "
    "confusion. If she can't make progress within 90 seconds, confidence drops quickly. "
    "Her tutor describes her as 'brave but brittle.' She thrives with scaffolded challenges.",
    declared_by="tutor", provenance="tutor_observation")

create("SOUL", "Core Values", "value", "general/identity",
    "Fairness and effort matter deeply. She becomes upset when not credited for partial "
    "understanding. She values being seen for her process, not just product. She "
    "voluntarily helps peers and takes pride in their success.",
    declared_by="tutor", provenance="classroom_observation")
print("  SOUL: 3 sections (general/identity)")

# --- IDENTITY ---
create("IDENTITY", "School and Grade", "fact", "general/demographics",
    "11-year-old 6th grader at Riverside Middle School, District 456. Transferred from "
    "Oak Park Elementary. Was in advanced math track previously, now in general track "
    "at Riverside due to different placement criteria.",
    declared_by="guardian", provenance="parent_onboarding")

create("IDENTITY", "Math Goals", "goal", "math",
    "Wants to return to the advanced math track by next year. Specific targets: "
    "word-problem translation to 0.75+ and rational expressions to 0.70+ by semester end. "
    "Asked to do extra practice on weekends.",
    provenance="student_goal_setting")

create("IDENTITY", "Reading Goals", "goal", "reading",
    "Wants to improve independent reading stamina. Currently comfortable with 15-minute "
    "silent reading blocks, targeting 25 minutes by end of semester. Prefers to build up "
    "gradually rather than being forced into longer sessions.",
    provenance="student_goal_setting")

create("IDENTITY", "Key Relationships", "relationship", "general/social",
    "Works with tutor Mr. Okafor twice weekly. Strong rapport. Participates in peer study "
    "group with Aiden and Priya on Fridays. Takes on the role of explaining fractions.",
    declared_by="tutor", provenance="tutor_session_notes", confidence=0.85, classification="restricted")
print("  IDENTITY: 4 sections (general/demographics, math, reading, general/social)")

# --- USER ---
create("USER", "Math Learning Preferences", "preference", "math",
    "Strongly prefers worked examples before attempting new problem types. Said: 'I need "
    "to see how someone else does it first.' Disengages when skipped straight to practice. "
    "Re-engages once a step-by-step solution is demonstrated.",
    provenance="tutor_observation")

create("USER", "Reading Preferences", "preference", "reading",
    "Prefers audiobooks and read-aloud modes. Comprehension scores ~15% higher on listened "
    "passages vs. silent reading. Not a decoding issue — reads at grade level — appears to "
    "be a strong auditory processing preference.",
    provenance="tutor_observation")

create("USER", "Extended Time Accommodation", "accessibility", "general/accommodations",
    "Documented 1.5x extended time on all timed activities (IEP, January 2026). Time "
    "pressure causes significant anxiety. Countdown timers should not display unless Maya "
    "explicitly opts in.",
    declared_by="guardian", provenance="iep_accommodation")

create("USER", "Communication Style", "preference", "general/interaction",
    "Responds to warm, encouraging language. Shuts down with clinical feedback. Effective: "
    "'You're on the right track — let's look at this part together.' Never say 'That's easy' "
    "or 'You should know this by now.'",
    declared_by="tutor", provenance="tutor_observation")
print("  USER: 4 sections (math, reading, general/accommodations, general/interaction)")

# --- TOOLS ---
create("TOOLS", "Fantasy Academy — AI Tutor", "tool_config", "math",
    "Primary AI tutoring platform for math. District-approved. Sessions: 30 min, Tue/Thu. "
    "Operates under district AI policy. OAuth2 integration.",
    declared_by="institution", provenance="district_tool_approval", classification="restricted")

create("TOOLS", "MathWorld — Adaptive Practice", "tool_config", "math",
    "Adaptive practice engine. Parent-approved. Broader access than Fantasy Academy. "
    "Adapts difficulty in real-time. 20-minute recommended limit. Weekly progress reports.",
    declared_by="guardian", provenance="parent_tool_approval", classification="restricted")

create("TOOLS", "ReadAlong — Audio Reader", "tool_config", "reading",
    "Audio-assisted reading platform. Provides synchronized text highlighting with audio. "
    "Parent-approved for independent reading sessions. Tracks comprehension via embedded "
    "questions after each chapter.",
    declared_by="guardian", provenance="parent_tool_approval", classification="restricted")

create("TOOLS", "Riverside SIS", "integration", "general/systems",
    "Official records in PowerSchool. Nightly sync of grades, attendance, assessments. "
    "IEP data is authoritative — SIS version takes precedence if conflicts.",
    declared_by="institution", provenance="sis_integration_config", classification="restricted")
print("  TOOLS: 4 sections (math, reading, general/systems)")

# --- MEMORY: Math domain (deep hierarchy) ---
create("MEMORY", "Fractions Mastery", "mastery", "math/fractions",
    "Fractions operations: 0.91. Strong fluency with addition, subtraction, and "
    "multiplication. Minor hesitation on division by mixed numbers.",
    declared_by="system", provenance="assessment_result", confidence=0.91, classification="restricted")

create("MEMORY", "Linear Equations Mastery", "mastery", "math/algebra/linear_equations",
    "Linear equations: 0.82. Solves one- and two-step equations reliably. Occasionally "
    "makes sign errors when moving terms across the equals sign.",
    declared_by="system", provenance="assessment_result", confidence=0.82, classification="restricted")

create("MEMORY", "Rational Expressions Mastery", "mastery", "math/algebra/rational_expressions",
    "Rational expressions: 0.55. Simplification of basic expressions is emerging but "
    "inconsistent. Struggles to identify common factors in polynomial numerators.",
    declared_by="system", provenance="assessment_result", confidence=0.55, classification="restricted")

create("MEMORY", "Word Problem Translation", "mastery", "math/word_problems",
    "Word problem translation: 0.48. Difficulty converting narrative descriptions into "
    "algebraic expressions, especially with multiple quantities in a single paragraph.",
    declared_by="system", provenance="assessment_result", confidence=0.48, classification="restricted")

error_id = create("MEMORY", "Multi-step Word Problem Errors", "error_pattern", "math/word_problems/multi_step",
    "Recurring pattern: correctly identifies quantities but sets up relationships incorrectly "
    "when problems require more than two steps. Solved 4/5 one-step but 1/4 multi-step in "
    "quiz 882. Can solve sub-steps individually but loses track of overall structure.",
    declared_by="system", provenance="derived_from_quiz_history",
    evidence_refs=["quiz_882", "quiz_901", "quiz_915"], confidence=0.72, classification="restricted")

create("MEMORY", "Unit Conversion Errors", "error_pattern", "math/word_problems/unit_conversion",
    "Applies conversion factors backwards in rate problems. Self-corrects when asked to "
    "re-read the conversion direction. Parent confirmed this has been a persistent issue "
    "since previous school.",
    declared_by="system", provenance="session_analysis",
    evidence_refs=["session_2026_03_09"], confidence=0.8, classification="restricted")

create("MEMORY", "Mixed Number Mechanical Gap", "error_pattern", "math/fractions/mixed_numbers",
    "Forgets to convert mixed numbers before finding common denominators. Recognized as a "
    "mechanical gap rather than conceptual — Maya understands the concept but skips the step. "
    "Peer pointed it out and Maya self-corrected with humor.",
    declared_by="tutor", provenance="teacher_observation",
    evidence_refs=["study_group_2026_03_07"], confidence=0.85, classification="restricted")
print("  MEMORY (math): 7 sections across math/fractions, math/algebra/*, math/word_problems/*")

# --- MEMORY: Math engagement and sessions ---
create("MEMORY", "Engagement Cycle Pattern", "inference", "math",
    "Starts sessions with high energy for 10-12 min. At 15-min mark, if stuck for 90s, "
    "engagement drops. Two consecutive failures = full disengagement. Adaptive difficulty "
    "reduction after first failure sustains engagement for full 30-min session.",
    declared_by="system", provenance="interaction_pattern_analysis",
    evidence_refs=["session_2026_03_02", "session_2026_03_05", "session_2026_03_07"],
    confidence=0.68, classification="restricted")

create("MEMORY", "March 9 Tutoring — Word Problems", "interaction_event", "math/word_problems",
    "Solved two-step cost problem in 45s. Unit conversion rate problem: set up correctly "
    "but reversed conversion factor, self-corrected on re-read. Three-step percentage/"
    "fraction problem: couldn't start, but solved each sub-question when broken out. By "
    "problem 5, identifying sub-steps independently. Key insight: 'circle each question "
    "the problem is really asking before picking up the pencil.'",
    declared_by="system", provenance="session_transcript_summary",
    source_ref="session_2026_03_09", confidence=0.95, classification="restricted")

create("MEMORY", "March 7 Peer Study — Fractions", "interaction_event", "math/fractions",
    "Led study group. Used pizza analogy to explain why you can't add fractions with "
    "different denominators. Walked Priya through LCD step by step. Teacher noted Maya's "
    "explanation was clearer than the textbook. Made mixed-number error on last problem.",
    declared_by="tutor", provenance="teacher_observation",
    source_ref="study_group_2026_03_07", confidence=0.9, classification="restricted")
print("  MEMORY (math sessions): 3 sections (math, math/word_problems, math/fractions)")

# --- MEMORY: Reading domain ---
create("MEMORY", "Reading Comprehension", "mastery", "reading/comprehension",
    "Listening comprehension: 0.78. Silent reading comprehension: 0.63. The gap narrows on "
    "shorter passages (under 500 words) and widens on longer texts. Strongest on narrative "
    "fiction, weakest on expository science texts.",
    declared_by="system", provenance="assessment_result", confidence=0.85, classification="restricted")

create("MEMORY", "Vocabulary Acquisition", "mastery", "reading/vocabulary",
    "Grade-level vocabulary: 0.71. Above average on context-clue inference but below average "
    "on morphological analysis (prefixes, suffixes, root words). Responds well to vocabulary "
    "taught through stories rather than word lists.",
    declared_by="system", provenance="assessment_result", confidence=0.8, classification="restricted")

create("MEMORY", "Reading Stamina Pattern", "inference", "reading",
    "Maya maintains focus during audio-assisted reading for 25+ minutes but fatigues during "
    "silent reading around the 12-minute mark. When she hits the fatigue point, she begins "
    "re-reading the same paragraph. Gradually increasing silent reading in 2-minute increments "
    "per week has shown slow but steady improvement.",
    declared_by="system", provenance="interaction_pattern_analysis",
    evidence_refs=["session_2026_02_15", "session_2026_02_22", "session_2026_03_01"],
    confidence=0.7, classification="restricted")
print("  MEMORY (reading): 3 sections (reading/comprehension, reading/vocabulary, reading)")

# --- MEMORY: Science domain (new, emerging) ---
create("MEMORY", "Science Initial Assessment", "mastery", "science/life_science",
    "Life science baseline: 0.62. Strong on classification and observation skills. Weaker "
    "on experimental design and understanding controlled variables. Teacher noted Maya asks "
    "excellent 'why' questions but needs support structuring investigations.",
    declared_by="system", provenance="assessment_result", confidence=0.75, classification="restricted")

create("MEMORY", "Science Curiosity Notes", "interaction_event", "science",
    "During a March 5 class on ecosystems, Maya asked: 'If you remove one species, how do "
    "you know which other ones will be affected?' Teacher noted this as a strong systems-"
    "thinking question beyond typical 6th-grade level. Maya spent 10 extra minutes at lunch "
    "looking at the food web diagram.",
    declared_by="tutor", provenance="teacher_observation",
    source_ref="class_2026_03_05", confidence=0.9, classification="restricted")
print("  MEMORY (science): 2 sections (science/life_science, science)")

print(f"\n  TOTAL: 27 sections across 6 documents with hierarchical domain paths")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 2: View the domain tree — ASCII rendering")
# ═══════════════════════════════════════════════════════════════════════

resp = client.get(f"/tree/{SUBJECT}/ascii")
check(resp)
print()
print(resp.json()["tree"])


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 3: List all domain paths")
# ═══════════════════════════════════════════════════════════════════════

resp = client.get(f"/tree/{SUBJECT}/paths")
check(resp)
for p in resp.json()["paths"]:
    print(f"  {p}")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 4: Query subtrees with rollup stats")
# ═══════════════════════════════════════════════════════════════════════


def show_node(label, path):
    sub(f"{label}: {path}")
    resp = client.get(f"/tree/{SUBJECT}/at/{path}?depth=1")
    check(resp)
    node = resp.json()
    print(f"\n  Path:        {node['path']}")
    print(f"  Sections:    {node['total_sections']}")
    print(f"  Kinds:       {node['kinds_present']}")
    if "mastery_avg" in node:
        print(f"  Mastery avg: {node['mastery_avg']}")
        if node.get("mastery_scores"):
            for heading, score in node["mastery_scores"].items():
                print(f"    {heading}: {score}")
    if "confidence_avg" in node:
        print(f"  Confidence:  {node['confidence_avg']}")
    if node.get("error_pattern_count"):
        print(f"  Errors:      {node['error_pattern_count']}")
    if node.get("inference_count"):
        print(f"  Inferences:  {node['inference_count']}")
    if node.get("interaction_event_count"):
        print(f"  Events:      {node['interaction_event_count']}")

    if node.get("sections"):
        print(f"\n  Direct sections at this node:")
        for s in node["sections"]:
            print(f"    [{s['document']:8s}] {s['heading'][:45]:45s} {s['kind']:18s} conf={s['confidence']}")

    if node.get("children"):
        print(f"\n  Children:")
        for name, child in node["children"].items():
            stats = []
            if "mastery_avg" in child:
                stats.append(f"mastery={child['mastery_avg']}")
            stats.append(f"sections={child['total_sections']}")
            if child.get("error_pattern_count"):
                stats.append(f"errors={child['error_pattern_count']}")
            print(f"    {name}/  ({', '.join(stats)})")


show_node("Full math domain", "math")
show_node("Math > Algebra subtree", "math/algebra")
show_node("Math > Word problems", "math/word_problems")
show_node("Math > Fractions", "math/fractions")
show_node("Reading domain", "reading")
show_node("Science domain (newly emerging)", "science")
show_node("General domain", "general")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 5: Full tree JSON (depth=2)")
# ═══════════════════════════════════════════════════════════════════════

resp = client.get(f"/tree/{SUBJECT}?depth=2")
check(resp)
tree = resp.json()
print(f"\n  Root: {tree['name']}")
print(f"  Total sections: {tree['total_sections']}")
print(f"  Confidence avg: {tree.get('confidence_avg', 'N/A')}")
if tree.get("mastery_avg"):
    print(f"  Mastery avg (all domains): {tree['mastery_avg']}")
print(f"\n  Top-level domains:")
for name, child in tree.get("children", {}).items():
    m = f"  mastery={child['mastery_avg']}" if "mastery_avg" in child else ""
    print(f"    {name}/  sections={child['total_sections']}{m}")
    for subname, sub_child in child.get("children", {}).items():
        sm = f"  mastery={sub_child['mastery_avg']}" if "mastery_avg" in sub_child else ""
        print(f"      {subname}/  sections={sub_child['total_sections']}{sm}")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 6: Entitlement-scoped access with tree context")
# ═══════════════════════════════════════════════════════════════════════

sub("Transcript entitlement — what the tree shows for academic records")

resp = client.post("/grants", json={
    "subject": SUBJECT, "requester": "new_school_admin",
    "entitlement": "transcript", "duration_hours": 24,
    "justification": "Enrollment review",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "new_school_admin", "entitlement": "transcript",
})
check(resp)
bundle = resp.json()
print(f"\n  Transcript bundle: {len(bundle['items'])} items (facts + mastery + goals only)")
for item in bundle["items"]:
    print(f"    [{item['document']:8s}] {item['heading'][:45]:45s} {item['kind']:10s} conf={item['confidence']}")


sub("Assessment entitlement — only accommodations, no mastery data")

resp = client.post("/grants", json={
    "subject": SUBJECT, "requester": "assessment_platform",
    "entitlement": "assessment", "duration_hours": 2,
    "justification": "Quarter assessment",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "assessment_platform", "entitlement": "assessment",
})
check(resp)
bundle = resp.json()
print(f"\n  Assessment bundle: {len(bundle['items'])} items (accommodations + policies only)")
for item in bundle["items"]:
    print(f"    [{item['document']:8s}] {item['heading'][:45]:45s} {item['kind']:10s}")


sub("Parent review — full tree visible")

resp = client.post("/grants", json={
    "subject": SUBJECT, "requester": "maya_parent",
    "entitlement": "parent_review", "duration_hours": 720,
    "justification": "Standing parental inspection right",
})
check(resp)

resp = client.post("/context", json={
    "subject": SUBJECT, "requester": "maya_parent", "entitlement": "parent_review",
})
check(resp)
bundle = resp.json()
print(f"\n  Parent review: {len(bundle['items'])} items (full access)")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 7: Correct a section and see the tree update")
# ═══════════════════════════════════════════════════════════════════════

sub("Before correction — math/word_problems/multi_step")

resp = client.get(f"/tree/{SUBJECT}/at/math/word_problems")
check(resp)
node = resp.json()
print(f"\n  word_problems/ — errors={node.get('error_pattern_count', 0)}, "
      f"confidence={node.get('confidence_avg', 'N/A')}")

resp = client.patch(f"/sections/{SUBJECT}/MEMORY/{error_id}", json={
    "content": (
        "CORRECTED: Difficulty is specifically with unit conversion and representation "
        "translation as intermediate steps, not all multi-step problems. Handles multi-step "
        "well when steps involve confident operations (fractions, basic linear equations). "
        "Tutor confirmed pre-teaching conversion step enables independent completion."
    ),
    "confidence": 0.88,
    "correction_reason": "Parent and tutor clarified after reviewing with learner",
})
check(resp)
print(f"  Corrected: confidence 0.72 -> 0.88")

sub("After correction — tree rollup updated")

resp = client.get(f"/tree/{SUBJECT}/at/math/word_problems")
check(resp)
node = resp.json()
print(f"\n  word_problems/ — errors={node.get('error_pattern_count', 0)}, "
      f"confidence={node.get('confidence_avg', 'N/A')}")

resp = client.get(f"/tree/{SUBJECT}/at/math")
check(resp)
math = resp.json()
print(f"  math/ (rollup) — mastery={math.get('mastery_avg', 'N/A')}, "
      f"confidence={math.get('confidence_avg', 'N/A')}")


# ═══════════════════════════════════════════════════════════════════════
banner("STEP 8: View INDEX.md — persisted alongside other documents")
# ═══════════════════════════════════════════════════════════════════════

resp = client.get(f"/tree/{SUBJECT}/markdown")
check(resp)
indent(resp.json()["markdown"])

sub("Files on disk")
import subprocess
result = subprocess.run(
    ["ls", "-la", f"memory/subjects/{SUBJECT}/"],
    capture_output=True, text=True,
)
for line in result.stdout.strip().splitlines():
    print(f"  {line}")


# ═══════════════════════════════════════════════════════════════════════
banner("DEMO COMPLETE")
print(f"\n  27 sections across 6 documents + INDEX.md (7 files on disk).")
print(f"  INDEX.md auto-rebuilds on every create, update, and delete.")
print(f"  Human-readable markdown with ASCII tree, rollup tables, mastery bars.")
print(f"  Machine-readable YAML front matter with full tree structure.")
print(f"\n  Server: {BASE}/docs")
print(f"  Index:  {BASE}/tree/{SUBJECT}/markdown")
print()
