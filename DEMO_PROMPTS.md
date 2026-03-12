# Demo Prompts for Chat UI

Sample prompts for the hackathon presentation. Each section demonstrates a different platform capability.

**URL:** `http://localhost:8000/chat/ui`
**User:** `student_maya` (default)

---

## 1. Memory-Grounded Progress Review

Shows: governed retrieval, memory context sidebar, scores from Canvas ingestion

```
What do you know about my math progress this semester?
```

What to point out:
- Sidebar shows 5-6 memory chunks with similarity scores
- Response cites specific scores (95, 78, 88) from ingested Canvas data
- Identifies struggle areas from Slack conversations

---

## 2. Learning Breakthrough (Memory Admission)

Shows: new memory creation from chat, episodic memory type

```
I think I finally understood how to set up word problems as equations! You break down what you know and what you need to find.
```

What to point out:
- "New Memories" panel lights up with episodic entry
- Claude references previous struggle with word problems
- This insight persists for future sessions

---

## 3. Test Preparation (Multi-Turn Context)

Shows: session continuity, personalized study advice

```
Can you help me prepare for my upcoming algebra test? What should I focus on?
```

What to point out:
- Claude references the word problem breakthrough from earlier in conversation
- Suggests reviewing the 78/88 scored assignments specifically
- Tailors advice to what memory knows about this learner

---

## 4. Cross-Source Knowledge

Shows: data from multiple source systems (Canvas + Slack)

```
What have I been discussing in my study group lately?
```

---

## 5. Privacy Boundary Demo

Shows: sensitivity filtering, governance controls

First, change sensitivity dropdown to **Sensitive**, then:

```
Show me everything you know about my learning history
```

What to point out:
- More chunks appear when sensitivity is raised
- Sensitive memories (DMs, struggles) now included
- Switch back to Normal — sensitive chunks disappear

---

## 6. Goal Setting (Creates Durable Memory)

Shows: memory admission for learning goals

```
I want to set a goal: I'm going to score at least 90 on my next algebra test by practicing word problems every day
```

What to point out:
- New memory created with goal context
- This goal will be retrievable in future sessions

---

## 7. Tutor Perspective (Switch User)

Shows: entitlement-based access control

Change User ID to `tutor_sarah`, then:

```
How is Maya doing in her math class? What should I focus on in our next session?
```

What to point out:
- Tutor only sees chunks they're entitled to via entitlements
- No access to private/sensitive student memories
- Still gets useful overview from shared/project-scope data

---

## Presentation Flow (Recommended Order)

1. **Start fresh** — click "New Session"
2. **Prompt 1** — progress review (shows retrieval + memory context)
3. **Prompt 2** — breakthrough moment (shows memory creation)
4. **Prompt 3** — test prep (shows multi-turn + personalization)
5. **Switch to Entitlements UI** — show the access control that governs all this
6. **Back to Chat** — Prompt 7 as tutor (shows entitlement filtering)

---

## Quick API Demos (Terminal)

```bash
# Pipeline status
curl -s http://localhost:8000/pipeline/status | python3 -m json.tool

# Ingest a new interaction
curl -s -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_system":"canvas","source_id":"demo_1","user_id":"student_maya","event_type":"quiz_submission","actor":"student_maya","content":"Maya scored 91% on linear equations quiz","timestamp":"2026-03-12T16:00:00Z","metadata":{"score":"91","topic":"linear_equations"}}'

# Governed query (tutor can only see what entitlements allow)
curl -s -X POST "http://localhost:8000/query?query=math+scores&user_id=student_maya&reader_id=tutor_sarah&max_results=3"

# LIF student record lookup
curl -s http://localhost:8000/lif/person/100005 | python3 -m json.tool
```
