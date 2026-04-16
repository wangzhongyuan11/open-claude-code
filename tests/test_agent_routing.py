from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.agent.routing import decide_routing


def test_build_routes_planning_requests_to_plan():
    decision = decide_routing(AgentProfile(name="build"), "先分析 runtime.py 的结构，不要修改代码。")
    assert decision.action == "switch"
    assert decision.target_agent == "plan"


def test_plan_routes_implementation_requests_to_build():
    decision = decide_routing(AgentProfile(name="plan"), "请创建一个文件 demo.txt，内容是 hello")
    assert decision.action == "switch"
    assert decision.target_agent == "build"


def test_readonly_custom_agent_routes_exploration_to_explore():
    reviewer = AgentProfile(name="ts-reviewer", allowed_tools={"read_file", "grep"}, mode="all")
    decision = decide_routing(reviewer, "请定位 active_agent 的使用位置，并只返回函数名")
    assert decision.action == "delegate"
    assert decision.target_agent == "explore"


def test_build_does_not_delegate_github_mcp_search_requests():
    decision = decide_routing(AgentProfile(name="build"), "请使用 GitHub MCP 搜索 query=openagent，并只回复第一项仓库的 full_name。")
    assert decision.action == "stay"
    assert decision.target_agent is None
