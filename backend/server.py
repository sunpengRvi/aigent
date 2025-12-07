import os
import sys
# ==========================================
# 🛑 1. Environment Configuration
# ==========================================
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import re
import json
import datetime
import hashlib
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import chromadb

# ==========================================
# 2. Configuration & Initialization
# ==========================================
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-r1:14b") 
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "ollama")

print(f"🔌 Connecting to AI Engine: {OLLAMA_HOST}")
print(f"🧠 Using Model: {MODEL_NAME}")

client = AsyncOpenAI(api_key=API_KEY, base_url=OLLAMA_HOST)

# Database
chroma_client = chromadb.PersistentClient(path="./agent_brain_db")
demo_collection = chroma_client.get_or_create_collection(name="demonstrations")
rl_collection = chroma_client.get_or_create_collection(name="rl_feedback")

DATASET_FILE = "user_trajectories.jsonl"
app = FastAPI()

# --- Runtime Cache ---
current_recording_session = [] 
last_context_cache = {}        
session_step_history = {}      
chat_history_cache = {}
session_blacklists = {} 

# ==========================================
# 3. Helper Functions
# ==========================================
def clean_ai_response(content):
    """Robustly extract JSON."""
    try:
        print(f"\n🧠 [AI Reasoning]:\n{content}\n")
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'(\{.*\})', content, re.DOTALL)
            if json_match: json_str = json_match.group(1)
            else: return json.dumps({"action": "message", "value": f"AI Raw: {content[:100]}..."})

        data = json.loads(json_str)
        
        # Normalize keys
        if 'action' in data and data['action'] in ['finish', 'return', 'done']:
            return json.dumps({"action": "message", "value": "Task Completed"})

        if 'id' in data:
            match = re.search(r'(\d+)', str(data['id']))
            if match: data['id'] = match.group(1)
            else: data['id'] = "INVALID_ID"

        if 'value' not in data:
            if 'message' in data: data['value'] = data['message']
            elif 'text' in data: data['value'] = data['text']

        return json.dumps(data)
    except Exception as e:
        print(f"❌ Parse Error: {e}")
        return json.dumps({"action": "error", "value": "Parse Error"})

def save_raw_log(data):
    try:
        if 'server_time' not in data: data['server_time'] = datetime.datetime.now().isoformat()
        with open(DATASET_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except: pass

def get_context_fingerprint(dom_str):
    if not dom_str: return "empty"
    tokens = re.findall(r'\[\d+\]\s*<(\w+)', dom_str)
    skeleton = "|".join(tokens[:300]) 
    return hashlib.md5(skeleton.encode('utf-8')).hexdigest()

# Helper: Check if text exists in DOM
def find_element_in_dom(desc, dom_str):
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").strip()
    if clean_desc in dom_str: return True
    return False

# 🔥 Helper: Check if the element matching the description is ACTIVE
def is_target_active(desc, dom_str):
    """
    Checks if the DOM line containing 'desc' also contains '[Active]'.
    """
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").strip()
    # Find line containing the description
    # Regex: [ID] ... desc ...
    # We escape clean_desc to handle special chars
    try:
        # Simple string check first for speed
        if clean_desc not in dom_str: return False
        
        # Look for the specific line
        lines = dom_str.split('\n')
        for line in lines:
            if clean_desc in line:
                if "[Active]" in line or 'class="active"' in line:
                    return True
    except: pass
    return False

# ==========================================
# 4. Core Brain A: Task Execution
# ==========================================
async def ask_brain_task(user_goal, dom_state, session_id, history_logs, instant_bans_map):
    print(f"⚡ [Task Brain] Goal: {user_goal}")
    
    current_hash = get_context_fingerprint(dom_state)
    context_specific_bans = instant_bans_map.get(current_hash, set())
    if context_specific_bans:
        print(f"🚫 Bans Active: {list(context_specific_bans)}")

    # 1. Loop Detection
    if len(history_logs) >= 4:
        last_three = history_logs[-3:]
        if last_three[0] == last_three[1] == last_three[2]:
            return json.dumps({"action": "message", "value": "Task Completed (Loop Detected)"})

    # 2. RAG Retrieval & Smart Logic
    demo_prompt = ""
    current_step_target = None
    should_stop = False
    
    try:
        demo_results = demo_collection.query(query_texts=[user_goal], n_results=1)
        if demo_results['documents'] and len(demo_results['documents'][0]) > 0:
            steps = json.loads(demo_results['metadatas'][0][0]['steps'])
            total_steps = len(steps)
            
            # A. Smart Step Selection (Reverse Goal Seek)
            target_step_idx = -1
            
            # Check backwards: Is the Final Step visible?
            for idx in range(total_steps - 1, -1, -1):
                step = steps[idx]
                desc = step.get('element_desc', '')
                if find_element_in_dom(desc, dom_state):
                    target_step_idx = idx
                    break 
            
            if target_step_idx == -1:
                target_step_idx = len(history_logs)

            # 🔥🔥 B. ZERO-CLICK COMPLETION CHECK
            # If we are targeting the Final Step (or beyond), check if it is ALREADY ACTIVE.
            if target_step_idx == total_steps - 1:
                target_step = steps[target_step_idx]
                desc = target_step.get('element_desc', '')
                
                if is_target_active(desc, dom_state):
                    print(f"🎉 Goal '{desc}' is already [Active]. Task Completed!")
                    return json.dumps({"action": "message", "value": "Task Completed (Goal Already Active)"})

            # C. Smart Stop (History Check)
            if history_logs and steps:
                if len(history_logs) >= total_steps + 1:
                    should_stop = True
            
            if target_step_idx < total_steps:
                target_step = steps[target_step_idx]
                action_type = target_step.get('action', {}).get('type')
                desc = target_step.get('element_desc', 'unknown')
                current_step_target = f"{action_type} on \"{desc}\""
                
                demo_prompt = f"### 🟢 SMART OBJECTIVE:\n"
                demo_prompt += f"Based on UI state, jump to Step {target_step_idx + 1} of {total_steps}.\n"
                demo_prompt += f"TARGET: {current_step_target}\n"
            else:
                should_stop = True
                demo_prompt = "### 🟢 STATUS:\nSteps appear complete.\n"

    except Exception as e:
        print(f"⚠️ RAG Demo Error: {e}")

    # 3. RAG Feedback
    rl_prompt = ""
    try:
        rl_query = f"Goal: {user_goal}\nContext: {dom_state[:500]}"
        rl_results = rl_collection.query(query_texts=[rl_query], n_results=5)
        if rl_results['documents'] and len(rl_results['documents'][0]) > 0:
            rl_prompt = "### 🔴 MISTAKES HISTORY:\n"
            for i, meta in enumerate(rl_results['metadatas'][0]):
                if meta['reward'] < 0:
                    rl_prompt += f"❌ FAILED previously: {meta['action']}\n"
            rl_prompt += "### END MISTAKES\n"
    except: pass

    # 4. System Prompt
    instruction = ""
    if should_stop:
        instruction = "Task completed. Return 'Task Completed' immediately."
    elif current_step_target:
        instruction = f"Find element matching: [{current_step_target}]. Do NOT return 'Task Completed' yet."
    else:
        instruction = "Follow demo steps."

    system_prompt = f"""
    You are a precise web automation agent.
    
    {demo_prompt}
    {rl_prompt}
    
    TASK: {instruction}
    
    🛑 RULES:
    1. **BANNED IDs**: {list(context_specific_bans)}. DO NOT CLICK.
    2. **SEMANTIC MATCH**: Use description to find the INTEGER ID.
    3. **SMART SKIPPING**: If target is visible, click it.
    4. **FINISH**: If {should_stop} is True, STOP and return "Task Completed".
    
    RESPONSE FORMAT:
    Step 1: Identify target.
    Step 2: Find matching ID.
    Step 3: Output JSON.
    
    ```json
    {{"action": "click", "id": "10", "value": "..."}}
    ```
    """
    
    user_prompt = f"GOAL: {user_goal}\nCURRENT VISIBLE UI:\n{dom_state}"
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0
        )
        result_str = clean_ai_response(response.choices[0].message.content.strip())
        
        # Validation Logic
        try:
            res_json = json.loads(result_str)
            
            if res_json.get('action') == 'message':
                return result_str

            target_id = str(res_json.get('id'))
            
            if not target_id.isdigit():
                 return json.dumps({"action": "message", "value": "Error: AI generated invalid ID format."})

            if target_id in context_specific_bans:
                return json.dumps({"action": "message", "value": f"Blocked banned ID {target_id}."})
            
            # Repetitive Click Guard
            if history_logs:
                last_log = history_logs[-1]
                if str(target_id) in last_log and res_json.get('action') == 'click':
                    print(f"🛡️ Repetitive Click. Assuming Task Done.")
                    return json.dumps({"action": "message", "value": "Task Completed"})

        except: pass

        return result_str

    except Exception as e:
        return json.dumps({"action": "error", "value": f"Task AI Error: {str(e)}"})

# ==========================================
# 5. Chat Brain
# ==========================================
async def ask_brain_chat(user_msg, dom_state, session_id):
    print(f"💬 [Chat Brain] User: {user_msg}")
    if session_id not in chat_history_cache:
        chat_history_cache[session_id] = [{"role": "system", "content": "You are a versatile AI assistant."}]
    history = chat_history_cache[session_id]
    history.append({"role": "user", "content": f"[Context]:\n{dom_state[:1000]}\n[Q]: {user_msg}"})
    try:
        res = await client.chat.completions.create(model=MODEL_NAME, messages=history, temperature=0.7)
        reply = res.choices[0].message.content
        if "<think>" in reply: reply = reply.split("</think>")[-1].strip()
        history.append({"role": "assistant", "content": reply})
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
    if session_id not in session_blacklists: session_blacklists[session_id] = {} 
    
    print(f"✅ Frontend Connected (Session: {session_id})")
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                payload = json.loads(raw_data)
                msg_type = payload.get('type')

                # A. Record
                if msg_type == 'record_event':
                    current_recording_session.append(payload)
                    save_raw_log(payload)
                    print(f"📹 [Rec] {payload.get('action',{}).get('type')}")
                    continue

                # B. Preview
                if msg_type == 'request_preview':
                    await websocket.send_text(json.dumps({"action": "preview_data", "data": current_recording_session}))
                    continue

                # C. Save Demo
                if msg_type == 'save_demo':
                    task_name = payload.get('name')
                    final_steps = payload.get('steps') or current_recording_session
                    if final_steps:
                        demo_collection.add(
                            documents=[task_name], 
                            metadatas=[{
                                "timestamp": datetime.datetime.now().isoformat(),
                                "steps": json.dumps(final_steps)
                            }],
                            ids=[f"demo_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({"type": "demo_saved", "name": task_name, "steps_count": len(final_steps)})
                        await websocket.send_text(json.dumps({"action": "message", "value": f"Skill Saved: {task_name}"}))
                        current_recording_session = [] 
                    continue

                # D. Instruction
                if 'instruction' in payload:
                    user_msg = payload.get("instruction")
                    dom_tree = payload.get("dom")
                    mode = payload.get("mode", "task")
                    is_new_task = payload.get("is_new_task", False)

                    if not dom_tree:
                        await websocket.send_text(json.dumps({"action": "message", "value": "⚠️ UI Retrieval Failed"}))
                        continue

                    if mode == 'chat':
                        response = await ask_brain_chat(user_msg, dom_tree, session_id)
                        await websocket.send_text(response)
                    else:
                        if is_new_task:
                            session_step_history[session_id] = []
                            # Keep session blacklist alive
                            print("🔄 New Task Started")

                        last_context_cache[session_id] = {"goal": user_msg, "dom_summary": dom_tree[:500], "full_dom": dom_tree}
                        
                        action_json_str = await ask_brain_task(
                            user_msg, 
                            dom_tree, 
                            session_id, 
                            session_step_history[session_id],
                            session_blacklists[session_id]
                        )
                        
                        try:
                            act_data = json.loads(action_json_str)
                            # Only log interactive actions with valid numeric IDs
                            if act_data.get('action') in ['click', 'type', 'select']:
                                if str(act_data.get('id')).isdigit():
                                    log = f"{act_data['action']} ID {act_data['id']}"
                                    session_step_history[session_id].append(log)
                        except: pass

                        print(f"🤖 Action: {action_json_str}")
                        await websocket.send_text(action_json_str)

                # E. Feedback
                if msg_type == 'feedback':
                    rating = payload.get('rating')
                    action_data = payload.get('action') 
                    context = last_context_cache.get(session_id)
                    
                    # Update Context Bans (Only if ID is numeric)
                    if rating < 0 and action_data and 'id' in action_data and context:
                        bad_id = str(action_data['id'])
                        if bad_id.isdigit():
                            ctx_hash = get_context_fingerprint(context['full_dom'])
                            if ctx_hash not in session_blacklists[session_id]:
                                session_blacklists[session_id][ctx_hash] = set()
                            session_blacklists[session_id][ctx_hash].add(bad_id)
                            print(f"🚫 Instant Context Ban: ID {bad_id} on Screen Hash [{ctx_hash[:6]}]")

                    if context:
                        rl_collection.add(
                            documents=[f"Goal: {context['goal']}\nUI: {context['dom_summary']}"],
                            metadatas=[{"action": json.dumps(action_data), "reward": rating}],
                            ids=[f"rl_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({"type": "feedback_event", "rating": rating, "action": action_data})
                        print(f"📈 Feedback: {rating}")

            except json.JSONDecodeError: pass
            
    except WebSocketDisconnect:
        if session_id in session_step_history: del session_step_history[session_id]
        if session_id in chat_history_cache: del chat_history_cache[session_id]
        if session_id in session_blacklists: del session_blacklists[session_id]
        print(f"🔌 Connection Closed")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    print("🚀 Server Starting...")
    uvicorn.run(app, host="0.0.0.0", port=8000)