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
