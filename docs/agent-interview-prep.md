# FlowStudy Agent 岗位面试准备

这份文档用于准备 FlowStudy 项目的简历介绍和 Agent 开发岗位面试。
回答问题时优先使用项目中真实存在的实现，不把普通的 Prompt 调用夸大成完整 Agent。

## 1. 项目一句话

FlowStudy 是一个面向考研数学学习场景的可观察学习 Agent：LLM 负责理解用户意图和选择下一步动作，应用层通过白名单工具查询学习状态和固定题库，SQLite 保存学习记忆与执行轨迹，系统再把 Agent 的真实执行过程转换成用户可读的进度提示。

项目的核心不是“接入 DeepSeek 聊天”，而是：

```text
自然语言输入
    -> LLM 意图路由
    -> 工具选择或业务动作
    -> 白名单工具执行
    -> 观察工具结果
    -> 继续规划或生成最终回答
```

## 2. 简历可用版本

### FlowStudy｜面向考研数学一的可观察学习 Agent

**技术栈：** Python、Streamlit、SQLite、OpenAI SDK、OpenRouter、DeepSeek、Function Calling、ReAct、结构化输出、unittest

- 面向考研数学学习场景，设计并实现自然语言学习 Agent，根据用户上下文自动路由至知识点讲解、薄弱点分析、错题解析和固定题库检索等流程。
- 构建白名单工具注册表，将知识点掌握度查询、薄弱知识点分析、章节题目检索和学习记忆读取封装为可调用工具，并支持 OpenAI 兼容的原生 Function Calling 与结构化 JSON 兼容路径。
- 实现有边界的 ReAct 知识补全流程：根据原题标签、章节掌握度和补充题结果，在前置知识练习、同章节练习、回到原题验证和结束诊断之间动态选择下一步；加入最大步数、补题上限、重复题过滤、参数校验、超时重试和本地降级策略。
- 坚持“固定题库检索而非模型生成题目”的数据约束。当前 SQLite 题库包含 1823 道题、78 个章节阶段，题目与知识节点通过多对多关系关联，避免模型自行编题造成题面和答案不可靠。
- 建立可观察 Agent 执行链路，记录路由、LLM 调用、工具调用、工具结果、耗时和错误，并将 Trace Event 映射为用户可见的实时处理进度。
- 使用 SQLite 持久化答题记录、错题、知识点掌握度、Agent 记忆、ReAct 执行步骤和学习总结；通过自动化测试覆盖工具注册、参数校验、意图路由、题库选择、ReAct 决策和降级逻辑。

### 简历指标口径

当前数据库实际数据：

- 题目数：1823
- 章节阶段数：78
- 基础阶段：42
- 综合阶段：18
- 强化阶段：18
- 自动化测试：当前 58 个测试用例

不要把“李林题库 1061 道”“当前总题库 1823 道”“23 个章节”等不同导入口径混写。面试时建议说：

> 当前本地数据库中有 1823 道题和 78 个章节阶段；其中不同题库和导入批次的统计口径不同，所以我在项目中把题库来源、学科、章节和阶段作为独立字段维护。

## 3. 系统架构

```text
Streamlit UI
  app.py / flowstudy/views.py
      |
      | 用户输入、题目展示、进度展示、公式渲染
      v
聊天 Agent 编排层
  flowstudy/chat_agent.py
      |
      | 读取上下文、调用 LLM、解释 tool result、维护当前题目
      v
模型适配层
  services/ai_service.py
      |
      | OpenAI SDK -> OpenRouter -> DeepSeek
      | native tools / structured JSON fallback
      v
工具层
  flowstudy/react_agent.py
      |
      | 工具注册表、白名单、参数校验、题库检索、掌握度查询
      v
数据层
  flowstudy/database.py
      |
      | SQLite：题库、答题记录、掌握度、错题、记忆、Trace
      v
固定内容
  content/、data/question_bank/、knowledge_catalog.py
```

### 主要模块职责

| 模块 | 职责 |
| --- | --- |
| `app.py` | 初始化 Streamlit、数据库和页面路由 |
| `flowstudy/views.py` | 页面、聊天 UI、后台任务轮询、题目和解析展示 |
| `flowstudy/chat_agent.py` | 聊天页 Agent 的上下文拼装、意图处理、工具编排和状态更新 |
| `services/ai_service.py` | OpenRouter/DeepSeek 调用、Prompt、结构化输出、原生工具调用和重试 |
| `flowstudy/react_agent.py` | 每日一题错题后的诊断与知识补全 Agent、工具注册表和动作约束 |
| `flowstudy/database.py` | SQLite schema、题库检索、掌握度计算、记忆和 Trace 持久化 |
| `flowstudy/agent_trace.py` | 将内部执行事件转换为用户可读进度 |
| `flowstudy/agent_eval.py` | 对 Agent 动作、工具和固定题库约束进行评测 |
| `tests/` | 单元测试和 Agent 行为测试 |

## 4. 你必须掌握的核心概念

### 4.1 LLM、Workflow 和 Agent 的区别

**LLM 调用：** 输入 Prompt，得到文本或结构化结果。模型本身通常是无状态的。

**Workflow：** 程序预先规定流程，例如：先查掌握度，再查题库，再回答。

**Agent：** 程序提供目标、上下文和工具，LLM 根据当前观察结果决定下一步动作；程序执行动作并把结果反馈给模型或编排层。

FlowStudy 是两者结合：

- 稳定边界和数据正确性由程序 Workflow 保证。
- 用户意图理解和部分下一步选择交给 LLM。
- 所有真实数据操作通过应用层工具完成。

### 4.2 为什么 LLM 不等于 Agent

单独调用 DeepSeek 只能得到一次模型输出。要成为 Agent，至少还需要：

1. 明确的目标和状态。
2. 可供模型选择的工具或动作。
3. 工具参数校验和执行器。
4. 将工具结果作为 Observation 放回流程。
5. 根据结果继续决策或生成最终回答。
6. 最大步数、超时和异常处理。

FlowStudy 中，`chat_agent.py` 和 `react_agent.py` 负责编排，`services/ai_service.py` 负责模型适配，`database.py` 提供工具实际需要的数据。

### 4.3 Function Calling 的完整过程

标准过程是：

```text
用户消息
  -> LLM + tools schema
  -> assistant.tool_calls
  -> 应用层解析工具名和 JSON 参数
  -> 白名单校验
  -> Python handler 执行
  -> tool result
  -> 再次调用 LLM
  -> 最终自然语言回答
```

关键点：模型返回的普通文本 JSON 不等于真正的工具调用。真正的原生工具调用应该出现在响应的 `tool_calls` 字段中，应用层不能把它直接展示给用户。

FlowStudy 对两种协议都做了适配：

- 原生路径：OpenAI 兼容的 `tools` 参数和 `tool_calls`。
- 兼容路径：模型返回结构化业务动作 JSON，再由应用层通过 `ACTION_TOOL_MAP` 路由。

这样做的原因是不同模型或不同 OpenRouter 路由对原生工具调用的支持程度可能不同，但底层 Python 工具注册表保持一致。

### 4.4 ReAct 是什么

ReAct 是 Reasoning and Acting 的组合思想：模型根据当前 Observation 选择 Action，执行工具后得到新的 Observation，再决定下一步。

FlowStudy 的每日一题补课流程：

```text
观察原题、用户答案、知识标签和章节掌握度
  -> 选择前置题或同章节题
  -> 用户完成补充题
  -> 观察补充题结果
  -> 继续练习、回到原题验证或结束
```

它不是无限自由的 Agent，而是有边界的 ReAct：

- 最多 12 个 Agent 步骤。
- 最多 3 道补充题。
- 不能重复展示本轮已问过的题目。
- 只能从固定题库选择题目。
- 不能修改标准答案或程序判题结果。

### 4.5 工具注册表为什么重要

如果把工具调用写成大量 `if/else`，工具描述、参数校验和执行逻辑会分散，新增工具容易出错。

注册表统一维护：

- 工具名称。
- 工具描述。
- 处理函数。
- 必填参数。
- 参数类型。
- 查询数量限制。

调用时统一经过：

```text
工具存在性检查
  -> 必填参数检查
  -> 参数类型检查
  -> 数量和范围限制
  -> 执行 handler
  -> 记录结果和耗时
```

面试时可以强调：LLM 只能提出工具请求，不能直接访问数据库，也不能直接写入学习记录。

### 4.6 对话历史、工作记忆和长期记忆

三者要区分：

- **对话历史：** 当前聊天中最近若干轮消息，用于理解“再来一道”“继续讲刚才那道题”等指代。
- **工作状态：** 当前题目、当前动作、当前薄弱点、已经调用的工具和本轮结果。
- **长期记忆：** 用户明确表达且值得长期保留的信息，例如“先给提示再给答案”。

DeepSeek API 本身通常不自动保存应用的历史。应用需要在下一次请求中重新组装 `messages`。FlowStudy 对聊天状态保留有限消息窗口，并把重要记忆单独写入 `agent_memories`，不把全部原始聊天永久写入长期记忆。

### 4.7 为什么题目不能让 LLM 自己生成

学习产品中的题目需要保证：

- 题面完整。
- 公式准确。
- 答案可验证。
- 难度和章节标签可靠。
- 能和历史答题记录关联。

因此 FlowStudy 让程序从固定题库中检索题目，LLM 负责理解意图、选择工具和讲解。这样牺牲了一部分开放生成能力，但提高了学习内容的可控性和可追溯性。

### 4.8 可观测性和思考过程的区别

不能把模型隐藏的内部思维直接展示给用户。FlowStudy 展示的是应用实际执行的安全事件：

```text
正在判断如何处理问题
  -> 正在读取知识点掌握情况
  -> 正在从固定题库查找题目
  -> 已找到匹配题目
  -> 正在整理最终回复
```

底层通过 `Trace Event` 记录 `route`、`llm_call`、`tool_call`、`tool_result`、`response` 和 `error` 等事件，再由 `trace_to_progress()` 转成用户提示。这种设计既提升体验，也方便定位 Agent 为什么做出某一步选择。

### 4.9 Prompt、工具和代码边界

Prompt 不能代替程序约束。正确的分工是：

- Prompt 告诉模型任务目标、工具含义和决策规则。
- 工具 schema 限制模型能提出什么请求。
- 应用层白名单和参数校验阻止非法调用。
- 数据库和业务代码保证题库、答案和掌握度的真实性。
- 测试验证模型输出不符合预期时的降级行为。

## 5. 高频面试题与回答模板

### Q1：请介绍一下这个项目

**建议回答：**

FlowStudy 是我做的一个面向考研数学的学习 Agent。用户可以用自然语言让系统解释知识点、分析薄弱点或练习题目。LLM 不直接生成题目，而是根据上下文选择白名单工具，程序从 SQLite 中查询掌握度、错题和固定题库，再把工具结果反馈给 Agent 生成最终回复。对于每日一题答错的场景，我实现了一个有边界的 ReAct 补课流程，根据中间答题结果决定继续练习前置知识、练习同章节题、回到原题验证还是结束诊断。同时我记录了 Agent Trace，向用户展示真实的处理阶段，并用于调试和评测。

### Q2：你的 Agent 和普通 Chatbot 有什么区别？

普通 Chatbot 主要是一次 LLM 输入输出。我的 Agent 有明确的状态、工具和执行循环。模型可以提出工具请求，应用层验证并执行工具，再把工具结果作为新的 Observation 交给后续决策。系统还维护当前题目、答题记录、掌握度、补题数量和执行步骤，并设置了最大步数和降级逻辑。

### Q3：Agent 的一次请求具体怎么走？

以“帮我找一道薄弱知识点的题”为例：

1. 读取当前会话、当前题目和有限的长期记忆。
2. 将用户消息、上下文和可用工具描述传给 LLM。
3. LLM 判断这是通用练习请求，提出 `get_weak_concepts` 工具调用。
4. 应用层校验参数并从 SQLite 查询真实答题记录。
5. 根据薄弱点依次调用 `choose_question_for_knowledge`。
6. 将题目结果保存到状态和 Trace。
7. LLM 或应用编排层生成面向用户的回复，界面展示题目和处理过程。

如果用户只问“分块矩阵的变化有哪些”，这是知识讲解问题，不需要查询学习薄弱点，系统会直接让模型回答。

### Q4：你是怎么给 LLM 提供工具的？

工具集中定义在 Agent 工具注册表中。每个工具包含名称、描述、处理函数、必填参数和类型定义。注册表可以转换为 OpenAI 兼容的 tools schema 传给模型，也可以转换为结构化动作协议使用。模型只负责提出工具请求，最终是否执行由应用层再次校验。

### Q5：原生 Function Calling 和普通 JSON 输出有什么区别？

普通 JSON 是模型生成的一段文本，应用需要自己解析，模型可能把 JSON 混进解释文字里。原生 Function Calling 通过 API 的 `tools` 参数声明函数，模型返回结构化的 `tool_calls`，其中包含工具名和参数。应用可以明确区分“模型最终回复”和“工具请求”。

项目同时保留结构化 JSON 兼容路径，因为部分模型或路由对原生工具调用支持不稳定。两条路径最终都调用同一个 Python 工具注册表，避免重复实现业务逻辑。

### Q6：为什么不让模型直接操作数据库？

安全性、数据正确性和可测试性都不允许模型直接操作数据库。模型只能调用抽象工具，例如“查询薄弱知识点”或“从指定知识点选题”。工具内部负责 SQL、参数范围、固定题库约束和错误处理。这样可以避免模型修改标准答案、越权写数据或构造任意 SQL。

### Q7：你的 ReAct 和普通流程有什么区别？

普通流程可能固定为“查薄弱点，然后出题”。ReAct 的下一步取决于上一动作的结果。例如综合题答错后，系统可能安排前置知识题；如果补充题答对，就回到原题验证；如果仍然答错，则继续巩固或结束。每一轮都使用结构化状态作为 Observation，再决定下一步 Action。

### Q8：为什么说你的 ReAct 是“有边界的”？

因为模型不能无限循环，也不能自由访问所有资源。系统最多执行 12 个 Agent 步骤，最多安排 3 道补充题，过滤重复题目，限制工具参数，并要求所有题目来自固定题库。如果 LLM 不可用，程序使用同章节基础题和有限本地策略继续推进。

### Q9：项目中哪些事情必须由程序决定，不能交给 LLM？

- 客观题的判分。
- 标准答案和题目原图。
- 题目是否来自固定题库。
- 数据库写入规则。
- Agent 最大步数和补题上限。
- 工具参数的合法性。
- 用户学习记录和掌握度的计算。

LLM 更适合做自然语言理解、解释、候选动作选择和学习反馈整理。

### Q10：你怎么处理 LLM 输出错误？

我做了多层处理：

1. 使用结构化输出和工具 schema 限制格式。
2. 对动作名称和参数做白名单、必填字段和类型校验。
3. 工具执行失败时记录错误事件，不静默吞掉。
4. OpenRouter 请求支持有限重试和 429 退避。
5. 模型不可用或解析失败时，切换到本地安全策略。
6. 使用 Agent 行为评测案例检查非法动作、错误工具和越过固定题库约束。

### Q11：你怎么避免 Agent 选择重复题目？

每次补课状态中保存 `asked_ids`，工具调用时把已经展示过的题目传入排除列表。数据库检索层再次执行过滤，而不是只依赖模型记忆。这样即使模型重复提出相同意图，最终也不会重复展示本轮题目。

### Q12：你怎么设计上下文，避免 Token 浪费？

不把整个数据库和全部历史聊天发给模型。每轮只组装：当前用户消息、最近对话、当前题目的必要信息、章节掌握度、少量知识标签、补充题结果和工具描述。长期信息单独保存，读取时限制条数。题目正文和图片由程序按需加载，模型只接收必要文本。

### Q13：对话记忆是怎么做的？

对话历史保存在当前会话状态中，用于理解上下文。长期记忆写入 `agent_memories`，但只保存用户明确表达且有长期价值的偏好，例如“先提示再给答案”。原始聊天不会自动全部变成长期记忆，用户还可以清除这些记忆。

### Q14：掌握度是怎么计算和使用的？

答题记录写入 `quiz_attempts`，知识点与题目通过 `question_knowledge` 关联。程序根据答题次数、正确次数和近期表现计算有效掌握度，再通过 `get_weak_concepts()` 产生薄弱方向。Agent 只能读取这个结果，不能自行修改掌握度；掌握度更新发生在程序记录答题结果时。

### Q15：为什么使用 SQLite？

这是一个个人本地学习应用，SQLite 足以支持单用户、低并发和本地部署，部署成本低，便于测试和备份。项目把题库、答题记录、知识节点、记忆和 Trace 分表保存，并通过外键和索引维护关系。

如果扩展成多用户在线产品，我会迁移到 PostgreSQL，并增加用户、会话、权限、并发连接池、异步任务队列和更完善的日志系统。

### Q16：为什么使用 Streamlit？

项目重点是 Agent 交互和学习流程验证，Streamlit 能快速完成页面、聊天输入、题目图片和状态展示。对长时间 LLM 请求，我使用后台线程执行任务，并通过 Streamlit fragment 周期性轮询任务状态，避免页面看起来卡死，同时显示阶段和已思考时间。

如果做生产级多人服务，我会将 UI 和后端拆分，后端采用 FastAPI，使用 WebSocket 或 SSE 推送 Trace，使用任务队列处理长任务。

### Q17：怎样实现用户可见的“思考过程”？

不展示模型隐藏推理，而是展示真实执行事件。每个路由、LLM 调用、工具调用和结果都会生成 Trace Event，前端通过映射函数显示“正在查询掌握情况”“正在查找题目”等状态。这样用户知道系统做了什么，但不会暴露内部推理或工具参数。

### Q18：如果用户发的是学习无关内容怎么办？

系统先让 LLM 结合上下文判断意图。对于非学习内容，不强行调用学习工具，也不把话题硬扯回学习。对于直接的知识问题，例如“分块矩阵的变化有哪些”，会优先直接回答，不触发薄弱点分析。

### Q19：如果用户只说“二重积分”，系统怎么知道他要出题？

这属于多轮上下文意图。上一轮如果存在未完成的“出题”意图，当前的短消息会被视为补充参数，而不是全新的独立请求。系统把历史对话和 `pending_practice_intent` 一起传给路由层，再选择指定知识点题库工具。

### Q20：为什么固定解析要优先于 LLM 重新讲解？

题库中的标准解析是经过整理的固定内容，准确性和题目对应关系更可靠。用户要求讲解当前题目时，程序先检查是否有固定解析，有则优先返回固定解析图片或内容；只有需要结合用户具体疑问继续追问时，才调用 LLM 做个性化解释。

### Q21：如何评测一个 Agent，而不是只测字符串？

不只比较最终文本，还检查结构化行为：

- 是否选择合法动作。
- 是否调用了正确工具。
- 工具参数是否正确。
- 是否越过固定题库约束。
- 是否在达到上限后停止。
- 是否在工具失败后进入安全降级。

项目使用 `data/agent_eval_cases.json` 保存案例，再由 `flowstudy/agent_eval.py` 检查决策契约。

### Q22：你写了哪些测试？

主要包括：

- 工具注册和参数校验。
- 薄弱点分析和指定知识点选题。
- 多轮“先出题、后补充知识点”的上下文继承。
- LLM 不返回工具字段时的本地兜底。
- Function Calling 结果解析。
- ReAct 动作选择和补题上限。
- 记忆保存和清除。
- 公式渲染和进度时间格式化。

当前测试套件为 58 个测试用例。

### Q23：这个项目目前有什么局限？

诚实回答：

- 当前知识关系主要是章节级标签，细粒度前置知识图谱还不完整。
- 本地 SQLite 适合单用户，不适合直接作为高并发生产数据库。
- 当前 Agent 评测主要是规则和案例契约，还可以增加更多真实用户轨迹、成功率、工具调用准确率和成本指标。
- 题库 OCR 主要用于索引和文本辅助，最终题面优先使用原始扫描图片。
- 不同模型对原生 Function Calling 的支持程度不同，因此保留了结构化 JSON 兼容路径。

回答局限时要同时说明下一步：补充人工复核的细粒度知识图谱、增加离线评测集、引入 Postgres 和任务队列、记录 token 成本与延迟分位数。

## 6. 关键代码定位

| 面试主题 | 主要代码 |
| --- | --- |
| 聊天 Agent 编排 | `flowstudy/chat_agent.py` |
| LLM 和 Function Calling | `services/ai_service.py` |
| 工具注册与 ReAct | `flowstudy/react_agent.py` |
| 执行 Trace | `flowstudy/agent_trace.py` |
| 数据库和学习状态 | `flowstudy/database.py` |
| 页面和用户进度 | `flowstudy/views.py` |
| Agent 行为评测 | `flowstudy/agent_eval.py`、`data/agent_eval_cases.json` |
| 设计说明 | `docs/react-daily-repair.md`、`docs/agent-engineering-upgrade.md` |

## 7. 面试前必须能手写的伪代码

### 7.1 原生工具调用循环

```python
messages = system_prompt + history + [user_message]

for step in range(MAX_STEPS):
    response = llm.chat(messages=messages, tools=tool_schemas)
    assistant_message = response.message
    messages.append(assistant_message)

    if not assistant_message.tool_calls:
        return assistant_message.content

    for call in assistant_message.tool_calls:
        name = call.function.name
        arguments = json.loads(call.function.arguments)
        result = execute_allowlisted_tool(name, arguments)
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })

raise AgentStepLimitError()
```

### 7.2 有边界的 ReAct

```python
state = observe_original_question()

for step in range(MAX_AGENT_STEPS):
    action = llm_choose_action(state)
    validate_action(action)

    if action == "practice_prerequisite":
        question = choose_fixed_bank_question(state, scope="prerequisite")
    elif action == "practice_same_section":
        question = choose_fixed_bank_question(state, scope="same_section")
    elif action == "verify_original":
        return show_original_question(state)
    elif action == "finish":
        return generate_report(state)

    state = observe_support_question_result(question)
    record_trace(state, action)
```

## 8. 30 秒、2 分钟和 5 分钟介绍稿

### 30 秒版本

我做了一个考研数学学习 Agent。它不是让大模型自由生成题目，而是让 LLM 根据用户意图选择工具，从固定题库和学习记录中查询真实内容。项目实现了 Function Calling、掌握度分析、错题后的有边界 ReAct 补课流程，以及用户可见的 Agent Trace。后端用 SQLite 保存题库、答题状态、记忆和执行轨迹，并通过测试验证工具调用和降级逻辑。

### 2 分钟版本

FlowStudy 的核心问题是让学习助手真正根据用户状态行动，而不是固定回复。用户说“帮我找一道薄弱知识点的题”时，模型先判断意图，调用掌握度工具，再调用固定题库工具，最后生成题目说明；用户只问一个数学知识点时，则直接回答，不强行查询学习记录。每日一题答错后，系统会启动一个有边界的 ReAct 流程，把原题、章节掌握度和补充题结果作为 Observation，让 Agent 在前置题、同章节题、原题验证和结束之间选择。程序层负责白名单、参数校验、重复题过滤、步数和补题上限，保证 Agent 不会越权生成题目或修改答案。为了调试和用户体验，我还记录了每个路由、工具调用、结果和耗时，并映射成实时进度。这个项目让我重点实践了 Agent 编排、工具调用、状态管理、记忆、可靠性和评测。

### 5 分钟版本的展开顺序

1. 先讲真实用户问题：学习助手需要结合答题历史，而不是只做通用问答。
2. 再讲架构：Streamlit、聊天编排层、模型适配层、工具注册表和 SQLite。
3. 讲一个具体链路：用户请求薄弱点题目，LLM 调工具，程序查数据，再回到模型。
4. 讲 ReAct：答错后根据补充题结果改变下一步。
5. 讲边界：固定题库、最大步数、补题上限、参数校验和 fallback。
6. 讲可观测性：Trace Event、用户进度、耗时、错误记录。
7. 讲工程取舍：SQLite 和 Streamlit 适合当前单用户原型，多用户生产化会换成 PostgreSQL、FastAPI、任务队列和 SSE/WebSocket。
8. 最后主动说局限和下一步，体现工程判断力。

## 9. 面试前检查清单

- [ ] 能解释 LLM、Workflow、Agent 的区别。
- [ ] 能画出一次 Function Calling 的完整消息流。
- [ ] 能说明为什么 `tool_calls` 不等于普通文本 JSON。
- [ ] 能解释 Observation、Action、Tool Result 和 Final Answer。
- [ ] 能说明为什么 ReAct 必须设置最大步数。
- [ ] 能解释聊天历史、工作状态和长期记忆的区别。
- [ ] 能说出题目为什么必须来自固定题库。
- [ ] 能解释工具注册表和白名单的作用。
- [ ] 能说明 Streamlit 长任务如何避免页面看起来卡死。
- [ ] 能说出 SQLite 当前适用范围和迁移到 PostgreSQL 的方案。
- [ ] 能解释 Trace 与模型隐藏思维的区别。
- [ ] 能说明模型不可用、429、解析失败时怎么降级。
- [ ] 能讲清楚当前项目的限制，而不是把限制包装成已经完成的功能。
- [ ] 能现场写出一个最小 Agent Loop。
- [ ] 能说明如何测试 Agent 的行为，而不是只断言最终文本。

## 10. 不要在面试中这样说

- 不要说“模型自己记住了用户”，应说“应用层维护对话历史和长期记忆”。
- 不要说“展示了模型的思考过程”，应说“展示了真实的 Agent 执行 Trace”。
- 不要说“模型自动生成了个性化题目”，应说“模型选择工具，题目来自固定题库”。
- 不要说“这是完全自主的 Agent”，应说“这是带白名单、步数限制和固定数据边界的 Agent”。
- 不要把结构化 JSON 路由和原生 Function Calling 混为一谈。
- 不要声称已经有完整细粒度知识图谱；当前主要是章节级知识节点和题目关联。
- 不要把 Streamlit 原型包装成高并发生产系统；应主动说明生产化改造方案。

