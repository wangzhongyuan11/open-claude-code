from openagent.session.termination import detect_completion


def test_exact_read_can_stop_on_full_content():
    decision = detect_completion(
        user_text="请读取 a.txt 并原样输出。",
        tool_name="read_file",
        arguments={"path": "a.txt"},
        content="hello\nworld\n",
        metadata={"path": "a.txt"},
    )

    assert decision is not None
    assert decision.reason == "exact-read"


def test_partial_read_does_not_stop_on_full_file_output():
    decision = detect_completion(
        user_text="请读取 a.txt 的前 2 行并原样输出。",
        tool_name="read_file",
        arguments={"path": "a.txt"},
        content="line-1\nline-2\nline-3\nline-4\n",
        metadata={"path": "a.txt"},
    )

    assert decision is None
