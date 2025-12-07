import chromadb
import json
import sys

# Initialize Client
client = chromadb.PersistentClient(path="./agent_brain_db")
demo_coll = client.get_collection("demonstrations")
rl_coll = client.get_collection("rl_feedback")

def list_all_demos():
    """List all saved skills/demonstrations"""
    print("\n📋 === Current Skills (Demonstrations) ===")
    data = demo_coll.get()
    
    if not data['ids']:
        print("(No demonstrations found)")
        return

    for i, doc_id in enumerate(data['ids']):
        task_name = data['documents'][i]
        meta = data['metadatas'][i]
        timestamp = meta.get('timestamp', 'unknown')
        print(f"[{i}] ID: {doc_id} | Task: {task_name} | Time: {timestamp}")

def search_memory(query):
    """Search for a specific memory to see what the AI retrieves"""
    print(f"\n🔍 === Searching for: '{query}' ===")
    
    results = demo_coll.query(query_texts=[query], n_results=3)
    
    if not results['ids'][0]:
        print("(No matching memories found)")
        return

    for i, doc_id in enumerate(results['ids'][0]):
        task_name = results['documents'][0][i]
        distance = results['distances'][0][i]
        print(f"[{i}] Match Score: {distance:.4f} | Task: {task_name} | ID: {doc_id}")
        
        # Print details of the best match
        if i == 0:
            meta = results['metadatas'][0][i]
            steps = json.loads(meta['steps'])
            print("    --- Steps Content ---")
            for idx, step in enumerate(steps):
                act = step.get('action', {})
                desc = step.get('element_desc', 'N/A')
                print(f"    {idx+1}. {act.get('type')} -> {desc}")

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
                # Re-create empty
                rl_coll = client.create_collection("rl_feedback")
                print("✅ RL Feedback cleared.")
        elif choice == 'q':
            break
        else:
            print("Invalid option")

if __name__ == "__main__":
    main()