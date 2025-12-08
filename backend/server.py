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
        
        if 'action' in data and data['action'] in ['finish', 'return', 'done']:
            return json.dumps({"action": "message", "value": "Task Completed"})

        # Sanitize Action
        if 'action' in data and '|' in data['action']:
            data['action'] = 'click'

        if 'id' in data:
            match = re.search(r'(\d+)', str(data['id']))
            if match: data['id'] = match.group(1)
            else: pass 

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

def find_id_by_desc(desc, dom_str):
    if not desc: return None
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").strip()
    clean_desc = re.escape(clean_desc)
    pattern = re.compile(rf'\[(\d+)\]\s*<[^>]+>\s*".*?{clean_desc}.*?"', re.IGNORECASE)
    match = pattern.search(dom_str)
    if match: return match.group(1)
    return None

def verify_id_in_dom(target_id, dom_str):
    pattern = re.compile(rf'\[{target_id}\].*?\"(.*?)\"', re.IGNORECASE)
    match = pattern.search(dom_str)
    if not match: return False, None
    return True, match.group(1)

def is_select_element(target_id, dom_str):
    pattern = re.compile(rf'\[{target_id}\]\s*<select', re.IGNORECASE)
    if pattern.search(dom_str): return True
    return False

def resolve_dom_id(target_id, dom_str):
    raw_id = str(target_id).strip()
    if raw_id.isdigit(): return raw_id
    try:
        clean = re.escape(raw_id)
        pattern = re.compile(rf'\[(\d+)\][^>]*\b(?:id|name|data-testid)=[\"\']{clean}[\"\']', re.IGNORECASE)
        match = pattern.search(dom_str)
        if match: return match.group(1)
    except: pass
    return raw_id

def is_state_satisfied(target_id, action_type, target_val, dom_str):
    try:
        pattern = re.compile(rf'\[{target_id}\].*?$', re.MULTILINE | re.IGNORECASE)
        match = pattern.search(dom_str)
        if not match: return False
        
        line = match.group(0)
        
        if action_type == 'click':
            if "[Active]" in line or 'class="active"' in line: return True
        
        if action_type in ['select', 'type'] and target_val:
            if f'Selected: "{target_val}"' in line: return True
            if f'Value: "{target_val}"' in line: return True
            if action_type == 'select' and target_val.lower() in line.lower() and "Selected:" in line:
                return True
    except: pass
    return False

def find_element_in_dom(desc, dom_str):
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").strip()
    if clean_desc in dom_str: return True
    return False

def is_target_active_or_selected(desc, target_val, dom_str):
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").strip()
    try:
        if clean_desc not in dom_str: return False
        lines = dom_str.split('\n')
        for line in lines:
            if clean_desc in line:
                if "[Active]" in line or 'class="active"' in line: return True
                if target_val:
                    if f'Selected: "{target_val}"' in line: return True
                    if f'Value: "{target_val}"' in line: return True
    except: pass
    return False

# ==========================================
# 4. Core Brain A: Task Execution
# ==========================================
async def ask_brain_task(user_goal, dom_state, session_id, history_logs, instant_bans_map):
    print(f"⚡ [Task Brain] Goal: {user_goal}")
    
    current_hash = get_context_fingerprint(dom_state)
    context_specific_bans = instant_bans_map.get(current_hash, set())
    if context_specific_bans: print(f"🚫 Bans Active: {list(context_specific_bans)}")

    # 1. Loop Detection
    if len(history_logs) >= 6: # Give more room for exploration
        last_three = history_logs[-3:]
        if last_three[0] == last_three[1] == last_three[2]:
            return json.dumps({"action": "message", "value": "Task Completed (Loop Detected)"})

    # 2. RAG Retrieval & Dynamic Cursor
    demo_info = ""
    should_stop = False
    
    try:
        demo_results = demo_collection.query(query_texts=[user_goal], n_results=1)
        if demo_results['documents'] and len(demo_results['documents'][0]) > 0:
            demo_task_name = demo_results['documents'][0][0]
            steps = json.loads(demo_results['metadatas'][0][0]['steps'])
            total_steps = len(steps)
            
            # 🔥🔥 DYNAMIC CURSOR: Determine where we are based on UI, NOT History
            cursor_idx = -1
            
            # 1. Reverse Check: Are we already at a later step?
            for idx in range(total_steps - 1, -1, -1):
                step = steps[idx]
                desc = step.get('element_desc', '')
                if find_element_in_dom(desc, dom_state):
                    cursor_idx = idx
                    break # Found the furthest visible step
            
            # 2. Fallback: If no future steps visible, default to start (or handle lost state)
            # We don't rely on history length because user might have clicked around.
            if cursor_idx == -1:
                # If nothing visible, maybe we are at start? Or completely lost?
                # Check if we have history. If history is empty, assume start (0).
                # If history exists, maybe we keep looking for Step 0?
                cursor_idx = 0 

            # 3. State Completion Check (Zero-Click)
            # If the cursor points to the last step, check if it's already done
            if cursor_idx == total_steps - 1:
                target_step = steps[cursor_idx]
                desc = target_step.get('element_desc', '')
                target_val = target_step.get('action', {}).get('value', '')
                if is_target_active_or_selected(desc, target_val, dom_state):
                    # Only complete if goals match, otherwise might need value adaptation
                    if user_goal.lower() == demo_task_name.lower():
                        return json.dumps({"action": "message", "value": "Task Completed (Goal State Active)"})

            # 4. Soft Stop (Buffer Limit)
            # Allow 2x buffer for exploration
            if history_logs and len(history_logs) >= total_steps * 2 + 2:
                should_stop = True
                print(f"🛑 Buffer Stop: History({len(history_logs)}) exceeds Limit.")

            # 5. Construct Guidance
            if cursor_idx < total_steps:
                target_step = steps[cursor_idx]
                action_type = target_step.get('action', {}).get('type')
                desc = target_step.get('element_desc', 'unknown')
                action_val = target_step.get('action', {}).get('value', '')
                
                # Find Hint
                suggested_id = find_id_by_desc(desc, dom_state)
                
                adaptation_hint = ""
                if user_goal.lower() != demo_task_name.lower() and action_type in ['select', 'type']:
                    adaptation_hint = f"\n⚠️ ADAPTATION: User Goal is '{user_goal}'. REPLACE Demo Value '{action_val}' with User Goal."
                
                if suggested_id:
                    adaptation_hint += f"\n💡 HINT: Target \"{desc}\" found at ID {suggested_id}."

                demo_info = f"--- DYNAMIC GUIDANCE (Matching Step {cursor_idx + 1}/{total_steps}) ---\n"
                demo_info += f"Recommended Action: {action_type}\n"
                demo_info += f"Target: \"{desc}\"\n"
                demo_info += f"Demo Value: \"{action_val}\"\n"
                demo_info += adaptation_hint
                
            else:
                should_stop = True

    except Exception as e: print(f"⚠️ RAG Error: {e}")

    # 3. Prompt
    instruction = ""
    if should_stop: instruction = "Task limit reached. Check if goal is met or return 'Task Completed'."
    elif demo_info: instruction = "Use DYNAMIC GUIDANCE to proceed. You may explore if needed, but prioritize the Guidance."
    else: instruction = "No memory found. Analyze UI to solve."

    system_prompt = f"""
    You are an intelligent web automation agent.
    
    TASK: {instruction}
    
    🛑 RULES:
    1. **FLEXIBILITY**: The Guidance matches the current UI state. Follow it if it makes sense.
    2. **ADAPT VALUES**: Change Demo Value if User Goal differs.
    3. **ID FORMAT**: Use ONLY the INTEGER index from `[10]`.
    4. **BANNED IDs**: {list(context_specific_bans)}.
    5. **FINISH**: If task is clearly done, return "Task Completed".
    
    RESPONSE FORMAT:
    Step 1: Analyze Guidance vs UI.
    Step 2: Decide Value (Adapt if needed).
    Step 3: Output JSON.
    ```json
    {{"action": "click", "id": "10", "value": "..."}}
    ```
    """
    
    user_prompt = f"GOAL: {user_goal}\nCURRENT VISIBLE UI:\n{dom_state}\n\n{demo_info}"
    
    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.0
        )
        result_str = clean_ai_response(response.choices[0].message.content.strip())
        
        # --- POST-PROCESSING ---
        try:
            res_json = json.loads(result_str)
            if res_json.get('action') == 'message': return result_str

            target_id = str(res_json.get('id', ''))
            target_id = resolve_dom_id(target_id, dom_state)
            res_json['id'] = target_id 

            # 🔥 REMOVED HARD PYTHON OVERRIDE
            # We trust the AI + Hint now. We don't force target_id = suggested_id.
            
            if not target_id.isdigit(): return json.dumps({"action": "message", "value": f"Error: Invalid ID '{target_id}'."})
            if target_id in context_specific_bans: return json.dumps({"action": "message", "value": f"Blocked banned ID {target_id}."})
            
            is_valid, real_text = verify_id_in_dom(target_id, dom_state)
            if not is_valid: return json.dumps({"action": "message", "value": f"Error: ID {target_id} not found."})
            
            action_type = res_json.get('action')
            target_val = res_json.get('value', '')

            # Action Logic
            if is_select_element(target_id, dom_state):
                res_json['action'] = 'select'
                action_type = 'select'
            elif action_type == 'click':
                res_json['value'] = real_text 

            # State Check
            if is_state_satisfied(target_id, action_type, target_val, dom_state):
                return json.dumps({"action": "message", "value": "Task Completed (State Satisfied)"})

            # Debounce
            if history_logs:
                last_log = history_logs[-1]
                if str(target_id) in last_log:
                    if action_type == 'click':
                        return json.dumps({"action": "message", "value": "Task Completed"})
                    elif action_type in ['select', 'type'] and target_val in last_log:
                         return json.dumps({"action": "message", "value": "Task Completed"})
            
            return json.dumps(res_json)

        except Exception as e:
            pass

        return result_str

    except Exception as e: return json.dumps({"action": "error", "value": f"Task AI Error: {str(e)}"})

# ==========================================
# 5. Chat Brain
# ==========================================
async def ask_brain_chat(user_msg, dom_state, session_id):
    if session_id not in chat_history_cache: chat_history_cache[session_id] = [{"role": "system", "content": "Assistant."}]
    history = chat_history_cache[session_id]
    history.append({"role": "user", "content": f"Context:\n{dom_state[:500]}\nQ: {user_msg}"})
    try:
        res = await client.chat.completions.create(model=MODEL_NAME, messages=history, temperature=0.7)
        reply = res.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        return json.dumps({"action": "message", "value": reply})
    except Exception as e: return json.dumps({"action": "message", "value": str(e)})

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

                if msg_type == 'record_event':
                    current_recording_session.append(payload)
                    payload['type'] = 'feedback_event' 
                    save_raw_log(payload)
                    print(f"📹 [Rec] {payload.get('action',{}).get('type')} on {payload.get('element_desc')}") 
                    continue

                if msg_type == 'request_preview':
                    await websocket.send_text(json.dumps({"action": "preview_data", "data": current_recording_session}))
                    continue

                if msg_type == 'save_demo':
                    task_name = payload.get('name')
                    final_steps = payload.get('steps') or current_recording_session
                    if final_steps:
                        demo_collection.add(
                            documents=[task_name], 
                            metadatas=[{"timestamp": datetime.datetime.now().isoformat(), "steps": json.dumps(final_steps)}],
                            ids=[f"demo_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({"type": "demo_saved", "name": task_name, "steps": len(final_steps)})
                        await websocket.send_text(json.dumps({"action": "message", "value": f"Skill Saved: {task_name}"}))
                        current_recording_session = [] 
                    continue

                if 'instruction' in payload:
                    user_msg = payload.get("instruction")
                    dom_tree = payload.get("dom")
                    mode = payload.get("mode", "task")
                    is_new_task = payload.get("is_new_task", False)
                    if not dom_tree:
                        await websocket.send_text(json.dumps({"action": "message", "value": "UI Error"}))
                        continue
                    if mode == 'chat':
                        await websocket.send_text(await ask_brain_chat(user_msg, dom_tree, session_id))
                    else:
                        if is_new_task:
                            session_step_history[session_id] = []
                            session_blacklists[session_id] = {} # Clear bans on new task
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
                            if act_data.get('action') in ['click', 'type', 'select']:
                                if str(act_data.get('id')).isdigit():
                                    val = act_data.get('value', '')
                                    log = f"{act_data['action']} ID {act_data['id']} (Val: {val})"
                                    session_step_history[session_id].append(log)
                        except: pass

                        print(f"🤖 Action: {action_json_str}")
                        await websocket.send_text(action_json_str)

                if msg_type == 'feedback':
                    rating = payload.get('rating')
                    action_data = payload.get('action') 
                    context = last_context_cache.get(session_id)
                    
                    if rating < 0 and action_data and 'id' in action_data and context:
                        bad_id = str(action_data['id'])
                        if bad_id.isdigit():
                            ctx_hash = get_context_fingerprint(context['full_dom'])
                            if ctx_hash not in session_blacklists[session_id]:
                                session_blacklists[session_id][ctx_hash] = set()
                            session_blacklists[session_id][ctx_hash].add(bad_id)
                            print(f"🚫 Ban ID {bad_id}")

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
        print(f"🔌 Closed Session {session_id}")
        del session_step_history[session_id]
        if session_id in chat_history_cache: del chat_history_cache[session_id]
        if session_id in session_blacklists: del session_blacklists[session_id]
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    print("🚀 Server Starting...")
    uvicorn.run(app, host="0.0.0.0", port=8000)