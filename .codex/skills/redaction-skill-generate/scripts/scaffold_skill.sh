#!/usr/bin/env bash
# Scaffold a redaction function-point skill in .cursor/skills and .codex/skills.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scaffold_skill.sh --name redaction-foo-bar --phase ocr-text \
  --title "Foo Bar" --display-name "Foo Bar" \
  --capability "one-line capability" --trigger "when the user asks ..."

Required:
  --name          Skill slug (must start with redaction-)
  --phase         Phase id from reference/phases.md (infra, ocr-text, visual, ...)
  --title         H1 title in SKILL.md
  --display-name  agents/openai.yaml display_name
  --capability    One-line capability for description and Capability section
  --trigger       WHEN clause for description (after "Use when the user asks")

Optional:
  --short-description   openai.yaml short_description (defaults to capability)
  --default-prompt-action  Verb phrase for default_prompt (defaults to capability)
  --dry-run             Print paths only, do not write files
EOF
}

ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
NAME=""
PHASE=""
TITLE=""
DISPLAY_NAME=""
CAPABILITY=""
TRIGGER=""
SHORT_DESC=""
PROMPT_ACTION=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --phase) PHASE="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    --display-name) DISPLAY_NAME="$2"; shift 2 ;;
    --capability) CAPABILITY="$2"; shift 2 ;;
    --trigger) TRIGGER="$2"; shift 2 ;;
    --short-description) SHORT_DESC="$2"; shift 2 ;;
    --default-prompt-action) PROMPT_ACTION="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$NAME" || -z "$PHASE" || -z "$TITLE" || -z "$DISPLAY_NAME" || -z "$CAPABILITY" || -z "$TRIGGER" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

if [[ "$NAME" != redaction-* ]]; then
  echo "Skill name must start with redaction-" >&2
  exit 1
fi

SHORT_DESC="${SHORT_DESC:-$CAPABILITY}"
PROMPT_ACTION="${PROMPT_ACTION:-$CAPABILITY}"

PHASES_FILE="$ROOT/.cursor/skills/redaction-skill-generate/reference/phases.md"

if ! grep -qF "$PHASE" "$PHASES_FILE"; then
  echo "Unknown phase id: $PHASE (see reference/phases.md)" >&2
  exit 1
fi

PHASE_LABEL="$(awk -F'|' -v p="$PHASE" '{
  gsub(/`/, "", $3); gsub(/^ +| +$/, "", $3)
  if ($3 == p) { gsub(/^ +| +$/, "", $4); print $4; exit }
}' "$PHASES_FILE")"

skill_md() {
  cat <<EOF
---
name: $NAME
description: Functional skill for $CAPABILITY. Use when the user asks $TRIGGER.
---

# $TITLE

## Pipeline phase

- Phase: $PHASE — $PHASE_LABEL
- Upstream: (fill in \$redaction-... skills or entry inputs)
- Downstream: (fill in \$redaction-... skills or consumers)

## Capability

$CAPABILITY

## Input And Output

- Input: (fill in)
- Output: (fill in)

## Project Entry Points

- (fill in API paths, services, frontend modules)

## Rules

- Stop at this phase boundary; defer upstream/downstream work to linked skills.
- (add skill-specific rules)

## Related skills

- (list \$redaction-... neighbors)
EOF
}

openai_yaml() {
  cat <<EOF
interface:
  display_name: "$DISPLAY_NAME"
  short_description: "$SHORT_DESC"
  default_prompt: "Use \$$NAME to $PROMPT_ACTION."
EOF
}

write_tree() {
  local base="$1"
  local skill_dir="$base/$NAME"
  local agents_dir="$skill_dir/agents"

  if [[ $DRY_RUN -eq 1 ]]; then
    echo "Would create: $skill_dir/SKILL.md"
    echo "Would create: $agents_dir/openai.yaml"
    return
  fi

  if [[ -e "$skill_dir/SKILL.md" ]]; then
    echo "Refusing to overwrite existing skill: $skill_dir" >&2
    exit 1
  fi

  mkdir -p "$agents_dir"
  skill_md > "$skill_dir/SKILL.md"
  openai_yaml > "$agents_dir/openai.yaml"
  echo "Created $skill_dir"
}

write_tree "$ROOT/.cursor/skills"
write_tree "$ROOT/.codex/skills"

if [[ $DRY_RUN -eq 0 ]]; then
  echo "Next: edit SKILL.md entry points and rules; add skill to reference/phases.md and redaction-function-skills.mdc"
fi
