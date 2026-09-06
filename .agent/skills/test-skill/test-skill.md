---
name: test-skill
description: >-
  Educational template and test skill demonstrating the Antigravity Agent Skill architecture.
  Use when learning how skills work, creating new skills, or testing skill discovery and progressive disclosure.
---

# Test Skill: Antigravity Skill Architecture & Training Guide

This skill serves as a reference implementation and training guide for building modular, high-performance skills in **Google Antigravity**.

---

## 1. What is a Skill?

A **Skill** is a specialized, on-demand package of domain knowledge, procedures, and executable workflows that extends the AI Agent's capabilities.

### Key Characteristics:
* **Progressive Disclosure:** Skills are not loaded into the context window by default. Only the `name` and `description` from the YAML frontmatter are indexed. When the agent detects a task matching the description, it dynamically reads the full `SKILL.md`.
* **Modularity:** Encapsulates domain logic without cluttering the global prompt.
* **Deterministic Workflows:** Provides step-by-step procedures (runbooks) that guide the agent through complex pipelines.

---

## 2. Standard Directory Layout

A complete skill directory is structured as follows:

```text
.agent/skills/test-skill/
├── SKILL.md            # [Required] Entry point with YAML frontmatter & core instructions
├── test-skill.md       # [Optional / Alias] Alternative reference file
├── scripts/            # [Optional] Helper scripts (Bash, PowerShell, Python)
│   ├── run_test.py
│   └── validate_output.py
├── examples/           # [Optional] Input/output examples, sample payloads
│   └── sample_result.json
├── resources/          # [Optional] Static assets, schemas, templates
│   └── output_schema.json
└── references/         # [Optional] Deep-dive docs, manuals (read on-demand)
    └── detailed_guide.md
```

---

## 3. Standard Operating Procedure (SOP) Template

When executing a task governed by this skill, follow these three phases:

### Phase 1: Environment & Input Verification
1. Verify required environment variables and configuration files:
   - Check `config/config.ini` for valid API credentials and parameters.
2. Confirm the presence of input files before initiating long-running processes:
   - Ensure target media files exist in `input/raw/` or `input/artikel/`.

### Phase 2: Execution Workflow
1. **Initialize State:** Create a structured execution record (e.g., timestamped run directory).
2. **Execute Steps Sequentially:**
   ```powershell
   # Example: Run mock verification pipeline
   python main.py --item Artikel_1 --mock
   ```
3. **Handle Errors Proactively:**
   - If an API rate limit (`429`) occurs, apply exponential backoff or toggle fallback models.
   - If a schema parsing error occurs, validate against `resources/output_schema.json`.

### Phase 3: Validation & Reporting
1. Verify that all expected output files exist:
   - Consolidated Excel report (`.xlsx`)
   - Consolidated CSV report (`.csv`)
   - Detailed per-item JSON trace (`06_prompt_2_parsed.json`)
2. Inspect log files for warnings or unhandled exceptions.
3. Report a concise, markdown-formatted summary to the user with direct file links.

---

## 4. Best Practices for Authoring Skills

| Principle | Guideline |
| :--- | :--- |
| **Frontmatter Description** | Write in third-person. Clearly specify **what** the skill does and **trigger conditions** (when to activate). |
| **Keep Main File Lean** | Keep `SKILL.md` under 500 lines. Move large reference tables or extensive API docs into `references/`. |
| **Relative File Links** | Use markdown links (e.g., `[helper](./scripts/run_test.py)`) so the agent can browse related assets. |
| **Deterministic Outputs** | Define explicit JSON schemas or table headers to avoid ambiguous model outputs. |
| **Actionable Verification** | Always include verification commands so the agent can test its own work. |

---

## 5. Quick Test / Verification Command

To test if the environment and pipeline are operational using this skill's pattern:

```powershell
# Quick dry-run test
python main.py --mock --item Artikel_1 --no-sort
```