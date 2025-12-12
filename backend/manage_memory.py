import chromadb
import json
import sys
from datetime import datetime

# Initialize Client
# Preserving your original path configuration
client = chromadb.PersistentClient(path="./agent_brain_db")
demo_coll = client.get_collection("demonstrations")
# Try/Except block in case rl_feedback doesn't exist yet
try:
    rl_coll = client.get_collection("rl_feedback")
except:
    rl_coll = client.create_collection("rl_feedback")

def list_all_demos():
    """List all saved skills/demonstrations"""
    print("\n📋 === Current Skills (Demonstrations) ===")
    # Getting all metadata to list them
    data = demo_coll.get()
    
    if not data['ids']:
        print("(No demonstrations found)")
        return

    print(f"{'ID':<30} | {'Time':<20} | {'Task'}")
    print("-" * 80)

    for i, doc_id in enumerate(data['ids']):
        task_name = data['documents'][i]
        meta = data['metadatas'][i]
        timestamp = meta.get('timestamp', 'unknown')
        
        # Format timestamp if possible
        try:
            ts_obj = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp = ts_obj.strftime('%Y-%m-%d %H:%M')
        except:
            pass

        print(f"{doc_id:<30} | {timestamp:<20} | {task_name}")

def search_memory(query):
    """Search for a specific memory to see what the AI retrieves"""
    print(f"\n🔍 === Searching for: '{query}' ===")
    
    results = demo_coll.query(query_texts=[query], n_results=3)
    
    if not results['ids'] or not results['ids'][0]:
        print("(No matching memories found)")
        return

    for i, doc_id in enumerate(results['ids'][0]):
        task_name = results['documents'][0][i]
        distance = results['distances'][0][i]
        print(f"[{i}] Match Score: {distance:.4f} | Task: {task_name} | ID: {doc_id}")

def inspect_demo_steps(doc_id):
    """
    Detailed inspection of a specific demo ID.
    Handles both legacy and new data formats for steps.
    """
    print(f"\n🕵️‍♂️ === Inspecting Demo: {doc_id} ===")
    
    # Fetch specific ID
    result = demo_coll.get(ids=[doc_id])
    
    if not result['ids']:
        print(f"❌ ID '{doc_id}' not found.")
        return

    task_name = result['documents'][0]
    meta = result['metadatas'][0]
    timestamp = meta.get('timestamp', 'unknown')

    print(f"Task: {task_name}")
    print(f"Time: {timestamp}")
    print("-" * 60)
    print(f"{'#':<3} | {'Action':<10} | {'Target ID':<10} | {'Value':<15} | {'Desc'}")
    print("-" * 60)

    try:
        # Steps are stored as a JSON string in metadata
        steps_json = meta.get('steps', '[]')
        steps = json.loads(steps_json)

        for idx, step in enumerate(steps):
            # --- Robust Data Extraction Logic ---
            
            # 1. Action (Try new flattened format first, then legacy nested, then event_type)
            action = step.get('action')
            if isinstance(action, dict): 
                # Handle legacy nested format: action: { type: "click" }
                action = action.get('type', 'N/A')
            elif not action:
                # Handle frontend legacy format: event_type: "click"
                action = step.get('event_type', 'N/A')

            # 2. Target ID (Try 'id' then 'target_id')
            target_id = step.get('id') or step.get('target_id') or 'N/A'

            # 3. Value
            val = step.get('value', '')
            
            # 4. Description
            desc = step.get('element_desc') or step.get('text_content', 'N/A')
            if len(desc) > 30: desc = desc[:27] + "..."

            print(f"{idx+1:<3} | {action:<10} | {target_id:<10} | {val:<15} | {desc}")

    except Exception as e:
        print(f"❌ Error parsing steps: {e}")
        print("Raw Steps Data:", meta.get('steps', ''))

def delete_memory(doc_id):
    """Delete a specific memory by ID"""
    try:
        demo_coll.delete(ids=[doc_id])
        print(f"✅ Successfully deleted memory: {doc_id}")
    except Exception as e:
        print(f"❌ Error deleting: {e}")

def main():
    while True:
        print("\n🔧 Memory Management Tool")
        print("1. List all demos")
        print("2. Search memory (Simulate AI retrieval)")
        print("3. Delete a demo (by ID)")
        print("4. Clear ALL RL feedback (Reset bad habits)")
        print("5. Inspect demo details (List steps) [NEW]")
        print("q. Quit")
        
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            list_all_demos()
        elif choice == '2':
            q = input("Enter user goal to search: ")
            search_memory(q)
        elif choice == '3':
            id_to_del = input("Enter ID to delete (e.g., demo_171...): ")
            delete_memory(id_to_del)
        elif choice == '4':
            confirm = input("Are you sure you want to delete ALL RL feedback? (y/n): ")
            if confirm.lower() == 'y':
                client.delete_collection("rl_feedback")
                rl_coll = client.create_collection("rl_feedback")
                print("✅ RL Feedback cleared.")
        elif choice == '5':
            # 🔥 New Option
            id_to_inspect = input("Enter Demo ID to inspect: ").strip()
            inspect_demo_steps(id_to_inspect)
        elif choice == 'q':
            break
        else:
            print("Invalid option")

if __name__ == "__main__":
    main()