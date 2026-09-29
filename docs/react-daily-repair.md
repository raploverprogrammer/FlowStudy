# FlowStudy 每日一题中的 ReAct 知识补全

## 1. 功能目标

“每日一题”从固定题库中选择一道用户当前值得练习的题：

```text
错题 / 薄弱章节选题
        ↓
用户独立作答
        ↓
答对：允许继续下一道每日题
答错：启动有限的 ReAct 知识补全
        ↓
补充题练习
        ↓
回到原题验证
        ↓
生成并保存知识补全报告
```

ReAct 只用于“答错后如何补课”的决策，不用于生成题目，也不用于替代程序判题。

## 2. 为什么这里适合 ReAct

单纯解释一道题是一问一答，不需要 ReAct。

答错后的补课则需要根据中间结果改变后续行动：

```text
观察原题和答题结果
→ 查询用户章节掌握度
→ 查询题目知识标签
→ 获取同章节候选题
→ 选择继续巩固、修补基础或回到原题
→ 观察补充题结果
→ 再决定下一步
```

下一步依赖上一步的 Observation，这构成了一个有边界的 ReAct 循环。

## 3. ReAct 状态

每次补课会话保存在 `react_runs`，主要状态包括：

- `original_question_id`：最初答错的题
- `original_user_answer`：用户第一次答案
- `support_count`：已经完成的补充题数量
- `support_results`：每道补充题的结果
- `asked_ids`：本次已经展示过的题目，避免重复
- `gap`：当前判断出的漏洞摘要
- `current_question`：下一道补充题
- `status`：补课、回到原题、完成

单次补课最多 3 道补充题，避免无限循环和 Token 浪费。

## 4. Observation 与 Action

### Observation

Agent 每轮可以看到压缩后的结构化状态：

```json
{
  "original_section": "当前题目所属章节",
  "original_phase": "foundation|comprehensive",
  "original_user_answer": "用户答案或思路",
  "knowledge_tags": [
    {
      "id": "section:foundation-calculus-01",
      "relation": "primary",
      "confidence": 0.55
    }
  ],
  "section_mastery": {
    "attempts": 6,
    "correct_attempts": 3,
    "accuracy": 0.5
  },
  "support_count": 1,
  "last_support_correct": false,
  "support_results": []
}
```

### Action

模型只能返回以下动作：

- `practice_same_section`：继续当前章节，但换一道题
- `practice_prerequisite`：综合题答错时优先安排同章基础题
- `verify_original`：回到原题验证
- `finish`：结束补课

模型还必须从数据库给出的候选题 ID 中选择，不能自己创造题目。

## 5. 工具调用边界

### 程序工具

- `get_question_knowledge()`：查询题目内部标签
- `get_section_mastery()`：查询章节掌握度
- `choose_repair_questions()`：从固定题库获取候选题
- `record_question_bank_attempt()`：记录答题结果
- `record_react_step()`：保存一次 Observation、Action 和工具结果
- `finish_react_run()`：结束 Agent 运行

当前版本没有假装拥有完整的前置知识图谱：当综合题答错时，
`choose_repair_questions()` 使用同科目、同章节的基础题作为“前置知识代理”。
后续如果补充人工复核的知识关系，再增加更细的前置节点。

### 模型职责

- 综合当前题目、历史掌握度和补充题结果
- 在允许动作中选择下一步
- 给出一句面向用户的简短说明
- 将已发生的事实整理成报告

### 程序强制约束

- 最多 3 道补充题
- 不能重复题目
- 不能越过固定题库范围
- 不能修改标准答案
- 不能修改程序判题结果
- 第十题或补课上限后必须停止

## 6. 知识标签策略

当前题目来自扫描题库，OCR 质量不一致。系统不把不可靠 OCR 强行转换成细粒度知识点，而是先使用导入时已经确认的元数据建立稳定标签：

```text
科目 + 章节 + 基础/综合阶段
```

对应数据库表：

- `knowledge_nodes`：内部知识节点
- `question_knowledge`：题目和知识节点的多对多关系

当前 1823 道题全部拥有至少一个章节级标签。未来可以在不改题库结构的情况下追加更细标签，并使用 `confidence` 和 `source` 区分自动标签与人工复核标签。

## 7. 无 API Key 时的回退

没有配置 OpenRouter 时，系统仍然可以运行：

- 综合题答错：优先选择同章基础题
- 基础题答错：继续选择同章未做题
- 补充题答对：回到原题
- 达到 3 道补充题：停止并生成程序版报告

因此每日一题不会因为 AI 服务暂时不可用而失效。

## 8. Token 与上下文控制

每轮只发送：

- 当前原题的必要文本
- 用户当前答案
- 当前章节掌握度
- 最近几道补充题结果
- 少量候选题摘要

不发送全部答题历史，也不发送整个数据库内容。题目仍然只从 SQLite 固定题库读取，DeepSeek 不负责出题。

## 9. 运行记录与可观测性

`react_steps` 会记录：

- 第几步
- Agent 选择的动作
- Observation
- 调用的工具
- 工具输入
- 工具输出

这些记录可以用于：

- 排查 Agent 为什么选择某道补充题
- 统计错误类型
- 比较补课前后的正确率
- 后续增加 Agent 运行追踪和评估

## 10. 当前实现的定位

当前版本是一个**有边界的 ReAct 知识补全 Agent**：

```text
固定题库 + SQLite 学习记忆
        +
结构化工具调用
        +
最多三步的 ReAct 补课循环
        +
原题回测和学习报告
```

它不会把所有简单的答题逻辑交给 AI。程序负责稳定性和边界，Agent 负责根据中间结果选择补课策略。
