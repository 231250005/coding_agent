"""冒烟测试：验证 agent 能否正确联通大模型。

测试两项核心能力：
1. 普通对话 —— 能拿到模型文本回复
2. tool calling —— 模型能按 JSON schema 返回结构化的工具调用参数

运行：python smoke_test.py
"""

from agent.llm import LLMClient

# 一个假的工具定义，用于验证 tool calling（本地不会真正执行）
WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气情况",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，如 北京"}
                },
                "required": ["city"],
            },
        },
    }
]


def test_plain_chat(client: LLMClient):
    print("=" * 50)
    print("[1] 测试：普通对话")
    resp = client.chat(
        [{"role": "user", "content": "你好！请只回复一句话：你是什么模型。"}]
    )
    content = resp.choices[0].message.content
    print(f"模型回复: {content}")
    usage = resp.usage
    print(f"token 用量: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")
    if not content:
        raise RuntimeError("普通对话失败：模型返回内容为空")
    return content


def test_tool_calling(client: LLMClient):
    print("=" * 50)
    print("[2] 测试：tool calling（模型应返回 get_weather 的工具调用）")
    resp = client.chat(
        [{"role": "user", "content": "北京今天天气怎么样？请查询一下。"}],
        tools=WEATHER_TOOL,
    )
    msg = resp.choices[0].message
    if not msg.tool_calls:
        print(f"警告：模型未返回工具调用，而是直接回复了：{msg.content}")
        print("提示：检查模型是否支持 function calling，或模型名是否正确。")
        return None
    for tc in msg.tool_calls:
        print(f"工具名: {tc.function.name}")
        print(f"参数(JSON): {tc.function.arguments}")
    return msg.tool_calls


def main():
    client = LLMClient()
    print(f"使用模型: {client.model}")
    print(f"API 端点: https://dashscope.aliyuncs.com/compatible-mode/v1")
    test_plain_chat(client)
    tool_calls = test_tool_calling(client)
    print("=" * 50)
    if tool_calls:
        print("✅ 全部通过：大模型连通成功，普通对话和 tool calling 均正常")
    else:
        print("⚠️ 对话正常，但 tool calling 未生效，请检查模型名或模型能力")


if __name__ == "__main__":
    main()
