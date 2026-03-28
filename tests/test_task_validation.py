from pathlib import Path

from openagent.session.task_validation import (
    looks_multistep,
    parse_multistep_requirements,
    validate_multistep_requirements,
)


def test_parse_multistep_requirements_extracts_dirs_files_and_replacements():
    prompt = """
1. 创建目录 `work/demo_project`，以及子目录：
   - `work/demo_project/docs`
   - `work/demo_project/config`

2. 创建文件 `work/demo_project/docs/README.md`，内容为：

hello

3. 将 `work/demo_project/config/app.json` 中的 `"mode": "test"` 修改为 `"mode": "production"`。

10. 最后直接告诉我：
   - 如果都成功，就回复“任务全部完成”
""".strip()

    req = parse_multistep_requirements(prompt)

    assert looks_multistep(prompt) is True
    assert "work/demo_project/docs" in req.directories
    assert req.created_files["work/demo_project/docs/README.md"] == "hello"
    assert req.replacements == [("work/demo_project/config/app.json", '"mode": "test"', '"mode": "production"')]
    assert req.final_files["work/demo_project/docs/README.md"] == "hello"
    assert req.requires_final_summary is True


def test_validate_multistep_requirements_checks_final_state(tmp_path: Path):
    root = tmp_path / "work" / "demo_project"
    (root / "docs").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "docs" / "README.md").write_text("hello", encoding="utf-8")
    (root / "config" / "app.json").write_text('{"mode": "production"}', encoding="utf-8")

    prompt = """
1. 创建目录 `work/demo_project`，以及子目录：
   - `work/demo_project/docs`
   - `work/demo_project/config`

2. 创建文件 `work/demo_project/docs/README.md`，内容为：

hello

3. 将 `work/demo_project/config/app.json` 中的 `"mode": "test"` 修改为 `"mode": "production"`。

10. 最后直接告诉我：
   - 如果都成功，就回复“任务全部完成”
""".strip()

    req = parse_multistep_requirements(prompt)
    result = validate_multistep_requirements(tmp_path, req, final_reply="任务全部完成")

    assert result.complete is True
    assert result.missing == []


def test_parse_multistep_requirements_applies_replacements_to_final_expected_content():
    prompt = """
1. 创建文件 `work/demo_project/config/app.json`，内容为：

{
  "mode": "test"
}

2. 将 `work/demo_project/config/app.json` 中的 `"mode": "test"` 修改为 `"mode": "production"`。
""".strip()

    req = parse_multistep_requirements(prompt)

    assert req.final_files["work/demo_project/config/app.json"] == '{\n  "mode": "production"\n}'


def test_parse_multistep_requirements_strips_inline_backticks_for_single_line_content():
    prompt = """
1. 创建文件 `work/demo_project/docs/subtask_note.txt`，内容为：
   `this file is created by delegated agent`
""".strip()

    req = parse_multistep_requirements(prompt)

    assert req.final_files["work/demo_project/docs/subtask_note.txt"] == "this file is created by delegated agent"
