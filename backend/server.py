import os
import sys
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import re
import json
import datetime
import hashlib
import uvicorn
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from openai import AsyncOpenAI
import chromadb
from sitemap_manager import SitemapManager
from image_utils import draw_grounding_marks
from dataset_recorder import DatasetRecorder

# ==========================================
# 1. Configuration & Initialization
# ==========================================

# AI Configuration
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1")
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "ollama")

TEXT_MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-r1:14b") 
VISION_MODEL_NAME = os.environ.get("VISION_MODEL_NAME", "qwen2.5vl")

print(f"🔌 Connecting to AI Engine: {OLLAMA_HOST}")
print(f"🧠 Text Model: {TEXT_MODEL_NAME}")
print(f"👁️ Vision Model: {VISION_MODEL_NAME}")

client = AsyncOpenAI(api_key=API_KEY, base_url=OLLAMA_HOST)
chroma_client = chromadb.PersistentClient(path="./agent_brain_db")
demo_collection = chroma_client.get_or_create_collection(name="demonstrations")
rl_collection = chroma_client.get_or_create_collection(name="rl_feedback")
DATASET_FILE = "user_trajectories.jsonl"
app = FastAPI()

# Components
sitemap = SitemapManager()
recorder = DatasetRecorder()

# Runtime Cache
current_recording_session = [] 
last_context_cache = {}        
session_step_history = {}      
chat_history_cache = {}
session_blacklists = {} 

# ==========================================
# 3. Helper Functions
# ==========================================
def clean_ai_response(content):
    """Robustly extract JSON from AI response."""
    try:
        print(f"\n🧠 [AI Reasoning Raw]:\n{content[:500]}...\n") 
        if "<think>" in content:
            content = content.split("</think>")[-1].strip()
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            matches = re.findall(r'(\{.*?\})', content, re.DOTALL)
            if matches: json_str = matches[-1] 
            else: return json.dumps({"action": "error", "value": "No JSON found"})
        data = json.loads(json_str)
        if 'action' in data and data['action'] in ['finish', 'return', 'done']:
            return json.dumps({"action": "message", "value": "Task Completed"})
        if 'action' in data and '|' in data['action']:
            data['action'] = 'click'
        if 'id' in data and data['id']:
            match = re.search(r'(\d+)', str(data['id']))
            if match: data['id'] = match.group(1)
        if 'value' not in data:
            data['value'] = ""
        return json.dumps(data)
    except Exception as e:
        print(f"❌ Parse Error: {e}")
        return json.dumps({"action": "error", "value": "JSON Parse Error"})

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
    clean_desc = desc.replace("[Sidebar]", "").replace("[Header]", "").replace("[Active]", "").strip()
    if not clean_desc: return None
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
        # Navigation elements check
        if "[Sidebar]" in line or "[Header]" in line or "[Breadcrumb]" in line: return False
        if action_type == 'click':
            if "[Active]" in line or 'class="active"' in line: return True
        if action_type in ['select', 'type'] and target_val:
            if f'Selected: "{target_val}"' in line: return True
            if f'Value: "{target_val}"' in line: return True
            if action_type == 'select' and target_val.lower() in line.lower() and "Selected:" in line: return True
    except: pass
    return False

def find_element_in_dom(desc, dom_str):
    if not desc: return False
    clean_desc = desc.replace("[Active]", "").strip()
    return clean_desc in dom_str

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
async def ask_brain_task(user_goal, dom_state, session_id, history_logs, instant_bans_map, marked_screenshot=None, raw_screenshot=None):
    
    # 🔄 RETRY LOOP
    MAX_RETRIES = 4
    last_error_context = ""
    
    # 🔥 Feedback Loop Integration
    if history_logs:
        last_log = history_logs[-1]
        if last_log.startswith("❌"):
            print(f"🚨 Frontend reported runtime error: {last_log}")
            last_error_context = f"RUNTIME ERROR: {last_log}. The previous action failed. You MUST fix this based on the error message."

    for attempt in range(MAX_RETRIES):
        print(f"⚡ [Task Brain] Goal: {user_goal} (Attempt {attempt+1}/{MAX_RETRIES})")
        
        current_hash = get_context_fingerprint(dom_state)
        context_specific_bans = instant_bans_map.get(current_hash, set())
        
        # Fail Fast
        max_allowed_steps = 15 
        if len(history_logs) >= max_allowed_steps:
            return json.dumps({"action": "finish", "value": f"Task Failed: Step limit ({max_allowed_steps}) reached."})

        # Sitemap
        map_url, map_reason = sitemap.find_best_page(user_goal)
        map_hint = f"🗺️ SITEMAP: Goal likely at {map_url} ({map_reason}). Navigate via Sidebar." if map_url else ""

        # RAG Logic
        demo_info = ""
        try:
            demo_results = demo_collection.query(query_texts=[user_goal], n_results=1)
            if demo_results['documents'] and len(demo_results['documents'][0]) > 0:
                demo_task_name = demo_results['documents'][0][0]
                steps = json.loads(demo_results['metadatas'][0][0]['steps'])
                total_steps = len(steps)
                
                # =========================================================
                # 🔥 LOGIC UPDATE: Calculate Effective Progress (Audit Logs)
                # =========================================================
                effective_history_count = 0
                for log in history_logs:
                    l = log.lower()
                    # Ignore non-advancing actions
                    if "scroll" in l or "scan" in l: continue
                    # Error means step failed, subtract count (retry)
                    if "error" in l or "fail" in l: 
                        effective_history_count = max(0, effective_history_count - 1)
                        continue
                    effective_history_count += 1
                
                cursor_idx = effective_history_count

                # Zero-Click Check (Only at end)
                if cursor_idx == total_steps - 1:
                    target_step = steps[cursor_idx]
                    desc = target_step.get('element_desc', '')
                    target_val = target_step.get('action', {}).get('value', '')
                    if user_goal.lower() == demo_task_name.lower():
                        if is_target_active_or_selected(desc, target_val, dom_state):
                            # Record Success
                            recorder.record_step(len(history_logs) + 1, {
                                "raw_screenshot": raw_screenshot, "marked_screenshot": marked_screenshot, "dom": dom_state,
                                "prompt": "System: Zero-Click Check", "response_raw": "Goal Active",
                                "action_json": {"action": "message", "value": "Task Completed"},
                                "attempt": 0, "model": "System"
                            })
                            return json.dumps({"action": "message", "value": "Task Completed (Goal Active)"})

                if cursor_idx < total_steps:
                    target_step = steps[cursor_idx]
                    action_type = target_step.get('action', {}).get('type')
                    desc = target_step.get('element_desc', 'unknown')
                    action_val = target_step.get('action', {}).get('value', '')
                    
                    suggested_id = find_id_by_desc(desc, dom_state)
                    
                    demo_info = f"--- GUIDANCE (Step {cursor_idx + 1}/{total_steps}) ---\nAction: {action_type}\nTarget: \"{desc}\"\nValue: \"{action_val}\""
                    
                    print(f"📚 [Memory] Following: '{demo_task_name}' (Step {cursor_idx + 1}/{total_steps})")
                    
                    if suggested_id:
                        if str(suggested_id) in context_specific_bans:
                            demo_info += f"\n🚫 WARNING: ID {suggested_id} is BANNED/STUCK. Find visual alternative!"
                            print(f"🚫 [Memory] ID {suggested_id} is banned.")
                        else:
                            demo_info += f"\n💡 HINT: Found at ID {suggested_id}."
                            print(f"🎯 [Memory] Target visible at ID {suggested_id}")
                    else:
                        # 🔥 MISSING ELEMENT STRATEGY: SCROLL 🔥
                        is_sidebar_target = "[Sidebar]" in desc
                        scroll_target = "sidebar:down" if is_sidebar_target else "down"
                        demo_info += f"\n⚠️ TARGET NOT VISIBLE IN DOM. Action required: 'scroll' (value: '{scroll_target}')."
                        print(f"🔻 [Memory] Target '{desc}' NOT FOUND. Suggesting SCROLL ({scroll_target}).")

        except Exception as e: print(f"⚠️ RAG Error: {e}")

        instruction = "Use GUIDANCE. If banned, find alternative." if demo_info else "Use SITEMAP."

        # Vision Switching
        use_vision = marked_screenshot and (attempt <= 1) 
        messages_payload = []
        used_model = ""

        # 🔥 Error Injection
        error_injection = ""
        if last_error_context:
            error_injection = f"\n❌ CRITICAL FEEDBACK: {last_error_context}\n👉 CORRECTION REQUIRED: Fix this error immediately."

        if use_vision:
            print(f"👁️ Using Vision Brain ({VISION_MODEL_NAME})...")
            used_model = VISION_MODEL_NAME
            system_prompt = f"""
            You are a GUI Agent.
            GOAL: "{user_goal}"
            TASK: {instruction}
            INPUTS: Image with RED BOXES + WHITE IDs.
            
            RULES:
            1. Find element matching GOAL. Use Numeric ID from RED BOX.
            2. 'id' is MANDATORY (unless action is scroll).
            3. 'select'/'type' actions MUST have 'value'.
            4. If GUIDANCE says SCROLL, output action: "scroll", value: "down" (or "sidebar:down").
            {error_injection}
            
            OUTPUT JSON ONLY:
            ```json
            {{"action": "click", "id": "10", "value": ""}}
            OR
            {{"action": "scroll", "id": "", "value": "down"}}
            ```
            """
            
            messages_payload = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": system_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{marked_screenshot}"}},
                        {"type": "text", "text": f"Context:\n{dom_state[:1000]}\n\n{demo_info}\n\nAnalyze image and output JSON."}
                    ]
                }
            ]
        else:
            print("🧠 Using Text Brain (Logic Fallback)...")
            used_model = TEXT_MODEL_NAME
            system_prompt = f"""
            You are a JSON generator.
            GOAL: "{user_goal}"
            CONTEXT:
            - BANNED: {list(context_specific_bans)}
            - MEMORY: {demo_info}
            {error_injection}
            
            INSTRUCTIONS:
            1. Find ID matching GOAL.
            2. If <select>, action MUST be 'select'.
            3. If MEMORY advises SCROLL, output action "scroll".
            
            FORMAT:
            ```json
            {{"action": "select", "id": "123", "value": "TargetValue"}}
            OR
            {{"action": "scroll", "id": "", "value": "down"}}
            ```
            """
            messages_payload = [
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": f"DOM TREE:\n{dom_state}"} 
            ]

        try:
            # 🔥 Enable JSON Mode
            response = await client.chat.completions.create(
                model=used_model,
                messages=messages_payload,
                temperature=0.0,
                response_format={"type": "json_object"} 
            )
            raw_response_content = response.choices[0].message.content
            result_str = clean_ai_response(raw_response_content)
            
            try:
                res_json = json.loads(result_str)
                recorder.record_step(len(history_logs) + 1, {
                    "raw_screenshot": raw_screenshot, "marked_screenshot": marked_screenshot, "dom": dom_state,
                    "prompt": str(messages_payload), "response_raw": raw_response_content,
                    "action_json": res_json, "attempt": attempt, "model": used_model
                })

                if res_json.get('action') == 'message': return result_str
                
                # 🔥 Pass through SCROLL actions immediately
                if res_json.get('action') == 'scroll':
                    return json.dumps(res_json)

                target_id = str(res_json.get('id', ''))
                target_id = resolve_dom_id(target_id, dom_state)
                res_json['id'] = target_id 

                # Validations
                if not target_id.isdigit(): 
                    print(f"⚠️ Invalid ID. Retrying...")
                    last_error_context = f"ID '{target_id}' is invalid. Use numeric ID."
                    continue 
                
                if target_id in context_specific_bans:
                    print(f"⚠️ Banned ID. Retrying...")
                    last_error_context = f"ID {target_id} is BANNED. Choose another."
                    continue 

                is_valid, real_text = verify_id_in_dom(target_id, dom_state)
                if not is_valid: return json.dumps({"action": "message", "value": f"Error: ID {target_id} not found."})
                
                # 🔥 Semantic Action Logging
                print(f"🎯 Target Identified: [ID {target_id}] -> \"{real_text}\"")

                action_type = res_json.get('action')
                target_val = res_json.get('value', '')

                if is_state_satisfied(target_id, action_type, target_val, dom_state):
                    return json.dumps({"action": "message", "value": "Task Completed (State Satisfied)"})

                # Loop Check
                if history_logs:
                    last_log = history_logs[-1]
                    if str(target_id) in last_log and action_type == 'click' and not last_log.startswith("❌"):
                        print(f"🔄 Loop detected. Banning...")
                        if current_hash not in instant_bans_map: instant_bans_map[current_hash] = set()
                        instant_bans_map[current_hash].add(target_id)
                        last_error_context = f"Action on ID {target_id} had no effect. It is BANNED."
                        continue 
                
                return json.dumps(res_json)

            except: pass
            return result_str
        except Exception as e: return json.dumps({"action": "error", "value": f"Task AI Error: {str(e)}"})
    
    return json.dumps({"action": "finish", "value": f"Task Failed: {last_error_context or 'Retries exhausted'}."})

async def ask_brain_chat(user_msg, dom_state, session_id):
    print(f"💬 [Chat Brain] User: {user_msg}")
    if session_id not in chat_history_cache: chat_history_cache[session_id] = [{"role": "system", "content": "Assistant."}]
    history = chat_history_cache[session_id]
    history.append({"role": "user", "content": f"Context:\n{dom_state[:500]}\nQ: {user_msg}"})
    try:
        res = await client.chat.completions.create(model=TEXT_MODEL_NAME, messages=history, temperature=0.7)
        reply = res.choices[0].message.content
        if "<think>" in reply: reply = reply.split("</think>")[-1].strip()
        history.append({"role": "assistant", "content": reply})
        return json.dumps({"action": "message", "value": reply})
    except Exception as e: return json.dumps({"action": "message", "value": f"Chat Error: {str(e)}"})

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
                
                if msg_type == 'sitemap_init':
                    sitemap.sync_skeleton(payload.get('routes', []), payload.get('version', 'v1')); continue
                
                if msg_type == 'record_event':
                    if payload.get('visual_crop'):
                        crop_b64 = payload.pop('visual_crop')
                        filename_crop = f"crop_{int(datetime.datetime.now().timestamp())}_{str(uuid.uuid4())[:6]}.jpg"
                        payload['crop_image_path'] = recorder.save_demo_image(crop_b64, filename_crop)
                        print(f"📸 Visual Anchor saved: {filename_crop}")

                    if payload.get('screenshot'):
                        full_b64 = payload.pop('screenshot')
                        filename_full = f"full_{int(datetime.datetime.now().timestamp())}_{str(uuid.uuid4())[:6]}.jpg"
                        payload['full_image_path'] = recorder.save_demo_image(full_b64, filename_full)
                        print(f"📸 Full Screen saved: {filename_full}")

                    current_recording_session.append(payload)
                    save_raw_log(payload)
                    continue

                if msg_type == 'request_preview':
                    await websocket.send_text(json.dumps({"action": "preview_data", "data": current_recording_session})); continue
                if msg_type == 'save_demo':
                    task_name = payload.get('name')
                    final_steps = payload.get('steps') or current_recording_session
                    if final_steps:
                        demo_collection.add(
                            documents=[task_name], 
                            metadatas=[{"timestamp": datetime.datetime.now().isoformat(), "steps": json.dumps(final_steps)}],
                            ids=[f"demo_{datetime.datetime.now().timestamp()}"]
                        )
                        save_raw_log({"type": "demo_saved", "name": task_name})
                        await websocket.send_text(json.dumps({"action": "message", "value": f"Skill Saved: {task_name}"}))
                        current_recording_session = [] 
                    continue

                if msg_type == 'client_error':
                    error_msg = payload.get('error')
                    print(f"🚨 Client reported error: {error_msg}")
                    
                    session_step_history[session_id].append(error_msg)
                    
                    dom_tree = payload.get("dom")
                    raw_screenshot = payload.get("screenshot") 
                    elements_meta = payload.get("elements_meta")
                    marked_screenshot_b64 = draw_grounding_marks(raw_screenshot, elements_meta)
                    
                    ctx = last_context_cache.get(session_id, {})
                    user_msg = ctx.get('goal', 'Continue task')

                    recorder.record_step(len(session_step_history[session_id]), {
                        "raw_screenshot": raw_screenshot, 
                        "marked_screenshot": marked_screenshot_b64, 
                        "dom": dom_tree,
                        "prompt": "Client-Side Feedback Loop", 
                        "response_raw": f"Frontend rejected previous action: {error_msg}",
                        "action_json": {"action": "error", "value": error_msg},
                        "attempt": 0, "model": "Frontend Guard"
                    })

                    action_json_str = await ask_brain_task(
                        user_msg, 
                        dom_tree, 
                        session_id, 
                        session_step_history[session_id], 
                        session_blacklists[session_id],
                        marked_screenshot=marked_screenshot_b64, 
                        raw_screenshot=raw_screenshot
                    )
                    
                    print(f"🤖 Correction Action: {action_json_str}")
                    await websocket.send_text(action_json_str)
                    continue

                if 'instruction' in payload:
                    user_msg = payload.get("instruction")
                    dom_tree = payload.get("dom")
                    raw_screenshot = payload.get("screenshot") 
                    elements_meta = payload.get("elements_meta")
                    marked_screenshot_b64 = draw_grounding_marks(raw_screenshot, elements_meta)
                    page_structure = payload.get("page_structure")
                    if page_structure: sitemap.update_flesh(page_structure)
                    
                    mode = payload.get("mode", "task")
                    is_new_task = payload.get("is_new_task", False)
                    if not dom_tree: await websocket.send_text(json.dumps({"action": "message", "value": "UI Error"})); continue
                    
                    if mode == 'chat': await websocket.send_text(await ask_brain_chat(user_msg, dom_tree, session_id))
                    else:
                        if is_new_task:
                            session_step_history[session_id] = []
                            session_blacklists[session_id] = {} 
                            print("🔄 New Task Started")
                            recorder.start_new_session(user_msg)
                        
                        last_context_cache[session_id] = {"goal": user_msg, "dom_summary": dom_tree[:500], "full_dom": dom_tree}
                        
                        action_json_str = await ask_brain_task(
                            user_msg, dom_tree, session_id, session_step_history[session_id], session_blacklists[session_id],
                            marked_screenshot=marked_screenshot_b64, raw_screenshot=raw_screenshot
                        )
                        
                        try:
                            act_data = json.loads(action_json_str)
                            if act_data.get('action') in ['click', 'type', 'select']:
                                if str(act_data.get('id')).isdigit():
                                    val = act_data.get('value', '')
                                    log = f"{act_data['action']} ID {act_data['id']} (Val: {val})"
                                    session_step_history[session_id].append(log)
                            # 🔥 Also Log Scrolls
                            if act_data.get('action') == 'scroll':
                                session_step_history[session_id].append(f"scroll {act_data.get('value', 'down')}")
                        except: pass
                        print(f"🤖 Action: {action_json_str}")
                        await websocket.send_text(action_json_str)

                if msg_type == 'feedback':
                    rating = payload.get('rating') # 1 (Good) or -1 (Bad)
                    action_data = payload.get('action') # The action JSON that was rated
                    
                    if rating and action_data:
                        feedback_id = f"rl_{int(datetime.datetime.now().timestamp())}_{str(uuid.uuid4())[:8]}"
                        print(f"👍/👎 Feedback Received: {rating} for action {action_data}")
                        
                        # 1. Store in ChromaDB for RLHF / DPO
                        rl_collection.add(
                            documents=[json.dumps(action_data)],
                            metadatas=[{
                                "rating": rating,
                                "timestamp": datetime.datetime.now().isoformat(),
                                "source": "user_ui"
                            }],
                            ids=[feedback_id]
                        )
                        
                        # 2. [RESTORED] Save Raw Log to JSONL
                        save_raw_log({
                            "type": "feedback",
                            "rating": rating,
                            "target_action": action_data,
                            "timestamp": datetime.datetime.now().isoformat()
                        })
                    continue

            except json.JSONDecodeError: pass
    except WebSocketDisconnect: pass
    except Exception as e: print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🚀 Server Starting...")
    uvicorn.run(app, host="0.0.0.0", port=8000)