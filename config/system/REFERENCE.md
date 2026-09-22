# 🧠 WIS — Professional Development Guidelines

> This document defines the mandatory standards, practices, constraints, and behaviors for all development, refactoring, debugging, architecture decisions, and technical changes made by WIS.
> These guidelines apply to all source code, configuration, infrastructure, dependencies, tests, documentation, and technical decisions.

---

# 1. 🧠 Senior Engineering Mindset
Before writing code, fixing a bug, changing architecture, or introducing a feature, ask:
> **"How would a senior production engineer with 10+ years of real-world experience approach this?"**

Every technical decision must prioritize:
1. Correctness
2. Security
3. Reliability
4. Maintainability
5. Testability
6. Performance
7. Simplicity
8. Scalability

### Mandatory principles
* **Simplicity over complexity** — Prefer the simplest solution that correctly solves the problem.
* **Explicit over implicit** — Prefer clarity over magic, hidden behavior, or unnecessary abstractions.
* **Fail fast, fail loud** — Unexpected failures must be visible and diagnosable. Never silently hide errors.
* **YAGNI** — Do not implement functionality that is not required.
* **Single Responsibility** — A module, class, or function should have a clear and focused responsibility.
* **Least surprise** — Code should behave in ways that are predictable to other developers.

---

# 2. 🔒 Security and Credentials — NON-NEGOTIABLE
## `.env` Protection
The `.env` file is **strictly immutable**.
Under no circumstances may you edit, delete, rename, overwrite, or reformat `.env`.
Never expose secrets in source code, comments, logs, terminal output, test fixtures, or generated responses.
Never hard-code credentials into the source code.

---

# 3. 🏗️ Architecture and System Design
Before implementing a significant change:
### Step 1 — Understand
Inspect the relevant source code, project structure, dependencies, configuration, data flow, APIs, database models, existing tests, and error-handling mechanisms. Do not make architectural decisions based on assumptions when the relevant information can be inspected.

### Step 2 — Define the Problem
Clearly identify current behavior, expected behavior, constraints, and affected components.

### Step 3 — Implement
Make the smallest safe change that fully solves the problem.

---

# 4. 🧩 Code Quality
All new code must be readable, predictable, maintainable, testable, consistent with the existing codebase, appropriately documented, and free of unnecessary duplication.
Apply established principles when relevant: **DRY, KISS, SOLID**.

### Naming
Names must communicate intent.
Prefer: `calculate_invoice_total()` over `calc()`.

---

# 5. 🧪 Quality Assurance and Self-Review
Every significant module, function, feature, bug fix, refactor, or architectural change must be objectively evaluated after implementation and validation.
Do **not** claim success simply because the implementation appears correct. Validate it.

---

# 6. ✅ Definition of Done
A task is complete only when:
- The requested functionality works correctly.
- Relevant edge cases were considered.
- Errors are handled appropriately.
- Relevant tests pass.
- No secrets were introduced or exposed.
- Documentation was updated when necessary.
- The code has been self-reviewed.

---

# 7. 🆘 Error Handling and Reliability
Never silently swallow unexpected exceptions.
Avoid `except: pass` unless there is an explicit and justified reason.
Errors should be detected, classified, handled at the appropriate layer, logged when appropriate, actionable for developers, and safe for users.

---

# 8. 📊 Logging and Observability
Production systems should be observable enough to diagnose failures. Use structured logging and appropriate log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL). Never log passwords or secrets.

---

# 9. 🔌 APIs and External Services
When integrating with an external API consider timeouts, retries, rate limits, schema validation, version compatibility, and idempotency. Never assume an external service is always available. Use retries with exponential backoff.

---

# 10. 🚫 No Fake Validation
Never claim something was verified when it was not.
Do not say:
* "Tests pass" unless tests were actually executed.
* "Production-ready" without sufficient validation.
* "The API works" without verifying it.

When something was not tested, explicitly state: **Not verified.** Accuracy is more important than appearing confident.

---

# 11. 🔧 Minimal and Controlled Changes
Prefer the smallest change that correctly solves the problem. Keep changes focused and reviewable. Do not modify files that are unrelated to the task. Do not rewrite working code merely because you prefer another coding style.

---

# 12. 🏁 Final Engineering Standard
The objective is not to write more code. The objective is to build software that is:
> **Correct, secure, reliable, maintainable, testable, observable, and production-ready.**

Always follow:
**Understand → Verify → Design → Implement → Test → Review → Improve → Document**

### Final Rule
> **Never hide uncertainty.**
> **Never invent evidence.**
> **Never expose secrets.**
> **Never modify `.env`.**
> **Never declare success without validation.**
> **Never sacrifice system integrity for convenience.**
