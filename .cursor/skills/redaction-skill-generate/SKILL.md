---
name: redaction-skill-generate
description: Meta skill for authoring new RedactionEverything function-point skills in pipeline phases, scaffolding SKILL.md and agents/openai.yaml, and syncing .cursor/skills with .codex/skills. Use when the user asks to create, scaffold, or extend redaction agent skills by stage or phase.
---

# Redaction Skill Generate

## When to use

Create or extend a **single function-point skill** aligned with one pipeline phase. Do not dump the whole pipeline into one skill.

## Authoring workflow (four steps)

Copy and track:

```
Skill authoring:
- [ ] Step 1 Discover — pick phase and boundary
- [ ] Step 2 Design — name, description, I/O, neighbors
- [ ] Step 3 Implement — scaffold and fill entry points
- [ ] Step 4 Verify — sync trees, update index, sanity check
```

### Step 1 Discover

1. Read [reference/phases.md](reference/phases.md) and pick exactly one phase id.
2. Confirm the capability is not already covered by an existing `$redaction-...` skill.
3. Define what this skill **does not** do (upstream/downstream boundaries).

### Step 2 Design

1. Skill slug: `redaction-<verb>-<noun>` (lowercase, hyphens, max 64 chars).
2. Description (third person): `Functional skill for ... Use when the user asks ...`
3. List upstream inputs, downstream consumers, and related `$redaction-...` skills.
4. Identify real code entry points in `backend/`, `frontend/` before writing prose.

### Step 3 Implement

**Option A — scaffold script (preferred for new skills)**

```bash
.cursor/skills/redaction-skill-generate/scripts/scaffold_skill.sh \
  --name redaction-example-capability \
  --phase ocr-text \
  --title "Example Capability" \
  --display-name "Example Capability" \
  --capability "doing one bounded thing in the OCR/text phase" \
  --trigger "to inspect or debug that one OCR/text step"
```

Then edit generated files:

- Fill `## Project Entry Points`, `## Rules`, pipeline upstream/downstream.
- Remove placeholder parentheses in scaffold output.

**Option B — manual**

Copy [templates/SKILL.md.template](templates/SKILL.md.template) and [templates/openai.yaml.template](templates/openai.yaml.template).

Write to **both**:

- `.cursor/skills/<name>/`
- `.codex/skills/<name>/`

Keep `SKILL.md` byte-identical in both trees.

### Step 4 Verify

1. `name` in frontmatter matches folder name and `$redaction-...` invocation.
2. Description includes WHAT and WHEN; body stays under 500 lines.
3. Phase section matches [reference/phases.md](reference/phases.md).
4. Add the skill to the phase table in `reference/phases.md`.
5. Add the skill under the correct phase in `.cursor/rules/redaction-function-skills.mdc`.
6. If the skill changes an orchestration chain, update `redaction-anonymize-image-flow` or the relevant flow skill.

## SKILL.md section contract

Match existing function-point skills:

| Section | Required |
|---------|----------|
| YAML `name`, `description` | Yes |
| `# Title` | Yes |
| `## Pipeline phase` | Yes for new skills |
| `## Capability` | Yes |
| `## Input And Output` | Yes |
| `## Project Entry Points` | Yes — real paths/functions |
| `## Rules` | Yes — boundaries and constraints |
| `## Related skills` or `## Use Smaller Skills In Order` | When orchestrating or neighboring |

## Phase → typical entry-point areas

| Phase | Start search here |
|-------|-------------------|
| `infra` | `backend/app/core/health_checks.py`, presets APIs, `backend/app/api/` |
| `ocr-text` | `backend/app/services/vision/ocr_pipeline.py`, `ocr_service.py`, NER services |
| `visual` | `backend/app/services/vision_service.py`, visual/locate modules |
| `region-merge` | `redaction_orchestrator.py`, region merge helpers |
| `mask-plan` | `redaction_orchestrator.py`, `redactor.py`, `replacement_strategy.py` |
| `render` | `backend/app/services/redaction/image_redactor.py`, PDF/DOCX redactors |
| `audit` | report builders, version/compare endpoints |
| `batch` | `backend/app/api/jobs.py`, batch workers |
| `structured` | `backend/app/services/structured_service.py`, structured APIs |
| `ui` | `frontend/src/components/ImageBBoxEditor.tsx`, playground features |
| `orchestration` | flow APIs, orchestrator, playground wiring |

## Anti-patterns

- One skill spanning multiple phases (e.g. OCR + NER + render).
- Skills without real file paths — always grep the codebase first.
- Updating only `.cursor/skills` or only `.codex/skills`.
- Orchestration skills that duplicate child skill rules instead of linking `$redaction-...`.

## Additional resources

- Business workflow map: [workflows.md](workflows.md)
- Excel stage table: run `scripts/generate_skill_workflows_excel.py` → `docs/redaction-skill-workflows.xlsx`
- Technical phase map: [phases.md](reference/phases.md)
- Templates: [templates/](templates/)
- Cursor skill authoring basics: user skill `create-skill` when format questions arise
