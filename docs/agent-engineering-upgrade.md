# FlowStudy Agent 工程升级

## 运行循环

每日一题答错后，系统先读取固定题目的知识标签、前置知识掌握度、章节掌握度和已保存的学习记忆。DeepSeek 再从有限的业务动作中选择下一步：解释、追问、练习前置知识、练习同章节、回到原题或结束。

默认协议是：

```text
LLM 输出结构化业务动作
→ ACTION_TOOL_MAP 路由
→ AGENT_TOOL_REGISTRY 参数校验
→ 执行固定题库工具
→ 保存 Observation 和耗时
→ 下一轮重新规划
```

这是一条 LLM-guided workflow，也是一条有边界的 ReAct-style loop。

## 工具安全边界

工具注册表统一保存工具描述、参数要求和处理函数。所有工具调用都经过：

1. 工具白名单检查；
2. 必填参数检查；
3. 基础类型检查；
4. 查询数量上限；
5. 固定题库约束。

Agent 没有写库、改掌握度或生成题目的工具权限。题目只能从数据库中抽取。

## 可靠性

- OpenRouter 请求最多重试三次，429 会短暂退避。
- 结构化输出解析失败会转为可读错误。
- DeepSeek 不可用时，诊断仍可使用本地有限策略继续推进。
- 单次诊断最多 12 个 Agent 步骤、最多 3 道补充题。
- 工具异常会进入轨迹，不会悄悄吞掉错误。

## 长期记忆

`agent_memories` 只保存明确有价值的信息，例如“先提示再给答案”和持续薄弱的知识点。原始聊天不会自动永久保存。首页可以查看并清除记忆，诊断时只读取最近的有限条目。

## 两种工具协议

默认的结构化动作协议适合当前稳定流程：

```json
{"next_action":"practice_prerequisite","target_knowledge_id":"..."}
```

诊断默认使用 OpenAI 兼容的 `tools` 参数，由模型直接返回 `tool_call`。如需兼容不支持工具调用的模型，可将 `FLOWSTUDY_NATIVE_FUNCTION_CALLING` 设置为 `0`；两条路径共享同一个 Python 工具注册表。

## 评测

`data/agent_eval_cases.json` 包含练习前置知识、练习同章节、解释、回到原题和结束诊断等行为案例。`flowstudy.agent_eval.evaluate_cases` 可以对模型决策结果检查：动作是否合法、工具是否正确、是否绕过固定题库约束。
