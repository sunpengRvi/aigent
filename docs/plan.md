```markdown
# 🗺️ Road to AGI: 从“规则驱动”到“原生智能”路线图

## 🏆 当前状态：第一阶段已完成 (Stage 1 Complete)
**系统能力已升级**：具备全息数据录制能力，支持“全屏上下文 + 局部视觉锚点”的双重采集。

---

### ✅ 第一阶段：全息数据记录 (The Holographic Recorder) [COMPLETED]
**目标**：不再只是打印 Log，而是把 Agent 的每一次“思考-行动”循环变成标准化的训练样本。

* **[x] 1.1 构建 `DatasetRecorder` 模块 (后端)**
    * **状态**：**已实装** (`backend/dataset_recorder.py`)
    * **实现细节**：
        * 实现了 `session_{timestamp}_{uuid}` 的结构化存储。
        * **数据资产**：
            * `raw_screenshot`: 原始纯净图 (用于视觉特征训练)。
            * `marked_screenshot`: 带红框图 (用于 SoM 定位验证)。
            * `visual_crop`: **[NEW]** 交互元素的特写切片 (用于训练 Visual Grounding)。
            * `dom` + `prompt`: 完整的上下文输入。
            * `response_raw`: 包含 DeepSeek `<think>` 的完整思维链 (CoT)。
            * `action_json`: 结构化的动作标签。
        * **性能优化**：实现了 Base64 图片的即时落盘 (`save_demo_image`)，内存中仅保留文件路径，防止长任务导致 OOM。

* **[x] 1.2 实现“视觉锚点”录制 (前端方案)**
    * **状态**：**已实装** (`coreui-angular/.../recording.service.ts`)
    * **实现细节**：
        * **异步采集**：`recordAction` 升级为 Async 模式，使用 `Promise.all` 并行捕获全屏截图和元素切图。
        * **精准切图**：在 `AgentService` 中增加了 `captureElementCrop`，利用 `html2canvas` 对交互目标进行独立渲染。
        * **SFT 准备**：现在每一条人类演示数据都包含 `(Context Image, Target Crop) -> Action` 的完整映射，直接满足多模态微调需求。

---

### 🔄 第二阶段：反馈闭环与样本分级 (Feedback Loop) [NEXT STEP]
**目标**：自动区分“好数据”和“坏数据”，为 RL (DPO) 准备正负样本。

* **[ ] 2.1 捕获“负样本” (Negative Samples)**
    * **做什么**：在 `server.py` 的死循环重试逻辑里埋点。
    * **逻辑**：如果 Agent 第一次点了 ID 14 (Fail)，第二次纠错点了 ID 15 (Success)。
    * **生成数据**：
        * Prompt: "Select Two"
        * Rejected: `ID 14` (坏数据，用于 DPO 惩罚)。
        * Chosen: `ID 15` (好数据，用于 DPO 奖励)。

* **[x] 2.2 捕获“人工反馈” (Human Feedback)**
    * **状态**：**后端逻辑已就绪** (`server.py` 中的 `if msg_type == 'feedback'`)
    * **做什么**：前端已预留 👍/👎 按钮。
    * **逻辑**：后端已能接收 `rating: 1/-1` 并将其存入 ChromaDB 的 `rl_feedback` 集合。
    * **下一步**：需要在前端 UI 上更显眼地展示反馈按钮，并在自动任务结束后引导用户评价。

* **[ ] 2.3 捕获“正样本” (Positive Samples)**
    * **做什么**：利用 `Task Completed` 信号。
    * **逻辑**：如果任务顺利跑通，将整个 Session 标记为 `High Quality Trajectory`。

---

### 🧠 第三阶段：离线知识蒸馏 (Offline Distillation)
**目标**：把“图片”变成“知识”，实现方案 B。

* **[ ] 3.1 构建后台分析器 (Background Worker)**
    * **做什么**：在空闲时间，让 Qwen2.5-VL 重新看一遍刚才录制的“视觉锚点（小图）”。
    * **问它**： "Describe this UI element visually."
    * **存入**：将生成的描述（"Blue Submit Button with a gear icon"）存入 ChromaDB。
    * **价值**：让 Agent 以后可以用自然语言描述来寻找元素，不再依赖死板的 DOM 结构。

---

### 🚀 第四阶段：实战微调 (Training / SFT)
**目标**：甩掉庞大的 RAG 和 Prompt，让小模型（3B/7B）内化这些能力。

* **[ ] 4.1 数据格式转换器**
    * 把我们需要积累的 JSON/Image 数据，转换为 HuggingFace / Ollama 支持的微调格式 (如 `ShareGPT` 或 `Alpaca` 格式)。
```