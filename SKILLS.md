# Skill Runtime

OpenAgent supports OpenCode-style native skills: reusable instruction packages declared as `SKILL.md`, discovered from known directories, advertised to the model by name and description, and loaded lazily through the unified `skill` tool.

## Directory Rules

Project-level roots:

- `.opencode/skill/**/SKILL.md`
- `.opencode/skills/**/SKILL.md`
- `.claude/skills/**/SKILL.md`
- `.agents/skills/**/SKILL.md`

Global roots:

- `~/.opencode/skill/**/SKILL.md`
- `~/.opencode/skills/**/SKILL.md`
- `~/.config/opencode/skill/**/SKILL.md`
- `~/.config/opencode/skills/**/SKILL.md`
- `~/.claude/skills/**/SKILL.md`
- `~/.agents/skills/**/SKILL.md`
- `~/.codex/skills/**/SKILL.md`

Additional roots:

- `OPENAGENT_SKILL_PATHS=/path/a:/path/b`

Relative paths in a skill body are resolved relative to the directory containing that skill's `SKILL.md`.

## `SKILL.md` Structure

Minimum valid file:

```markdown
---
name: python-review
description: Use when reviewing Python code for correctness, tests, typing, and maintainability.
---

# Python Review

Review the target files, then report findings by severity.
```

Required frontmatter:

- `name`
- `description`

Optional frontmatter:

- `compatibility`
- `license`
- `metadata`

Unknown frontmatter fields are ignored by the current runtime. They are not injected as instructions.

## Name Rules

`name` must match:

```text
^[a-z0-9][a-z0-9._-]{0,63}$
```

Valid:

- `python-review`
- `openai-docs`
- `skill_creator`
- `docs.v1`

Invalid:

- `PythonReview`
- `bad skill`
- `-leading-dash`
- names longer than 64 characters

## Description Rules

The description is the main discovery and trigger signal shown to the agent before the full skill body is loaded. Write it as a concise "when to use" sentence:

- Good: `Use when the user asks to review Python code for correctness, tests, typing, and maintainability.`
- Bad: `Python stuff.`

## Body Rules

Keep the body focused on workflow and constraints. Put large material outside the main file:

- `references/` for detailed docs intended to be loaded only when needed
- `scripts/` for executable helpers
- `assets/` for templates, images, and other output resources

The body should not include unrelated long documents or secrets.

## Discovery And Injection

OpenAgent does not inject every skill body at startup. The runtime:

1. Discovers and validates `SKILL.md` files.
2. Adds only available skill names and descriptions to the agent prompt.
3. Scores available skills against the active agent profile and current user task.
4. Loads high-confidence selected skill content into the current turn's system prompt.
5. Allows the model to explicitly load any remaining visible skill through the unified `skill` tool.

This keeps context usage bounded and explains why a skill is visible: it was discovered, valid, and not denied by permission rules.

Selection uses metadata only before loading:

- `name`
- `description`
- `metadata`
- `compatibility`
- active agent name / description / prompt
- current user text

The selector records reasons such as `skill-name-mentioned`, `description-overlap`, `phrase-match`, or domain-specific hints like `openai-task`.

## Permissions

Skills use the `skill` permission namespace. The pattern is the skill name.

Examples:

- allow all: `permission=skill pattern=* action=allow`
- deny one: `permission=skill pattern=openai-docs action=deny`
- deny a family: `permission=skill pattern=internal-* action=deny`

Denied skills are:

- omitted from `/skills`
- omitted from prompt skill summaries
- blocked by `/skill <name>` and the `skill` tool

YOLO mode only auto-approves ask-class permissions. Explicit skill denies still apply.

## Error Handling

Discovery reports, but does not crash on:

- missing frontmatter
- missing `name` or `description`
- invalid `name`
- empty body
- duplicate skill names
- unreadable paths

Duplicate skill names are reported; the later discovered skill replaces the earlier one.

## Migration Notes

OpenAgent scans OpenCode `.opencode/{skill,skills}` directories and compatible `.claude/skills`, `.agents/skills`, and `~/.codex/skills` directories. Existing Codex/Claude-style skills can usually be reused if their `SKILL.md` has valid frontmatter with `name` and `description`.

## CLI Checks

```bash
openagent --skills
openagent --skill openai-docs
OPENAGENT_SKILL_PATHS=/tmp/my-skills openagent --skills
```

Interactive:

```text
/skills
/skill openai-docs
```

Runtime selection is model-driven. OpenAgent shows visible skill names and descriptions in the system prompt, but it does not deterministically select or inject a skill body. The model must call the unified `skill` tool when it decides that a listed skill matches the current task.
