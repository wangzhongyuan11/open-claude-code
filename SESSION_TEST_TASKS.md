# Session Test Tasks

以下任务用于真实验证 `openagent` 的 session 主干、message/part 协议、processor、prompt/context、compaction/summary。

## 0. REPL 多行输入

进入交互模式后，不再是一行一提交。

规则：

- 普通内容会进入当前输入缓冲区
- 只有输入 `/end` 才真正提交这条消息
- 输入 `/cancel` 会放弃当前缓冲区
- `/status`、`/inspect`、`/replay` 等 slash 命令必须在空缓冲状态下单独输入

## 1. 最小文本往返

输入：

```text
请只回复 session-smoke-ok。
```

理论预期：

- assistant 只回复 `session-smoke-ok`
- 本轮 assistant message 的 `finish` 为 `stop`
- session.json 中这轮 user/assistant message 都带 `session_id`
- session title 会自动设为第一轮用户请求的截断文本

## 2. 文件读取 + tool-use 协议

输入：

```text
请读取 README.md 的前 3 行并原样输出。
```

理论预期：

- assistant 先触发 `read_file`
- tool result 回填后 assistant 原样输出前 3 行
- session.json 中：
  - assistant tool-call message 含 `tool` part，`state.status=requested`
  - tool message 含 `tool` part，`state.status=completed`
  - 若是 `read_file`，tool message 额外带 `file` part

## 3. 文件写入

输入：

```text
请创建 session_demo.txt，内容是 hello-session。
```

理论预期：

- assistant 触发 `write_file`
- 文件真实落盘
- 最终 assistant 回复确认写入成功
- session.json 中保留 tool call / tool result / final assistant reply

## 4. 多轮会话恢复

输入顺序：

```text
第一轮：请只回复 one。
第二轮：请只回复 two。
```

然后退出，使用：

```bash
./openagent.sh --session-id <session_id>
```

理论预期：

- `/history` 可看到前两轮
- 继续发送 `请只回复 resumed-ok。`
- assistant 正常回复 `resumed-ok`

## 5. Compaction / Summary

建议环境变量：

```bash
OPENAGENT_COMPACT_MAX_MESSAGES=4
OPENAGENT_PROMPT_RECENT_MESSAGES=4
OPENAGENT_PROMPT_MAX_TOKENS=200
```

输入顺序：

```text
请只回复 alpha。
请读取 README.md 的前 2 行并原样输出。
请只回复 gamma。
请只回复 delta。
```

理论预期：

- session.json 中 `summary` 不为空
- `metadata` 中出现：
  - `prompt_token_estimate`
  - `compacted_token_estimate`
  - `prompt_window_message_count`
  - `compaction_mode`
  - `last_finish_reason`
  - `last_loop_steps`
  - `last_loop_tool_calls`
- 从 session 构建 prompt 时，前两条 synthetic message 分别是：
  - `agent=summary`
  - `agent=context`

## 6. Subagent

输入：

```text
请把下面任务委托给子代理完成：创建 subagent_check.txt，内容是 delegated-ok。完成后直接告诉我是否完成。
```

理论预期：

- 主代理调用 `delegate`
- 子代理在独立上下文中执行
- 最终文件真实存在
- 主代理应基于 delegate 结果收尾，而不是无限重复确认

## 7. 错误路径：bash 非零退出

输入：

```text
请执行命令 bash -lc 'echo fail-msg >&2; exit 7'，并告诉我错误输出和退出码。
```

理论预期：

- assistant 调用 `bash`
- tool result 中带 stderr
- 最终 assistant 回复包含：
  - `fail-msg`
  - `7`

## 8. Processor / Part 验证点

如果要直接检查 session.json，应重点看：

- `message.id`
- `message.session_id`
- `message.parent_id`
- `message.finish`
- `message.model`
- `message.tokens`
- `message.parts`
- assistant part 中是否有：
  - `step-start`
  - `tool`
  - `step-finish`
- tool message 中是否有：
  - `tool`
  - `file`（针对 `read_file`）

## 9. Inspect / Replay

命令：

```bash
./openagent.sh --session-id <session_id> --inspect
./openagent.sh --session-id <session_id> --replay
```

理论预期：

- `--inspect` 输出结构化 JSON
- 能看到：
  - `title`
  - `status`
  - `metadata`
  - `recent_messages`
  - 每条 recent message 的 `parts`
- `--replay` 输出 turn-by-turn 文本回放
- 至少能看到：
  - `Turn N`
  - `User: ...`
  - `Assistant: finish=...`
- 若有工具调用，则看到 `ToolRequest` / `ToolResult`

## 10. Streaming Processor Skeleton

输入：

```text
请只回复 stream-ready。
```

理论预期：

- assistant 最终回复 `stream-ready`
- session 日志 JSONL 中出现：
  - `model.stream.event`
  - `processor.part.appended`
- 对于纯文本回复，至少应看到这些事件类型：
  - `start`
  - `text-delta`
  - `finish`
- 对应的 part 事件至少应看到：
  - `step-start`
  - `text`
  - `step-finish`

## 11. Native Provider Streaming + CLI Live Output

命令：

```bash
./openagent.sh --stream --prompt "请只回复 stream-live-ok。"
```

理论预期：

- 终端在请求进行时直接打印文本，而不是等待整段完成后再一次性输出
- 本轮仍会落盘正常 session
- `.openagent/logs/<session_id>.jsonl` 中出现：
  - `model.stream.event`
  - `processor.part.appended`
- `model.stream.event` 至少包括：
  - `start`
  - 一个或多个 `text-delta`
  - `finish`
- 最终 assistant message 仍应是一个正常消息对象，而不是只存在于事件流中

## 12. Session Helpers + Richer Parts

命令顺序：

```bash
./openagent.sh --print-session
./openagent.sh --session-id <session_id> --stream --prompt "请创建 session_endgame_v4.txt，内容是 line-1。"
./openagent.sh --session-id <session_id> --prompt "请读取 session_endgame_v4.txt 并只回复其内容。"
./openagent.sh --session-id <session_id> --status
./openagent.sh --session-id <session_id> --inspect
```

理论预期：

- 文件真实落盘，外部读取应得到 `line-1`
- 第二个 prompt 应返回 `line-1`
- `--status` 能看到：
  - `state`
  - `retry_count`
  - `status_last_transition`
  - 最近一次 turn 的 metadata
- `--inspect` 的 tool message 中可看到 richer parts：
  - `tool`
  - `file`

## 13. Tool Runtime Extended Chain

使用同一个 session 连续执行下面至少 6 轮：

1. 让 agent 用 `ls` / `glob` / `read_file` 检查 `src/openagent/tools` 和 `src/openagent/agent/runtime.py`
2. 在 `work/tool_runtime_chain` 下创建一个故意失败的 `math_utils.py` 和 `test_math_utils.py`
3. 用 `bash` 运行 `pytest`，只观察失败，不修复
4. 用 `read_file_range` + `apply_patch` 修复 `return a - b`
5. 再次用 `bash` 跑测试，并用 `grep` 或 `codesearch` 确认 `return a + b`
6. 用 `task` 委托子代理创建 `notes.txt`
7. 用 `todowrite` 写入两个 todo，再用 `todoread` 读取

理论预期：

- 同一个 session 内保持上下文连续
- 至少出现 3 种以上工具
- 必须出现一次真实失败，再出现真实修复
- 最终外部验证：
  - `work/tool_runtime_chain/math_utils.py` 返回 `a + b`
  - `python -m pytest test_math_utils.py -q` 结果为 `1 passed`
  - `work/tool_runtime_chain/notes.txt` 内容为 `done-by-task`
  - session.json 中 todo 列表包含两条记录

## 13. 多步 Checklist 任务不应提前结束

输入：

```text
请完成下面这个多步任务，严格按顺序执行，并在最后给我一个简短总结：

1. 创建目录 `work/demo_project`，以及子目录：
   - `work/demo_project/docs`
   - `work/demo_project/config`
   - `work/demo_project/logs`

2. 创建文件 `work/demo_project/docs/README.md`，内容为：

# Demo Project

这是一个用于测试 session、tool call、delegate、revert、retry 的示例项目。

## Tasks
- create files
- read files
- edit files
- delegate subtask

3. 创建文件 `work/demo_project/config/app.json`，内容为：

{
  "name": "demo_project",
  "version": "1.0",
  "mode": "test",
  "features": ["session", "tools", "delegate"]
}

4. 创建文件 `work/demo_project/logs/run.log`，内容为：

[INIT] demo project created
[STATUS] pending verification

5. 读取 `work/demo_project/docs/README.md`，并确认文件中是否包含 `delegate subtask` 这一行。

6. 将 `work/demo_project/config/app.json` 中的 `"mode": "test"` 修改为 `"mode": "production"`。

7. 将 `work/demo_project/logs/run.log` 中的第二行
`[STATUS] pending verification`
修改为
`[STATUS] verified`

8. 请把下面任务委托给子代理完成：
   创建文件 `work/demo_project/docs/subtask_note.txt`，内容为：
   `this file is created by delegated agent`

9. 再次读取以下三个文件，并只检查最终内容是否符合预期：
   - `work/demo_project/docs/README.md`
   - `work/demo_project/config/app.json`
   - `work/demo_project/logs/run.log`

10. 最后直接告诉我：
   - 哪些文件被创建了
   - 哪些文件被修改了
   - 子代理任务是否成功
   - 如果都成功，就回复“任务全部完成”
```

理论预期：

- 即使 assistant 在中途误判并给出 `finish=stop`，runtime 也不会直接接受
- runtime 会根据最终文件状态继续推进剩余步骤
- 最终应真实满足：
  - `docs/README.md` 内容准确
  - `config/app.json` 的 `mode` 为 `production`
  - `logs/run.log` 第二行为 `[STATUS] verified`
  - `docs/subtask_note.txt` 由子代理创建，内容精确匹配
- 最终回复必须明确包含 `任务全部完成`

## 14. 工具生命周期与截断

输入：

```text
请读取一个非常大的文本文件，或者执行一个会产生大量输出的命令。
```

理论预期：

- 工具调用会在事件流中经过：
  - `tool.pending`
  - `tool.running`
  - `tool.succeeded` / `tool.failed`
- 若输出过大：
  - 返回内容应带截断提示
  - 完整输出应被写入 `.openagent/tool_outputs/`
  - tool result metadata 中应记录：
    - `truncated`
    - `output_path`
    - `duration_ms`

## 15. 连续多轮工具链验证

建议在同一个 session 内按顺序执行：

1. 使用 `ls` / `glob` 查看 `src/openagent/tools`
2. 使用 `grep` 查找 `tool.pending`
3. 创建一个故意带 bug 的最小 Python 示例
4. 使用 `bash` 运行受限范围内的 pytest，观察失败
5. 使用 `apply_patch` 或 `edit_file` 修复
6. 再次运行 pytest
7. 使用 `read_file_range` 只读取修复后的关键行

理论预期：

- 对话上下文应连续保留
- 至少串联 3 种以上工具
- 必须经过一次真实失败，再修复成功
- 最终文件内容和外部 pytest 结果应一致
  - `patch`
  - `snapshot`

如果要验证 retry / revert / todo：

```text
/todo add finish-session-review
/todos
请只回复 retry-base。
/retry
请只回复 to-be-reverted。
/revert
/history
```

理论预期：

- todo 会持久化
- retry 会重跑最后一条用户消息，并在 session 中留下 `retry` part
- revert 会撤销最后一轮，并留下 `snapshot` 类型的 session-op 记录

## 13. Completion Detection / Termination Condition

命令：

```bash
python - <<'PY'
from pathlib import Path
path = Path('/root/open-claude-code/work')
path.mkdir(exist_ok=True)
(path / 'already_done.txt').write_text('step-1\nstep-2-done\n', encoding='utf-8')
PY

./openagent.sh --prompt "请把 work/already_done.txt 中的 step-2 改成 step-2-done。"
./openagent.sh --prompt "请把下面任务委托给子代理完成：创建 work/subagent_note_fix.txt，内容是 delegated-n。完成后直接告诉我结果。"
```

理论预期：

- 第一个任务不应再进入无意义的 read/edit/read 循环
- 应直接停在“已经满足目标”的回复上
- 第二个任务不应在子代理完成后继续工具循环直到 `max_steps_exceeded`
- 应直接基于 delegate 结果收尾
