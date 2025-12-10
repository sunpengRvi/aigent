这是一个非常清晰的战略规划时刻。如果不先把**“数据资产化”**的路径规划好，现在跑再多遍任务，也只是浪费电费，没有沉淀下“智慧”。

为了让现在的每一次点击、每一次纠错都成为未来微调（SFT）和强化学习（RL）的燃料，我们制定了这份 **“全息数据黑盒”构建路线图**。

请过目，我们按这个单子一步步来。

---

### 🗺️ Road to AGI: 从“规则驱动”到“原生智能”路线图

#### ✅ 第一阶段：全息数据记录 (The Holographic Recorder)
**目标**：不再只是打印 Log，而是把 Agent 的每一次“思考-行动”循环变成标准化的训练样本。

* **[ ] 1.1 构建 `DatasetRecorder` 模块 (后端)**
    * **做什么**：不再覆盖保存 `latest_grounding.jpg`。而是按 `SessionID / StepID` 结构化保存每一帧。
    * **存什么**：
        * `Screenshot` (原始纯净图) -> 用于训练视觉特征。
        * `Marked Screenshot` (带红框图) -> 用于训练 SoM 定位能力。
        * `DOM Tree` + `Sitemap Hint` -> 作为输入的 Context。
        * `Prompt` (我们发给 Qwen 的指令) -> 作为 Instruction。
        * `Thinking Process` (DeepSeek 的 `<think>` 内容) -> **极其珍贵**，用于训练 CoT (思维链)。
        * `Action` (最终 JSON) -> 作为 Label。

* **[ ] 1.2 实现“视觉锚点”录制 (前端方案 A)**
    * **做什么**：修改 `RecordingService`。
    * **怎么做**：在用户录制 Demo 点击按钮的瞬间，前端利用 `html2canvas` 截取**被点击元素的小图 (Crop)**。
    * **价值**：这是 SFT 的核武器。告诉模型：“以后看到长成这张图（Crop）样子的东西，就去点它，不管 ID 变成了什么。”

---

#### 🔄 第二阶段：反馈闭环与样本分级 (Feedback Loop)
**目标**：自动区分“好数据”和“坏数据”，为 RL (DPO) 准备正负样本。

* **[ ] 2.1 捕获“负样本” (Negative Samples)**
    * **做什么**：在 `server.py` 的死循环重试逻辑里埋点。
    * **逻辑**：如果 Agent 第一次点了 ID 14 (Fail)，第二次纠错点了 ID 15 (Success)。
    * **生成数据**：
        * Prompt: "Select Two"
        * Rejected: `ID 14` (坏数据，用于 DPO 惩罚)。
        * Chosen: `ID 15` (好数据，用于 DPO 奖励)。

* **[ ] 2.2 捕获“正样本” (Positive Samples)**
    * **做什么**：利用 `Task Completed` 信号。
    * **逻辑**：如果任务顺利跑通，将整个 Session 标记为 `High Quality Trajectory`。

---

#### 🧠 第三阶段：离线知识蒸馏 (Offline Distillation)
**目标**：把“图片”变成“知识”，实现你提到的方案 B。

* **[ ] 3.1 构建后台分析器 (Background Worker)**
    * **做什么**：在空闲时间，让 Qwen2.5-VL 重新看一遍刚才录制的“视觉锚点（小图）”。
    * **问它**： "Describe this UI element visually."
    * **存入**：将生成的描述（"Blue Submit Button with a gear icon"）存入 ChromaDB。
    * **价值**：让 Agent 以后可以用自然语言描述来寻找元素，不再依赖死板的 DOM 结构。

---

#### 🚀 第四阶段：实战微调 (Training / SFT)
**目标**：甩掉庞大的 RAG 和 Prompt，让小模型（3B/7B）内化这些能力。

* **[ ] 4.1 数据格式转换器**
    * 把我们需要积累的 JSON/Image 数据，转换为 HuggingFace / Ollama 支持的微调格式 (如 `ShareGPT` 或 `Alpaca` 格式)。

---

### 🏁 既然我们有了单子，先迈出第一步？

我觉得 **[1.1 构建 `DatasetRecorder`]** 是当务之急。
因为我们现在的每一次调试都在产生宝贵的数据（比如你刚才跑通的 Find Flags 和跑挂的 Select Two），如果现在不存下来，这些经验就浪费了。

**您同意先从实现 `backend/dataset_recorder.py` 开始吗？**