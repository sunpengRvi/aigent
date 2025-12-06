import chromadb
import json
import os

# Connect to local database
client = chromadb.PersistentClient(path="./agent_brain_db")

# Get collections
demo_coll = client.get_collection("demonstrations")
rl_coll = client.get_collection("rl_feedback")

def inspect_feedback():
    print("🧠 Reading RL Experience Memory (rl_feedback)...")
    
    # Get all data
    data = rl_coll.get()
    
    count = len(data['ids'])
    print(f"📊 Total feedback records: {count}\n")
    
    if count == 0:
        print("⚠️ No data yet. Please provide some 👍 or 👎 feedback in the frontend.")
        return

    # Iterate and print
    for i in range(count):
        meta = data['metadatas'][i]
        doc = data['documents'][i]
        
        # Parse data
        reward = meta.get('reward')
        action_str = meta.get('action')
        
        # Visual formatting
        icon = "✅ (Good)" if reward > 0 else "❌ (Bad)"
        
        print(f"--- Record #{i+1} ---")
        print(f"Rating: {icon}")
        # Print Goal only, truncate long Context for readability
        print(f"Context: \n{doc.split('Context:')[0].strip()}...") 
        print(f"Action: {action_str}")
        print("-" * 30)

def inspect_demos():
    print("\n\n🎥 Reading Demonstration Logs (demonstrations)...")
    data = demo_coll.get()
    count = len(data['ids'])
    print(f"📊 Total demonstrations: {count}\n")
    
    for i in range(count):
        task_name = data['documents'][i]
        print(f"📼 Skill: {task_name}")

if __name__ == "__main__":
    inspect_feedback()
    inspect_demos()