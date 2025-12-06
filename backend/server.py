import os
import re
# ==========================================
# 🛑 1. Environment Configuration
# ==========================================
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import os
import sys
import re
import json
import datetime
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import chromadb


# ==========================================
# 2. Configuration & Initialization
# ==========================================
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-r1:14b") # Your model
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "ollama")

print(f"🔌 Connecting to AI Engine: {OLLAMA_HOST}")
print(f"🧠 Using Model: {MODEL_NAME}")

client = AsyncOpenAI(api_key=API_KEY, base_url=OLLAMA_HOST)

# Vector Database
chroma_client = chromadb.PersistentClient(path="./agent_brain_db")
demo_collection = chroma_client.get_or_create_collection(name="demonstrations")
rl_collection = chroma_client.get_or_create_collection(name="rl_feedback")

# Log File
DATASET_FILE = "user_trajectories.jsonl"

app = FastAPI()

# --- Runtime Cache ---
current_recording_session = [] 
last_context_cache = {}        
session_step_history = {}      
chat_history_cache = {}        

# ==========================================
# 3. Helper Functions
# ==========================================
def clean_ai_response(content):
    try:
        if "<think>" in content:
            content = content.split("</think>")[-1]
        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        if 'id' in data:
            match = re.search(r'(\d+)', str(data['id']))
            if match: data['id'] = match.group(1)
        return json.dumps(data)
    except:
        return content

def save_raw_log(data):
    try:
        if 'server_time' not in data:
            data['server_time'] = datetime.datetime.now().isoformat()
        with open(DATASET_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"❌ Log Write Failed: {e}")

# ==========================================
# 4. Brain A: Task Execution (Task Mode)
# ==========================================
async def ask_brain_task(user_goal, dom_state, session_id, history_logs):
    print(f"⚡ [Task Brain] Goal: {user_goal}")
    
    # --- RAG Retrieval (Demo & RL) ---
    demo_prompt = ""
    try:
        demo_results = demo_collection.query(query_texts=[user_goal], n_results=1)
        if demo_results['documents'] and len(demo_results['documents'][0]) > 0:
            steps = json.loads(demo_results['metadatas'][0][0]['steps'])
            demo_prompt = "### REFERENCE DEMONSTRATION:\n"
            for i, step in enumerate(steps):
                act = step.get('action', {})
                desc = step.get('element_desc', 'unknown')
                demo_prompt += f"Step {i+1}: {act.get('type')} on {desc}\n"
            demo_prompt += "### END DEMONSTRATION\n"
    except: pass

    rl_prompt = ""
    try:
        rl_query = f"Goal: {user_goal}\nContext: {dom_state[:500]}"
        rl_results = rl_collection.query(query_texts=[rl_query], n_results=3)
        if rl_results['documents'] and len(rl_results['documents'][0]) > 0:
            rl_prompt = "### LEARNED FEEDBACK:\n"
            for meta in rl_results['metadatas'][0]:
                if meta['reward'] > 0: rl_prompt += f"- GOOD: Doing '{meta['action']}' worked.\n"
                else: rl_prompt += f"- BAD: Avoid '{meta['action']}'.\n"
            rl_prompt += "### END FEEDBACK\n"
    except: pass

    history_prompt = ""
    if history_logs:
        history_prompt = "### SESSION HISTORY:\n" + "\n".join(history_logs[-8:]) + "\n"

    # --- Task System Prompt ---
    system_prompt = f"""
    You are an intelligent web automation agent.
    
    {demo_prompt}
    {rl_prompt}
    {history_prompt}
    
    Task: Generate the NEXT single JSON action.
    
    RULES:
    1. **ID MATCHING**: Use the exact numeric ID from 'CURRENT VISIBLE UI'.
    2. **NO TEXT ID**: Never use text as ID.
    3. **CHECK HISTORY**: Don't repeat failed actions.
    4. **FINISH**: If task completed, return {{"action": "message", "value": "Task Completed"}}.
    5. Output JSON ONLY. Format: {{"action": "click|type|select", "id": "...", "value": "..."}}
    """
    
    user_prompt = f"GOAL: {user_goal}\nCURRENT VISIBLE UI:\n{dom_state}"
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        return clean_ai_response(response.choices[0].message.content.strip())
    except Exception as e:
        return json.dumps({"action": "error", "value": f"Task AI Error: {str(e)}"})

# ==========================================
# 5. Brain B: Chat (Chat Mode - Enhanced)
# ==========================================
async def ask_brain_chat(user_msg, dom_state, session_id):
    print(f"💬 [Chat Brain] User: {user_msg}")
    
    # 🔥 核心修改：更新 Chat Mode 的系统提示词
    # 明确告诉 AI 它有两种模式：页面助手 和 通用助手
    chat_system_prompt = """
    You are a versatile AI assistant embedded in a web application.
    
    Your Capabilities:
    1. **General Knowledge**: You can answer questions about coding, history, science, writing, etc., just like ChatGPT.
    2. **Page Awareness**: You have read-only access to the current webpage structure (Context).
    
    Instructions:
    - If the user asks about the current page (e.g., "What is this page?", "Where is the login button?"), analyze the Context.
    - If the user asks a GENERAL question (e.g., "Write a python script", "Explain Quantum Physics"), IGNORE the Context and answer using your general knowledge.
    - Do NOT output JSON actions in this mode. Just chat naturally.
    """

    if session_id not in chat_history_cache:
        chat_history_cache[session_id] = [
            {"role": "system", "content": chat_system_prompt}
        ]
    
    history = chat_history_cache[session_id]
    
    # 🔥 优化：将页面上下文作为"辅助信息"而非"强制约束"
    # 我们明确标注 Context 部分
    current_input = f"""
    [Current Page Context (Use only if relevant)]:
    {dom_state[:1500]}... (truncated)
    
    [User Question]:
    {user_msg}
    """
    
    history.append({"role": "user", "content": current_input})
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=history,
            temperature=0.7, # 提高创造力
            stream=False
        )
        
        reply = response.choices[0].message.content
        if "<think>" in reply: reply = reply.split("</think>")[-1].strip()
            
        history.append({"role": "assistant", "content": reply})
        
        # 这里的截断逻辑要小心，保留 System Prompt
        if len(history) > 12: 
            chat_history_cache[session_id] = [history[0]] + history[-11:]
            
        return json.dumps({"action": "message", "value": reply})
        
    except Exception as e:
        return json.dumps({"action": "message", "value": f"Chat Error: {str(e)}"})

# ==========================================
# 6. WebSocket Endpoint
# ==========================================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    global current_recording_session
    
    if session_id not in session_step_history: session_step_history[session_id] = []
    
    print(f"✅ Frontend Connected (Session: {session_id})")
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                payload = json.loads(raw_data)
                msg_type = payload.get('type')

                # --- A. Record ---
                if msg_type == 'record_event':
                    current_recording_session.append(payload)
                    save_raw_log(payload)
                    print(f"📹 [Rec] {payload.get('action',{}).get('type')}")
                    continue

                # --- B. Save Demo ---
                if msg_type == 'save_demo':
                    task_name = payload.get('name')
                    if current_recording_session:
                        demo_collection.add(
                            documents=[task_name], 
                            metadatas=[{
                                "timestamp": datetime.datetime.now().isoformat(),
                                "steps": json.dumps(current_recording_session)
                            }],
                            ids=[f"demo_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({"type": "demo_saved", "name": task_name, "steps_count": len(current_recording_session)})
                        print(f"💾 Demo Saved: {task_name}")
                        await websocket.send_text(json.dumps({"action": "message", "value": f"Skill Learned: {task_name}"}))
                        current_recording_session = [] 
                    continue

                # --- C. Handle Instruction (Router) ---
                if 'instruction' in payload:
                    user_msg = payload.get("instruction")
                    dom_tree = payload.get("dom")
                    mode = payload.get("mode", "task") # 'chat' or 'task'
                    is_new_task = payload.get("is_new_task", False)

                    if not dom_tree:
                        await websocket.send_text(json.dumps({"action": "message", "value": "⚠️ UI Retrieval Failed"}))
                        continue

                    # 👉 Chat Mode
                    if mode == 'chat':
                        response = await ask_brain_chat(user_msg, dom_tree, session_id)
                        await websocket.send_text(response)
                    
                    # 👉 Task Mode
                    else:
                        if is_new_task:
                            session_step_history[session_id] = [] 
                            print("🔄 Starting New Task")

                        last_context_cache[session_id] = {"goal": user_msg, "dom_summary": dom_tree[:500]}
                        
                        action_json_str = await ask_brain_task(user_msg, dom_tree, session_id, session_step_history[session_id])
                        
                        try:
                            act_data = json.loads(action_json_str)
                            if act_data.get('action') in ['click', 'type', 'select']:
                                log = f"{act_data['action']} ID {act_data['id']}"
                                session_step_history[session_id].append(log)
                        except: pass

                        print(f"🤖 Task Action: {action_json_str}")
                        await websocket.send_text(action_json_str)

                # --- D. Feedback ---
                if msg_type == 'feedback':
                    rating = payload.get('rating')
                    action_taken = json.dumps(payload.get('action'))
                    context = last_context_cache.get(session_id)
                    if context:
                        rl_collection.add(
                            documents=[f"Goal: {context['goal']}\nUI: {context['dom_summary']}"],
                            metadatas=[{"action": action_taken, "reward": rating}],
                            ids=[f"rl_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({
                            "type": "feedback_event",
                            "rating": rating,
                            "action": payload.get('action'),
                            "context": context
                        })
                        print(f"📈 [RL] Feedback: {rating}")

            except json.JSONDecodeError: pass
            
    except WebSocketDisconnect:
        if session_id in session_step_history: del session_step_history[session_id]
        if session_id in chat_history_cache: del chat_history_cache[session_id]
        print(f"🔌 Connection Closed")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    print("🚀 Agent Server Starting...")
    uvicorn.run(app, host="0.0.0.0", port=8000)