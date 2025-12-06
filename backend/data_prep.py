import json
import os

INPUT_FILE = "user_trajectories.jsonl"
OUTPUT_FILE = "train_dataset.json"

def format_system_prompt(dom_state):
    return f"""You are an intelligent web agent.
Task: Generate the NEXT single JSON action.

CRITICAL RULES:
1. ID MATCHING: Use the exact numeric ID from 'CURRENT VISIBLE UI'.
2. Output JSON ONLY. Format: {{"action": "click|type|select", "id": "...", "value": "..."}}

CURRENT VISIBLE UI:
{dom_state}
"""

def process_logs():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Log file not found: {INPUT_FILE}")
        return

    print("⏳ Processing logs...")
    
    buffer_steps = []
    final_dataset = []
    
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)
                msg_type = entry.get('type')
                
                # 1. Collect steps
                if msg_type == 'record_event':
                    buffer_steps.append(entry)
                    
                # 2. Found Save Marker
                elif msg_type in ['demo_saved', 'save_demo', 'demo_completed']:
                    task_name = entry.get('name') or entry.get('task_name')
                    
                    if not task_name: 
                        print("⚠️ Unnamed task, skipping")
                        buffer_steps = []
                        continue

                    if buffer_steps:
                        print(f"✅ Extracted Task: '{task_name}' ({len(buffer_steps)} steps)")
                        
                        for step in buffer_steps:
                            dom_snippet = step.get('element_desc', '')
                            action = step.get('action', {})
                            
                            target_id = action.get('target_id')
                            if not target_id or target_id == 'UNKNOWN':
                                continue 

                            clean_action = {
                                "action": action.get('type'),
                                "id": target_id,
                                "value": action.get('value', '')
                            }
                            
                            sample = {
                                "instruction": f"USER GOAL: {task_name}",
                                "input": format_system_prompt(dom_snippet),
                                "output": json.dumps(clean_action)
                            }
                            final_dataset.append(sample)
                        
                        buffer_steps = [] 
                    else:
                        print(f"⚠️ Task '{task_name}' has no steps")

            except json.JSONDecodeError:
                continue

    if final_dataset:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_dataset, f, indent=2, ensure_ascii=False)
        print(f"🎉 Success! Generated {len(final_dataset)} training samples -> {OUTPUT_FILE}")
    else:
        print("⚠️ No valid data extracted.")

if __name__ == "__main__":
    process_logs()