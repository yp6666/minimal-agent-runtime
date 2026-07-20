# MiniAgent

## 运行方式

环境要求：Python 3.11 及以上。

```bash
git clone https://github.com/yp6666/minimal-agent-runtime.git
cd minimal-agent-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -r minimal_agent/requirements.txt
cp minimal_agent/.env.example minimal_agent/.env
```

在 `minimal_agent/.env` 中填写配置：

```dotenv
DEEPSEEK_API_KEY=你的 DeepSeek API Key
TAVILY_API_KEY=你的 Tavily API Key
QWEATHER_API_KEY=你的和风天气 API Key
QWEATHER_WEATHER_BASE=https://你的和风天气专属 API Host
QWEATHER_GEO_BASE=https://你的和风天气专属 API Host
```

启动服务：

```bash
python3 -m minimal_agent
```

浏览器访问 <http://127.0.0.1:8010>。

## 系统设计

项目没有使用 LangGraph、OpenHands 等 Agent 框架，核心循环由 `AgentRuntime` 自行实现：

```text
用户输入
   │
   ▼
AgentRuntime
   │
   ├── 构建当前 session 的上下文
   ├── 调用 DeepSeek，并传入工具 Schema
   ├── 解析 final answer 或 tool calls
   ├── 校验并执行工具
   ├── 将工具结果放回上下文
   └── 继续循环，直到最终回复或达到最大步数
```

主要模块：

```text
Web UI / REST API
        │
        ▼
   AgentRuntime ───── 最大步数、单 session 并发锁
        │
        ├── DeepSeekClient ── 真实 LLM API
        ├── OutputParser ──── 解析工具调用或最终答案
        ├── ToolRegistry ──── 工具注册、Schema 和统一执行入口
        │      ├── calculator
        │      ├── search（Tavily）
        │      ├── weather（QWeather）
        │      └── todo（SQLite）
        ├── ContextManager ── 上下文构建与基础压缩
        └── SQLiteStore ───── sessions、messages、todos、traces
```

每个会话拥有独立的 `session_id`。消息、待办、摘要和执行轨迹都以该 ID 隔离，因此同一用户可以在多个会话间切换并继续追问，不会互相污染。会话标题由首条用户消息的前两个字符自动生成。

## Memory 的召回时机与放置方式

Memory 在每次调用 LLM 之前召回。`ContextManager` 根据当前 `session_id` 从 SQLite 中读取对应会话的数据，构造本次模型输入：

```text
System Prompt
+ 当前日期、时区和 session_id
+ 较早对话的压缩摘要
+ 最近 N 条原始消息
+ 当前 Agent 循环中的 assistant tool_calls
+ 与 tool_call_id 对应的工具执行结果
```

各类信息的放置方式：

- 用户输入：以 `user` message 保存并放入上下文，用于连续对话和追问。
- Agent 最终回复：以 `assistant` message 保存并放入后续上下文。
- 工具调用：以带 `tool_calls` 的 `assistant` message 放入当前循环上下文。
- 工具结果：以 `tool` message 放入上下文，并通过 `tool_call_id` 与调用对应。
- 较早历史：压缩为摘要，追加到 System Prompt；原始记录仍保留在 SQLite 中。
- 待办：按 `session_id` 持久化；需要读取时由 Agent 调用 `todo` 工具，不默认全部塞入上下文。
- 执行轨迹：用于界面观测和问题排查，不作为长期对话 Memory 自动召回。
- 思考过程：不保存或召回完整隐藏思维链，只记录可验证的工具决策、结果、耗时和简短说明。

当消息数量超过配置阈值时，系统对较早消息做基础压缩，只向模型发送摘要和最近消息，从而限制上下文长度；原始消息不会被删除。
