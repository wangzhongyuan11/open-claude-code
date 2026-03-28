from __future__ import annotations

from dataclasses import dataclass

from openagent.agent.profile import AgentProfile


@dataclass(slots=True)
class RoutingDecision:
    action: str = "stay"
    target_agent: str | None = None
    reason: str = ""


def decide_routing(active: AgentProfile, user_text: str) -> RoutingDecision:
    lowered = user_text.lower()

    planning_request = _looks_like_planning(lowered)
    build_request = _looks_like_build(lowered)
    explore_request = _looks_like_exploration(lowered)
    readonly_agent = _is_readonly_agent(active)

    if active.name == "build" and planning_request:
        return RoutingDecision(action="switch", target_agent="plan", reason="planning-request")

    if (active.name == "plan" or readonly_agent) and build_request:
        return RoutingDecision(action="switch", target_agent="build", reason="implementation-request")

    if (active.name == "build" or readonly_agent) and explore_request and not build_request:
        return RoutingDecision(action="delegate", target_agent="explore", reason="exploration-request")

    return RoutingDecision()


def _looks_like_planning(lowered: str) -> bool:
    planning_tokens = [
        "先分析",
        "先规划",
        "给出计划",
        "设计方案",
        "不要修改",
        "只读",
        "只做分析",
        "review only",
        "plan only",
        "分析当前实现",
    ]
    implementation_tokens = [
        "创建",
        "修改代码",
        "编辑",
        "实现",
        "修复",
        "写入",
        "运行测试",
    ]
    has_planning = any(token in lowered for token in planning_tokens)
    negative_edit_intent = any(
        token in lowered for token in ["不要修改代码", "不要修改", "不修改代码", "不要改代码", "只读"]
    )
    has_implementation = any(token in lowered for token in implementation_tokens)
    if negative_edit_intent and not any(token in lowered for token in ["创建", "写入", "实现", "修复", "运行测试"]):
        has_implementation = False
    return has_planning and not has_implementation


def _looks_like_build(lowered: str) -> bool:
    tokens = [
        "创建",
        "修改",
        "编辑",
        "实现",
        "修复",
        "写入",
        "追加",
        "运行测试",
        "apply patch",
        "write file",
        "edit file",
    ]
    return any(token in lowered for token in tokens)


def _looks_like_exploration(lowered: str) -> bool:
    tokens = [
        "定位",
        "查找",
        "搜索",
        "哪里使用",
        "引用",
        "用在什么地方",
        "列出使用位置",
        "只返回函数名",
        "只返回路径",
        "find references",
        "where is",
        "search",
    ]
    return any(token in lowered for token in tokens)


def _is_readonly_agent(profile: AgentProfile) -> bool:
    if profile.allowed_tools is None:
        return False
    write_like = {
        "write_file",
        "write",
        "append_file",
        "edit_file",
        "edit",
        "replace_all",
        "insert_text",
        "multiedit",
        "apply_patch",
        "patch",
        "ensure_dir",
        "bash",
    }
    return not any(tool in profile.allowed_tools for tool in write_like)
