# FlowStudy V4 · 数学一知识航海

FlowStudy 是一个面向考研数学一的本地学习伙伴。题目来自固定习题集，DeepSeek 不生成题目，只在用户点击“请教噜噜”时讲解当前单题。

## 当前流程

```text
首页
├── 开始探索 → 选择题库与章节 → 固定题库五题航行
├── 触礁记录 → 重新思考错题 → 查看原解析
└── 发现宝藏 → 收藏对话总结与反思
```

五题航行结束后只保存答题记录和章节进度，不自动生成模板总结。用户针对某道题与噜噜连续讨论后，可以生成并收藏这次单题对话的认知总结。

## 固定题库

当前并存两套来源：

- 张宇 1000 题：仅保留高等数学部分。
- 李林 880 题：高等数学、线性代数、概率论与数理统计（仅保留基础题和综合题）。

知识航线先按题库来源分组，再按学科和基础题、综合题显示。界面使用扫描原图，避免公式 OCR 误差影响题面。

李林 880 题当前导入：

- 23 个章节
- 41 个章节阶段
- 1061 道题
- 分为 5 个批次导入并逐批校验

解析册中有 1 道题未检出对应解析，系统会明确提示，不会用错误图片冒充答案；该题仍可使用“请教噜噜”进行讨论。

## 判题规则

- 选择题由程序直接判分。
- 复杂计算题、填空题和证明题展示原解析后，由用户自评“我答对了 / 还需复习”。
- 答错题自动进入触礁记录。
- OCR 只用于建立索引和提取可判分答案，界面始终以扫描原图为准。

## AI 职责

OpenRouter 默认模型为 `deepseek/deepseek-chat`。

AI 只负责单题讲解：

1. 用户先独立作答。
2. 用户点击“请教噜噜”并描述具体疑问。
3. 系统发送当前章节、当前题 OCR 文本、题库答案、用户疑问和最近对话。
4. 噜噜围绕用户真正卡住的地方继续追问和讲解。

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

## 重新导入李林 880 题

OCR 依赖：

```powershell
python -m pip install -r requirements-import.txt
```

脚本会在 `E:\` 自动查找两本做题册和一本解析册。分批执行：

```powershell
python tools/import_lilin880.py --batch 1
python tools/import_lilin880.py --batch 2
python tools/import_lilin880.py --batch 3
python tools/import_lilin880.py --batch 4
python tools/import_lilin880.py --batch 5
python tools/import_lilin880.py --validate
```

也可以只重导一个章节阶段：

```powershell
python tools/import_lilin880.py --section lilin880-c21-foundation
```

数据库写入 `data/flowstudy.db`，裁剪图片写入 `data/question_bank/lilin880/`。这些内容仅供个人本地学习使用，不应重新分发。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py flowstudy services tools tests
```
