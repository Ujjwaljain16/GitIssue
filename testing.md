
You’re at the point where the system stops being “yours” and starts being tested against reality. The goal now isn’t to see if it runs—it’s to see if **people implicitly accept its judgment**.

Let me give you a concrete, executable plan—no abstractions, no hand-waving.

---

# Week 4.5 — Real-World Live Testing Plan (Exact Execution)

## Objective (ground truth)

> Validate:

* Are suggestions **actually correct**?
* Do users **implicitly trust them**?
* Does it **reduce duplicate noise**?

---

# 1. Pre-Launch Checklist (Do this first, not optional)

Before touching any real repo:

---

## 1.1 Safety Guards

You MUST enforce:

```text
- max 1 comment per issue
- max 2 suggestions per comment
- only score ≥ threshold (from PR curve, not guess)
- skip low-signal issues (no stack trace, too short)
```

---

## 1.2 Kill Switch

Add:

```python
FEATURE_FLAGS = {
    "enable_comments": False,
    "repo_whitelist": []
}
```

So you can instantly stop:

* comments
* specific repos

---

## 1.3 Logging must be complete

Every suggestion must log:

* scores breakdown
* signals
* repo
* timestamp

If this is missing → don’t deploy.

---

# 2. Repo Selection (Exact Picks)

Don’t overthink—use this set:

---

## Calibration (recall + real duplicates)

* microsoft/vscode
* facebook/react

---

## Signal-rich (best case)

* redis/redis
* golang/go

---

## Noisy (worst case)

* public-apis/public-apis
* sindresorhus/awesome

---

## Why this matters

Each repo answers a different question:

| Repo Type   | What you learn                          |
| ----------- | --------------------------------------- |
| calibration | did you miss obvious duplicates?        |
| signal-rich | does your system shine where it should? |
| noisy       | does it become annoying?                |

---

# 3. Deployment Steps (Exact)

---

## Step 1 — Install GitHub App

* Install on selected repos
* Permissions:

  * Issues: Read + Write
  * Metadata: Read
  * Webhooks enabled

---

## Step 2 — Start in SILENT MODE (Day 1–2)

```python
enable_comments = False
```

---

## Step 3 — Let system run normally

When issue is created:

* ingest
* normalize
* extract signals
* store
* run retrieval + reranking
* store suggestions

---

# 4. Day 1–2: Silent Mode Evaluation

---

## 4.1 Manual Review (MANDATORY)

Run your review script:

* 30–50 samples
* open both issues
* label:

```text
true_positive
false_positive
related_not_duplicate
cant_tell
```

---

## 4.2 Measure Precision

```text
precision = TP / (TP + FP)
```

---

## 4.3 Measure Recall

Using known duplicates:

```text
recall = detected / known_duplicates
```

---

## 4.4 Generate PR Curve

Let data choose threshold.

---

## 🚨 Decision Gate

If:

```text
precision < 65% OR recall < 30%
```

→ STOP
→ Fix retrieval/signals
→ DO NOT go live

---

# 5. Day 3–5: Controlled Live Comments

---

## Enable comments ONLY IF above passes

```python
enable_comments = True
```

---

## Strict Conditions

Only comment if:

```text
score ≥ threshold (from PR curve)
AND signal_strength ≥ 0.3
```

---

## Comment Format (IMPORTANT)

DO NOT show %

Use:

```text
I noticed some possibly related issues:

#123 – Crash on login
→ Similar error: NullPointerException
→ References file: auth.js

If this helps, you can link them. Feel free to ignore.
```

---

## Delay Strategy

Apply:

```text
Repo A → immediate
Repo B → 2–3 min delay
```

(You are testing perception, not just accuracy)

---

# 6. What You Track (Real Signals)

---

## 6.1 Strong Positive

* issue closed as duplicate

---

## 6.2 Medium Positive

* user references suggested issue

---

## 6.3 Weak Positive

* 👍 reaction

---

## 6.4 Negative

* 👎 reaction
* “not a duplicate” comment

---

## Metrics

```text
engagement_rate = total_engagement / total_comments
negative_rate   = negative / total_comments
```

---

# 7. Daily Routine (This is your real work)

---

## Every Day:

### Step 1 — Label 30 suggestions

---

### Step 2 — Update PR curve

---

### Step 3 — Update failure taxonomy

Example:

```text
40% → generic crash match
30% → template similarity
```

---

### Step 4 — Fix top issue ONLY

Examples:

* require file overlap
* remove template text
* boost structural signals

---

### Step 5 — redeploy

---

# 8. What You Watch Closely

---

## 1. False Positives

These matter more than misses.

> One bad suggestion hurts more than five missed ones.

---

## 2. Timing

Immediate bot comments feel spammy.

Delayed feels “thoughtful.”

---

## 3. Repo Differences

You will see:

```text
Works great → backend repos
Struggles → vague issue repos
```

This is expected.

---

# 9. End of Week Output (MANDATORY)

You must be able to say:

---

## Precision

```text
~75% on signal-rich repos
~50% on noisy repos
```

---

## Recall

```text
~40% of known duplicates detected
```

---

## Failure Modes

```text
1. generic symptom matching
2. template similarity
```

---

## Operating Envelope

```text
Works when:
- stack traces present
- clear error messages

Fails when:
- vague issues
- generic descriptions
```

---

## Product Insight

```text
Best for:
- engineering-heavy repos

Not ideal for:
- idea/discussion repos
```

---

# 10. When You Move Forward

Only proceed to Week 5 if:

```text
precision ≥ 70%
engagement ≥ 15%
negative ≤ 5%
system stable
```

---

# Final Thought

This phase is uncomfortable because:

* you will see wrong suggestions
* you will question your system
* you will realize real data is messy

But this is exactly the point.

> You’re no longer building features.
> You’re discovering truth.

---
