import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import json
import chromadb
from openai import OpenAI  # 使用同步客户端方便测试

# === 1. 配置 ===
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1")
API_KEY = "ollama"
MODEL_NAME = "deepseek-r1:14b"  # 你的思考模型

client = OpenAI(api_key=API_KEY, base_url=OLLAMA_HOST)
chroma_client = chromadb.PersistentClient(path="./agent_brain_db")
demo_coll = chroma_client.get_collection("demonstrations")

# === 2. 核心功能：压缩 Demo ===
def simplify_demo_steps(steps_json):
    """
    把冗长的录制数据压缩成 DeepSeek 能看懂的‘摘要’。
    去掉具体的坐标、DOM 细节，只保留语义。
    """
    steps = json.loads(steps_json)
    simplified_plan = []
    
    for s in steps:
        # 兼容旧数据格式
        action = s.get('action')
        if isinstance(action, dict): action = action.get('type')
        
        desc = s.get('element_desc', 'Unknown Element')
        val = s.get('value', '')
        
        # 生成人类可读的单步描述
        step_desc = f"{action} -> {desc}"
        if val:
            step_desc += f" (Value: {val})"
        
        simplified_plan.append(step_desc)
    
    return simplified_plan

# === 3. 核心功能：Planner ===
def run_planner(user_goal):
    print(f"\n🧠 [Planner] Analyzing goal: '{user_goal}'...")
    
    # --- Step A: 检索 (Retrieve Top-N) ---
    results = demo_coll.query(
        query_texts=[user_goal],
        n_results=3  # 🔥 关键点：获取 3 个参考答案
    )
    
    if not results['documents'][0]:
        print("❌ No memory found.")
        return

    # --- Step B: 上下文组装 (Context Assembly) ---
    reference_text = ""
    for i, doc in enumerate(results['documents'][0]):
        task_name = doc
        steps_json = results['metadatas'][0][i]['steps']
        distance = results['distances'][0][i]
        
        # 只有相似度足够高才参考 (可选)
        plan_summary = simplify_demo_steps(steps_json)
        
        reference_text += f"\n--- Reference Case #{i+1} (Task: {task_name}) ---\n"
        reference_text += "\n".join([f"- {step}" for step in plan_summary])
        reference_text += "\n"

    print(f"📚 Retrieved {len(results['documents'][0])} references. Asking DeepSeek...")

    # --- Step C: 深度推理 (Reasoning) ---
    system_prompt = f"""
    You are an Expert Web Agent Planner.
    
    USER GOAL: "{user_goal}"
    
    I have retrieved {len(results['documents'][0])} past experiences that might be relevant:
    {reference_text}
    
    YOUR TASK:
    1. Analyze the Reference Cases. Are they relevant to the USER GOAL?
    2. If relevant, extract the COMMON LOGIC (pattern).
    3. Generate a NEW, abstract plan for the USER GOAL.
    
    OUTPUT FORMAT:
    Return a clear list of steps. Do not output JSON. Just natural language plan.
    """

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": system_prompt}],
        temperature=0.1 # 规划需要严谨
    )

    print("\n💡 === DeepSeek Generated Plan ===")
    print(response.choices[0].message.content)

# === 4. 入口 ===
if __name__ == "__main__":
    while True:
        g = input("\n🎯 Enter a goal to test (or 'q'): ")
        if g == 'q': break
        run_planner(g)