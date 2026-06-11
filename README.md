# FlowStudy V4 · 数学一知识航海

FlowStudy 是一个面向考研数学一的本地学习伙伴。题目来自用户提供的《张宇 1000 题》试题册与解析册；DeepSeek 不再生成题目，只在用户点击“请教噜噜”时讲解当前单题。

## 当前流程

```text
首页
├── 开始探索 → 数学一完整知识航线 → 固定题库五题航行
├── 触礁记录 → 重新思考错题 → 查看原解析
└── 发现宝藏 → 收藏总结与反思
```

五题航行结束后只保存客观答题记录和章节进度，不自动生成模板总结。
当用户针对某道题与噜噜连续讨论后，可点击“结束请教并生成总结”：
系统会根据该题、用户疑问和最近对话生成可收藏的认知总结。

知识航线包含：

- 基础篇：高等数学 19 章、线性代数 6 章、概率论与数理统计 6 章
- 强化篇：高等数学 18 章、线性代数 9 章、概率论与数理统计 9 章
- 综合篇：数学一测试卷 4 套

题库共 71 个章节/试卷、1256 道题。每题保存原题图片和解析图片，避免公式 OCR 文本影响阅读。

## 判题规则

- 选择题和高置信度短答案由程序直接判分。
- 复杂计算题、填空题和证明题先展示原解析，再由用户自评“我答对了 / 还需复习”。
- 答错题自动进入触礁记录。
- OCR 只用于建立索引和提取可判分答案，界面始终以扫描原图为准。

## AI 职责

OpenRouter 模型默认使用 `deepseek/deepseek-chat`。

AI 只负责单题讲解：

1. 用户先独立作答。
2. 用户点击“请教噜噜”并描述具体疑问。
3. 系统只发送当前章节、当前题 OCR 文本、题库答案和用户疑问。
4. 噜噜按考点、易错条件、解题步骤和可复用方法进行讲解。

AI 不生成题目，不决定目录，也不参与客观题判分。

## 配置 OpenRouter

在项目根目录 `.env` 中填写：

```dotenv
OPENROUTER_API_KEY=你的_OpenRouter_Key
OPENROUTER_MODEL=deepseek/deepseek-chat
```

`.env` 已加入 `.gitignore`。

## 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 重新导入题库

OCR 依赖：

```powershell
python -m pip install -r requirements-import.txt
```

将试题册和解析册放在桌面，然后分批执行：

```powershell
python tools/import_question_bank.py --batch 1
python tools/import_question_bank.py --batch 2
python tools/import_question_bank.py --batch 3
python tools/import_question_bank.py --batch 4
python tools/import_question_bank.py --batch 5
```

题库写入 `data/flowstudy.db`，裁图写入 `data/question_bank/`。这些内容仅供本地个人学习使用，不应重新分发。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py flowstudy services tools tests
```
