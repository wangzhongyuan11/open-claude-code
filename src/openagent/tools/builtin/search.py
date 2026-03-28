from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from pathlib import PurePosixPath

from openagent.domain.tools import ToolContext, ToolExecutionResult, ToolOutputLimits
from openagent.tools.base import BaseTool
from openagent.tools.builtin.files import IGNORED_TOP_LEVEL_NAMES, resolve_workspace_path


def _iter_workspace_files(workspace: Path, pattern: str | None = None) -> list[Path]:
    paths: list[Path] = []
    normalized_pattern = _normalize_workspace_glob(workspace, pattern) if pattern else None
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if any(part in IGNORED_TOP_LEVEL_NAMES for part in relative.parts):
            continue
        if normalized_pattern and not _matches_glob(relative, normalized_pattern):
            continue
        paths.append(path)
    return paths


def _normalize_workspace_glob(workspace: Path, pattern: str | None) -> str | None:
    if not pattern:
        return pattern
    candidate = Path(pattern)
    if not candidate.is_absolute():
        return pattern
    workspace = workspace.resolve()
    candidate = candidate.resolve()
    if workspace != candidate and workspace not in candidate.parents:
        return pattern
    return candidate.relative_to(workspace).as_posix()


def _matches_glob(relative: Path, pattern: str) -> bool:
    relative_posix = PurePosixPath(relative.as_posix())
    normalized = pattern.replace("\\", "/")
    candidates = _expand_glob_candidates(normalized)
    for candidate in candidates:
        if relative_posix.match(candidate) or fnmatch.fnmatch(relative.as_posix(), candidate):
            return True
    return False


def _expand_glob_candidates(pattern: str) -> set[str]:
    results = {pattern}
    stack = [pattern]
    seen = {pattern}
    while stack:
        current = stack.pop()
        for needle, replacement in (("**/", ""), ("/**", "")):
            if needle not in current:
                continue
            next_pattern = current.replace(needle, replacement, 1)
            if next_pattern in seen:
                continue
            seen.add(next_pattern)
            results.add(next_pattern)
            stack.append(next_pattern)
    return results


class LsTool(BaseTool):
    tool_id = "ls"
    name = "ls"
    description = "List files and directories under a workspace path. Prefer this for directory inspection over bash ls."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=300, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean"},
        },
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        raw_path = arguments.get("path", ".")
        recursive = bool(arguments.get("recursive", False))
        path = resolve_workspace_path(context.workspace, raw_path)
        if not path.exists():
            return ToolExecutionResult.failure(
                f"path not found: {raw_path}",
                error_type="path_not_found",
                hint="Use an existing relative path inside the workspace.",
                metadata={"path": raw_path, "operation": "ls"},
            )
        entries: list[str] = []
        if recursive:
            iterator = sorted(path.rglob("*"))
        else:
            iterator = sorted(path.iterdir())
        for item in iterator:
            relative = item.relative_to(context.workspace)
            if any(part in IGNORED_TOP_LEVEL_NAMES for part in relative.parts):
                continue
            suffix = "/" if item.is_dir() else ""
            entries.append(str(relative) + suffix)
        return ToolExecutionResult.success(
            "\n".join(entries) if entries else "(empty)",
            title=f"Listed {raw_path}",
            metadata={"path": raw_path, "recursive": str(recursive), "entry_count": str(len(entries))},
        )


class GlobTool(BaseTool):
    tool_id = "glob"
    name = "glob"
    description = "Find files by glob pattern inside the workspace."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=400, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "base_path": {"type": "string"},
        },
        "required": ["pattern"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        pattern = arguments["pattern"]
        base_path = arguments.get("base_path", ".")
        base = resolve_workspace_path(context.workspace, base_path)
        if not base.exists():
            return ToolExecutionResult.failure(
                f"base path not found: {base_path}",
                error_type="path_not_found",
                hint="Use an existing base_path inside the workspace.",
                metadata={"pattern": pattern, "base_path": base_path, "operation": "glob"},
            )
        matches = [
            str(path.relative_to(context.workspace))
            for path in sorted(base.glob(pattern))
            if not any(part in IGNORED_TOP_LEVEL_NAMES for part in path.relative_to(context.workspace).parts)
        ]
        if not matches and "/" not in pattern and "*" not in pattern:
            matches = [
                str(path.relative_to(context.workspace))
                for path in _iter_workspace_files(context.workspace, f"**/{pattern}")
            ]
        return ToolExecutionResult.success(
            "\n".join(matches) if matches else "(no matches)",
            title=f"Globbed {pattern}",
            metadata={"pattern": pattern, "base_path": base_path, "match_count": str(len(matches))},
        )


class GrepTool(BaseTool):
    tool_id = "grep"
    name = "grep"
    description = "Search text inside workspace files. Prefer this over bash grep for repository text search."
    output_limits = ToolOutputLimits(max_chars=12000, max_lines=300, direction="head")
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path_glob": {"type": "string"},
            "ignore_case": {"type": "boolean"},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        pattern = arguments["pattern"]
        path_glob = arguments.get("path_glob")
        ignore_case = bool(arguments.get("ignore_case", False))
        max_results = int(arguments.get("max_results", 50))
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)

        matches: list[str] = []
        scanned = 0
        for file_path in _iter_workspace_files(context.workspace, path_glob):
            scanned += 1
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{file_path.relative_to(context.workspace)}:{line_number}: {line}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break

        return ToolExecutionResult.success(
            "\n".join(matches) if matches else "(no matches)",
            title=f"Searched for {pattern}",
            metadata={
                "pattern": pattern,
                "path_glob": path_glob or "",
                "ignore_case": str(ignore_case),
                "match_count": str(len(matches)),
                "scanned_files": str(scanned),
            },
        )
