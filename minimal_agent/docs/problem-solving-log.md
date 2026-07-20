# 问题解决记录

## 1. 不使用 Agent 框架

没有引入 LangGraph、OpenHands、OpenClaw 或 LangChain。LLM 客户端只负责发出 HTTP 请求；工具注册、输出解析、循环、消息状态、最大步数、错误回注和 trace 都在本项目中实现。

## 2. DeepSeek 模型名更新

实现时官方文档已提示旧的 `deepseek-chat` 和 `deepseek-reasoner` 名称即将弃用，因此默认使用 `deepseek-v4-flash`。模型和 Base URL 均可通过环境变量替换。

## 3. 和风天气 API Host 决策

当前官方推荐每个开发者使用专属 API Host，旧公共域名从 2026 年起逐步停止服务。初始版本曾按要求尝试 API Key 加旧公共域名：

- 天气：`https://devapi.qweather.com`
- 城市查询：`https://geoapi.qweather.com`

真实测试中，旧 GeoAPI 返回 404，旧天气域名返回 `403 Invalid Host`。切换账户专属 API Host 后，现有 API Key 鉴权测试通过。因此两个 Base URL 都被抽成环境变量，切换 Host 无需修改 Agent 或工具实现。

## 4. 搜索结果污染上下文

Tavily 默认关闭自动答案和原始页面正文，只返回最多五条标题、URL、分数和截断后的摘要。System Prompt 明确声明网页文本是不可信数据，减少搜索结果中的提示注入风险。

## 5. Memory 和上下文增长

所有消息永久保存在 SQLite。消息量超过阈值时，Runtime 将较早消息压缩为基础摘要，只把摘要和最近消息放回上下文。工具结果当前轮完整保留，较早工具结果只保留截断摘要。
