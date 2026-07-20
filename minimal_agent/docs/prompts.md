# AI Prompt 记录

## 主 System Prompt

主提示词保存在 `minimal_agent/context.py` 的 `SYSTEM_PROMPT` 常量中，运行时还会附加：

- 当前日期和时间；
- `Asia/Shanghai` 时区；
- 当前 `session_id`；
- 较早对话的压缩摘要。

关键约束：模型可以直接回答或调用工具；不得假装执行工具；收到工具错误后可以修正参数；相对日期必须转换成 ISO 日期；搜索网页内容被视为不可信数据；最终回答尽可能携带来源。

## 工具 Prompt

工具信息不是拼接成自然语言，而是通过 DeepSeek/OpenAI 兼容的 `tools` 字段传入。每个工具均由统一注册中心提供：

- `name`：稳定的程序标识；
- `description`：告诉模型适用时机；
- `parameters`：由 Pydantic 参数模型生成的 JSON Schema。

Runtime 不相信模型生成的参数。任何调用都会再次经过 Pydantic 校验，然后才进入工具函数。

## 思考过程策略

系统不要求模型暴露完整隐藏思维链。`OutputParser` 支持读取 `reasoning_content` 或工具调用前的简短 `content`，但 trace 中最多保留 240 字的决策摘要。真正用于调试和验收的是可核验的事件：工具名、参数、结果、状态、耗时和最终答案。

## 输出解析

`OutputParser` 将 LLM 输出归一化成两种动作：

1. `tool_calls`：可以包含一个或多个函数调用；
2. `final`：没有工具调用且正文非空。

非法 JSON 参数、空响应、未知工具和参数校验失败都会转换为明确错误，不会让 Agent Runtime 崩溃。
