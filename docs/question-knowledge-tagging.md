# 题库知识点标注

FlowStudy 的固定题库现在支持三层知识关系：

- `direct`：题目直接考查的知识点；
- `prerequisite`：解题时需要调用的前置知识；
- `section_fallback`：无法可靠识别时保留的章节级兜底标签。

知识点目录由 `flowstudy/knowledge_catalog.py` 维护，包含高等数学、线性代数、概率论与数理统计的核心节点和前置关系。AI 分类只能从目录提供的候选节点中选择，不允许创造新的知识点 id。

## 分批分类

项目根目录运行：

```powershell
.venv\Scripts\python.exe tools\classify_question_bank.py --subject calculus --limit 100 --batch-size 20
```

可选参数：

- `--subject calculus|linear_algebra|probability`：只处理一个科目；
- `--section-id SECTION_ID`：只处理一个题章节；
- `--offset N --limit N`：断点分批处理；
- `--batch-size N`：每次发送给 AI 的题目数，默认 8；
- `--resume`：跳过已经有 AI 标签的题目，适合中断后继续；
- `--offline`：只使用关键词和章节标题，不调用 OpenRouter。

分类器不会删除章节兜底标签。AI 返回格式错误、网络失败、OCR 不清楚或置信度不足时，题目仍可正常抽题，只是继续按章节补题。

## ReAct 使用

补课 Agent 可以读取题目的 `direct` 和 `prerequisite` 标签，再结合章节掌握度决定：

1. 做同类题；
2. 先补前置知识；
3. 回到原题验证迁移。

当前数据库中的分类来源、置信度和章节兜底会保留，方便后续抽查和重新分类。

建议先用 `--offline --resume` 完成全库初标，再针对低置信度题目分章节使用 AI 精修。这样不会因为某一次网络请求变慢而阻塞整套题库导入。
