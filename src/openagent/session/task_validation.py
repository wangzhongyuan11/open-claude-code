from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChecklistStep:
    number: int
    text: str
    directories: list[str] = field(default_factory=list)
    created_files: dict[str, str] = field(default_factory=dict)
    replacements: list[tuple[str, str, str]] = field(default_factory=list)
    verification_only: bool = False


@dataclass(slots=True)
class MultiStepRequirements:
    directories: list[str] = field(default_factory=list)
    created_files: dict[str, str] = field(default_factory=dict)
    final_files: dict[str, str] = field(default_factory=dict)
    replacements: list[tuple[str, str, str]] = field(default_factory=list)
    requires_final_summary: bool = False
    steps: list[ChecklistStep] = field(default_factory=list)


@dataclass(slots=True)
class ValidationResult:
    complete: bool
    missing: list[str] = field(default_factory=list)


def looks_multistep(user_text: str) -> bool:
    return len(re.findall(r"(?m)^\s*\d+\.\s+", user_text)) >= 2


def parse_multistep_requirements(user_text: str) -> MultiStepRequirements:
    req = MultiStepRequirements()
    step_blocks = _split_step_blocks(user_text)
    last_file_path: str | None = None
    mutable_workflow = _looks_like_mutable_setup_workflow(user_text)
    for number, block in step_blocks:
        step = ChecklistStep(number=number, text=_step_text(block))
        if "创建目录" in block:
            step.directories.extend(_extract_declared_directories(block))
            req.directories.extend(step.directories)
        for path, content in _extract_create_file_blocks(block, default_path=last_file_path):
            cleaned = _clean_block_content(content)
            step.created_files[path] = cleaned
            req.created_files[path] = cleaned
            if not _should_skip_exact_final_content(path, mutable_workflow):
                req.final_files[path] = cleaned
            last_file_path = path
        for path, old_text, new_text in _extract_replacements(block):
            step.replacements.append((path, old_text, new_text))
            req.replacements.append((path, old_text, new_text))
            if path in req.final_files:
                req.final_files[path] = req.final_files[path].replace(old_text, new_text, 1)
            last_file_path = path
        inferred_path = _infer_last_file_reference(block)
        if inferred_path is not None:
            last_file_path = inferred_path
        step.verification_only = "最后读取" in block or "最终内容" in block or "只告诉我" in block
        req.steps.append(step)
    req.requires_final_summary = "最后直接告诉我" in user_text or "任务全部完成" in user_text
    req.directories = _dedupe(req.directories)
    return req


def validate_multistep_requirements(
    workspace: Path,
    requirements: MultiStepRequirements,
    final_reply: str = "",
) -> ValidationResult:
    missing: list[str] = []

    for directory in requirements.directories:
        path = _resolve_workspace_path(workspace, directory)
        if not path.exists() or not path.is_dir():
            missing.append(f"目录未完成: {directory}")

    for rel_path, expected_content in requirements.final_files.items():
        path = _resolve_workspace_path(workspace, rel_path)
        if not path.exists() or not path.is_file():
            missing.append(f"文件未创建: {rel_path}")
            continue
        actual = path.read_text(encoding="utf-8")
        if not _contents_match(path, actual, expected_content):
            missing.append(
                "文件内容不符合预期: "
                f"{rel_path}\n期望:\n{expected_content}\n实际:\n{actual}"
            )

    for rel_path, old_text, new_text in requirements.replacements:
        if rel_path in requirements.final_files:
            continue
        path = _resolve_workspace_path(workspace, rel_path)
        if not path.exists() or not path.is_file():
            missing.append(f"待修改文件不存在: {rel_path}")
            continue
        actual = path.read_text(encoding="utf-8")
        if new_text not in actual:
            missing.append(f"修改未生效: {rel_path}")
        elif old_text in actual and old_text != new_text:
            missing.append(f"旧内容仍存在: {rel_path}")

    if requirements.requires_final_summary and "任务全部完成" not in final_reply:
        missing.append("最终总结未明确声明任务全部完成")

    return ValidationResult(complete=not missing, missing=missing)


def _split_step_blocks(user_text: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"(?m)^\s*(\d+)\.\s+", user_text))
    blocks: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(user_text)
        blocks.append((int(match.group(1)), user_text[start:end].strip()))
    return blocks


def _extract_backtick_paths(block: str) -> list[str]:
    return [item for item in re.findall(r"`([^`]+)`", block) if "/" in item]


def _extract_declared_directories(block: str) -> list[str]:
    results = _extract_backtick_paths(block)
    parent_match = re.search(r"创建(?:目录)?\s+([A-Za-z0-9_./-]+)\s+及\s+(.+?)子目录", block, re.S)
    if parent_match:
        parent = parent_match.group(1).strip().rstrip("，。")
        raw_children = parent_match.group(2)
        children = re.findall(r"([A-Za-z0-9_.-]+)", raw_children)
        for child in children:
            if child in {"子目录"}:
                continue
            results.append(f"{parent}/{child}")
    return _dedupe(results)


def _extract_create_file_blocks(block: str, default_path: str | None = None) -> list[tuple[str, str]]:
    multiline_pattern = re.compile(r"创建文件\s+`([^`]+)`，内容为(?:[:：])?[ \t]*\n(.*)$", re.S)
    match = multiline_pattern.search(block)
    if match:
        return [(match.group(1), match.group(2))]
    inline_pattern = re.compile(r"创建文件\s+`([^`]+)`，内容为(?:[:：])?[ \t]*(.*)$", re.S)
    match = inline_pattern.search(block)
    if match:
        return [(match.group(1), match.group(2))]
    if default_path and re.search(r"创建(?:这个|该)?文件", block):
        fallback = re.search(r"内容为(?:[:：])?[ \t]*\n(.*)$", block, re.S) or re.search(
            r"内容为(?:[:：])?[ \t]*(.*)$", block, re.S
        )
        if fallback:
            return [(default_path, fallback.group(1))]
    return []


def _extract_replacements(block: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r"将\s+`([^`]+)`\s+中的.*?`([^`]+)`\s*修改为\s*`([^`]+)`",
        block,
        re.S,
    ):
        results.append((match.group(1), match.group(2), match.group(3)))
    return results


def _resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (workspace / raw_path).resolve()


def _normalize_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _contents_match(path: Path, actual: str, expected: str) -> bool:
    if path.suffix.lower() == ".json":
        actual_json = _try_parse_json(actual)
        expected_json = _try_parse_json(expected)
        if actual_json is not None and expected_json is not None:
            return actual_json == expected_json
    return _normalize_ws(actual) == _normalize_ws(expected)


def _try_parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _clean_block_content(text: str) -> str:
    cleaned = textwrap.dedent(text).strip()
    if cleaned.startswith("`") and cleaned.endswith("`") and "\n" not in cleaned:
        return cleaned[1:-1]
    quoted = re.match(r"^`([^`]+)`[。．.!！]?$", cleaned)
    if quoted and "\n" not in cleaned:
        return quoted.group(1)
    return cleaned


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _step_text(block: str) -> str:
    return re.sub(r"^\s*\d+\.\s*", "", block.strip(), flags=re.S)


def _infer_last_file_reference(block: str) -> str | None:
    for item in reversed(_extract_backtick_paths(block)):
        path = Path(item)
        if path.suffix or "/" in item:
            return item
    return None


def _looks_like_mutable_setup_workflow(user_text: str) -> bool:
    lowered = user_text.lower()
    return "pytest" in lowered and any(token in user_text for token in ("修复 bug", "修复后再次运行 pytest", "根据失败结果修复", "修复这个 bug"))


def _should_skip_exact_final_content(path: str, mutable_workflow: bool) -> bool:
    if not mutable_workflow:
        return False
    suffix = Path(path).suffix.lower()
    if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
        return False
    normalized = path.replace("\\", "/").lower()
    return "/src/" in normalized or "/tests/" in normalized
