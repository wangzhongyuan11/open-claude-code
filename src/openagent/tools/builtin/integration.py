from __future__ import annotations

import ast
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openagent.domain.session import SessionTodo
from openagent.domain.tools import ToolArtifact, ToolContext, ToolExecutionResult
from openagent.session.todo import render_todos
from openagent.tools.base import BaseTool
from openagent.tools.builtin.search import _iter_workspace_files


class QuestionTool(BaseTool):
    tool_id = "question"
    name = "question"
    description = "Ask the user one or more clarifying questions through the active interactive runtime."
    input_schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "header": {"type": "string"},
                    },
                    "required": ["question"],
                },
            }
        },
        "required": ["questions"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        asker = context.runtime_state.get("ask_questions")
        if not callable(asker):
            return ToolExecutionResult.failure(
                "question is unavailable because the runtime did not provide an interactive question handler.",
                error_type="unsupported_runtime",
                hint="Run inside the interactive CLI or configure a question callback in runtime_state.",
                metadata={"operation": "question"},
            )
        questions = arguments["questions"]
        answers = asker(questions)
        formatted = ", ".join(f'"{item["question"]}"="{answer}"' for item, answer in zip(questions, answers))
        return ToolExecutionResult.success(
            f"User has answered your questions: {formatted}. You can now continue with the user's answers in mind.",
            title=f"Asked {len(questions)} question(s)",
            metadata={"operation": "question", "answers": json.dumps(answers, ensure_ascii=False)},
        )


class SkillTool(BaseTool):
    tool_id = "skill"
    name = "skill"
    description = "Load a skill template from configured skill directories and inject its instructions into context."
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        skill_name = arguments["name"]
        roots = [Path(root) for root in context.runtime_state.get("skill_roots", [])]
        skill_path = _find_skill_path(skill_name, roots)
        if skill_path is None:
            available = ", ".join(sorted(_list_available_skills(roots))) or "none"
            return ToolExecutionResult.failure(
                f'skill "{skill_name}" not found',
                error_type="skill_not_found",
                hint=f"Available skills: {available}",
                metadata={"operation": "skill", "skill_name": skill_name},
            )
        content = skill_path.read_text(encoding="utf-8").strip()
        base_dir = str(skill_path.parent)
        sample_files = sorted(str(path.relative_to(skill_path.parent)) for path in skill_path.parent.rglob("*") if path.is_file() and path.name != "SKILL.md")[:10]
        output = "\n".join(
            [
                f'<skill_content name="{skill_name}">',
                f"# Skill: {skill_name}",
                "",
                content,
                "",
                f"Base directory for this skill: {base_dir}",
                "<skill_files>",
                *sample_files,
                "</skill_files>",
                "</skill_content>",
            ]
        )
        return ToolExecutionResult.success(
            output,
            title=f"Loaded skill: {skill_name}",
            metadata={"operation": "skill", "skill_name": skill_name, "dir": base_dir},
            artifacts=[ToolArtifact(kind="file", path=str(skill_path), description="Loaded SKILL.md")],
        )


class LspTool(BaseTool):
    tool_id = "lsp"
    name = "lsp"
    description = "Perform basic code intelligence operations. Python files are supported with AST-based fallbacks."
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
            "query": {"type": "string"},
        },
        "required": ["operation"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        operation = arguments["operation"]
        handler = context.runtime_state.get("lsp_handler")
        if callable(handler):
            payload = handler(arguments, context)
            return ToolExecutionResult.success(
                json.dumps(payload, ensure_ascii=False, indent=2),
                title=f"LSP {operation}",
                metadata={"operation": "lsp", "delegated": "true"},
            )
        if operation in {"workspaceSymbol", "workspace_symbol"}:
            query = arguments.get("query", "")
            result = _workspace_symbols(context.workspace, query)
            return ToolExecutionResult.success(
                json.dumps(result, ensure_ascii=False, indent=2),
                title="workspace symbols",
                metadata={"operation": "lsp", "query": query, "result_count": str(len(result))},
            )
        file_path = arguments.get("file_path")
        if not file_path:
            return ToolExecutionResult.failure(
                "lsp requires file_path for this operation.",
                error_type="invalid_arguments",
                hint="Provide file_path plus 1-based line/character coordinates.",
                metadata={"operation": "lsp"},
            )
        path = (context.workspace / file_path).resolve()
        if not path.exists():
            return ToolExecutionResult.failure(
                f"file not found: {file_path}",
                error_type="path_not_found",
                metadata={"operation": "lsp", "file_path": file_path},
            )
        if path.suffix != ".py":
            return ToolExecutionResult.failure(
                "AST-based fallback LSP currently supports only Python files.",
                error_type="unsupported_filetype",
                hint="Use a Python file or configure an external lsp_handler in runtime_state.",
                metadata={"operation": "lsp", "file_path": file_path},
            )
        line = int(arguments.get("line", 1))
        character = int(arguments.get("character", 1))
        result = _python_lsp_fallback(path, operation, line, character)
        return ToolExecutionResult.success(
            json.dumps(result, ensure_ascii=False, indent=2),
            title=f"LSP {operation} {file_path}:{line}:{character}",
            metadata={"operation": "lsp", "file_path": file_path, "result_count": str(len(result))},
        )


class CodeSearchTool(BaseTool):
    tool_id = "codesearch"
    name = "codesearch"
    description = "Search code-like files for a regex pattern and return matching file/line hits."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path_glob": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        import re

        pattern = re.compile(arguments["pattern"])
        path_glob = arguments.get("path_glob")
        max_results = int(arguments.get("max_results", 50))
        code_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".cpp", ".c", ".h", ".md", ".json", ".yaml", ".yml"}
        matches: list[str] = []
        scanned = 0
        for file_path in _iter_workspace_files(context.workspace, path_glob):
            if file_path.suffix.lower() not in code_exts:
                continue
            scanned += 1
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{file_path.relative_to(context.workspace)}:{line_number}: {line}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
        return ToolExecutionResult.success(
            "\n".join(matches) if matches else "(no matches)",
            title=f"Code search for {arguments['pattern']}",
            metadata={"operation": "codesearch", "match_count": str(len(matches)), "scanned_files": str(scanned)},
        )


class ReadSymbolTool(BaseTool):
    tool_id = "read_symbol"
    name = "read_symbol"
    description = "Read a named Python function or class definition from a file."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "symbol": {"type": "string"},
        },
        "required": ["path", "symbol"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        path = (context.workspace / arguments["path"]).resolve()
        if not path.exists():
            return ToolExecutionResult.failure(
                f"file not found: {arguments['path']}",
                error_type="path_not_found",
                metadata={"operation": "read_symbol", "path": arguments["path"]},
            )
        if path.suffix != ".py":
            return ToolExecutionResult.failure(
                "read_symbol currently supports Python files only.",
                error_type="unsupported_filetype",
                hint="Use a Python file path or fall back to read_file/read_file_range.",
                metadata={"operation": "read_symbol", "path": arguments["path"]},
            )
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return ToolExecutionResult.failure(
                f"failed to parse Python file: {exc}",
                error_type="syntax_error",
                metadata={"operation": "read_symbol", "path": arguments["path"]},
            )
        symbol = arguments["symbol"]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
                segment = ast.get_source_segment(source, node) or ""
                if not segment:
                    lines = source.splitlines()
                    end_lineno = getattr(node, "end_lineno", node.lineno)
                    segment = "\n".join(lines[node.lineno - 1 : end_lineno])
                return ToolExecutionResult.success(
                    segment,
                    title=f"Read symbol {symbol} from {arguments['path']}",
                    metadata={
                        "operation": "read_symbol",
                        "path": arguments["path"],
                        "symbol": symbol,
                        "line": str(node.lineno),
                    },
                    artifacts=[ToolArtifact(kind="file", path=str(path), description=f"Symbol {symbol}")],
                )
        return ToolExecutionResult.failure(
            f"symbol not found: {symbol}",
            error_type="symbol_not_found",
            hint="Use codesearch or lsp workspaceSymbol/documentSymbol to locate the symbol first.",
            metadata={"operation": "read_symbol", "path": arguments["path"], "symbol": symbol},
        )


class BatchTool(BaseTool):
    tool_id = "batch"
    name = "batch"
    description = "Execute multiple tool calls sequentially and return a structured summary."
    input_schema = {
        "type": "object",
        "properties": {
            "calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool", "arguments"],
                },
            }
        },
        "required": ["calls"],
    }

    def invoke(self, arguments: dict, context: ToolContext) -> ToolExecutionResult:
        invoker = context.runtime_state.get("invoke_tool")
        if not callable(invoker):
            return ToolExecutionResult.failure(
                "batch is unavailable because the runtime did not provide an invoke_tool callback.",
                error_type="unsupported_runtime",
                hint="Run inside the standard runtime or configure invoke_tool in runtime_state.",
                metadata={"operation": "batch"},
            )
        results = []
        failures = 0
        for idx, call in enumerate(arguments["calls"], start=1):
            result = invoker(call["tool"], call["arguments"], parent_context=context)
            results.append(
                {
                    "index": idx,
                    "tool": call["tool"],
                    "status": result.status,
                    "title": result.title,
                    "output": result.content,
                }
            )
            if result.is_error:
                failures += 1
        return ToolExecutionResult.success(
            json.dumps(results, ensure_ascii=False, indent=2),
            title=f"Executed {len(results)} batched tool call(s)",
            metadata={"operation": "batch", "call_count": str(len(results)), "failure_count": str(failures)},
        )


def _find_skill_path(name: str, roots: list[Path]) -> Path | None:
    candidates = [name, name.replace("/", "_"), name.replace(" ", "-")]
    for root in roots:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            parent_name = skill_md.parent.name
            if parent_name in candidates:
                return skill_md
    return None


def _list_available_skills(roots: list[Path]) -> list[str]:
    names: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            names.add(skill_md.parent.name)
    return sorted(names)


def _workspace_symbols(workspace: Path, query: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for file_path in _iter_workspace_files(workspace, "**/*.py"):
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if query and query not in node.name:
                    continue
                results.append(
                    {
                        "name": node.name,
                        "kind": type(node).__name__,
                        "path": str(file_path.relative_to(workspace)),
                        "line": node.lineno,
                        "character": node.col_offset + 1,
                    }
                )
    return results[:100]


def _python_lsp_fallback(path: Path, operation: str, line: int, character: int) -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    target_name = _word_at_position(lines, line, character)
    results: list[dict[str, Any]] = []
    if operation in {"documentSymbol", "document_symbol"}:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                results.append({"name": node.name, "kind": type(node).__name__, "line": node.lineno, "character": node.col_offset + 1})
        return results
    if not target_name:
        return results
    if operation in {"goToDefinition", "go_to_definition", "hover"}:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == target_name:
                results.append(
                    {
                        "name": node.name,
                        "kind": type(node).__name__,
                        "line": node.lineno,
                        "character": node.col_offset + 1,
                        "signature": ast.get_source_segment(source, node).splitlines()[0] if operation == "hover" else "",
                    }
                )
        return results
    if operation in {"findReferences", "find_references"}:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == target_name:
                results.append({"name": node.id, "line": node.lineno, "character": node.col_offset + 1})
        return results
    return results


def _word_at_position(lines: list[str], line: int, character: int) -> str:
    if line < 1 or line > len(lines):
        return ""
    text = lines[line - 1]
    index = max(0, min(len(text) - 1, character - 1)) if text else 0
    if not text:
        return ""
    if not (text[index].isalnum() or text[index] == "_"):
        left = index - 1
        right = index + 1
    else:
        left = index
        right = index
    while left >= 0 and (text[left].isalnum() or text[left] == "_"):
        left -= 1
    while right < len(text) and (text[right].isalnum() or text[right] == "_"):
        right += 1
    return text[left + 1 : right]
