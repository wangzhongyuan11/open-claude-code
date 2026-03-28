from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MultiStepRequirements:
    directories: list[str] = field(default_factory=list)
    created_files: dict[str, str] = field(default_factory=dict)
    final_files: dict[str, str] = field(default_factory=dict)
    replacements: list[tuple[str, str, str]] = field(default_factory=list)
    requires_final_summary: bool = False


@dataclass(slots=True)
class ValidationResult:
    complete: bool
    missing: list[str] = field(default_factory=list)


def looks_multistep(user_text: str) -> bool:
    return len(re.findall(r"(?m)^\s*\d+\.\s+", user_text)) >= 2


def parse_multistep_requirements(user_text: str) -> MultiStepRequirements:
    req = MultiStepRequirements()
    step_blocks = _split_step_blocks(user_text)
    for number, block in step_blocks:
        if "创建目录" in block:
            req.directories.extend(_extract_backtick_paths(block))
        for path, content in _extract_create_file_blocks(block):
            cleaned = _clean_block_content(content)
            req.created_files[path] = cleaned
            req.final_files[path] = cleaned
        for path, old_text, new_text in _extract_replacements(block):
            req.replacements.append((path, old_text, new_text))
            if path in req.final_files:
                req.final_files[path] = req.final_files[path].replace(old_text, new_text, 1)
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
        if _normalize_ws(actual) != _normalize_ws(expected_content):
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


def _extract_create_file_blocks(block: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"创建文件\s+`([^`]+)`，内容为：\s*(.*)$", re.S)
    match = pattern.search(block)
    if not match:
        return []
    path = match.group(1)
    content = match.group(2).strip()
    return [(path, content)]


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


def _clean_block_content(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("`") and cleaned.endswith("`") and "\n" not in cleaned:
        return cleaned[1:-1]
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
