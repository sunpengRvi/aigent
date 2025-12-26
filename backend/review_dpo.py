import os
import json
import glob

def review_dpo_pairs(base_dir="agent_datasets"):
    print("🕵️‍♂️ === DPO Data Review Tool ===")
    
    # Find all DPO files
    dpo_files = glob.glob(os.path.join(base_dir, "session_*", "dpo_pairs.jsonl"))
    if not dpo_files:
        print("❌ No DPO data found.")
        return

    total_pairs = 0
    pending_pairs = []

    # Load all pending pairs
    for fpath in dpo_files:
        lines = []
        with open(fpath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get('verification_status') == 'pending':
                        data['_file_path'] = fpath # Track source file
                        data['_original_line'] = line
                        pending_pairs.append(data)
                    total_pairs += 1
                except: pass

    print(f"📊 Found {total_pairs} pairs, {len(pending_pairs)} pending review.\n")

    if not pending_pairs:
        print("✅ All caught up!")
        return

    # Review Loop
    for idx, pair in enumerate(pending_pairs):
        print(f"\n--- Reviewing Pair {idx+1}/{len(pending_pairs)} ---")
        print(f"📂 Session: {pair.get('session_id')}")
        print(f"🎯 Task: {pair.get('task_goal')}")
        print(f"🖼️  Image: {pair.get('context_image')}")
        print(f"❌ Rejected (Reason: {pair.get('reason')}):")
        print(f"   {json.dumps(pair.get('rejected'), indent=2)}")
        print(f"✅ Chosen:")
        print(f"   {json.dumps(pair.get('chosen'), indent=2)}")
        
        while True:
            choice = input("\n[Y]Verify / [N]Delete / [S]kip / [Q]uit: ").strip().lower()
            
            if choice == 'y':
                # Update status
                update_status_in_file(pair['_file_path'], pair['_original_line'], "verified")
                print("✅ Verified.")
                break
            elif choice == 'n':
                # Delete line (conceptually mark as deleted or actually remove)
                # For simplicity, we can mark as "rejected_by_human" or remove.
                # Let's remove for cleaner datasets.
                remove_line_from_file(pair['_file_path'], pair['_original_line'])
                print("🗑️  Deleted.")
                break
            elif choice == 's':
                print("⏭️  Skipped.")
                break
            elif choice == 'q':
                print("👋 Bye.")
                return
            else:
                print("Invalid choice.")

def update_status_in_file(filepath, original_line, new_status):
    """Reads file, finds line, updates JSON, rewrites file. Not efficient for huge files but safe."""
    lines = []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    with open(filepath, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.strip() == original_line.strip():
                data = json.loads(line)
                data['verification_status'] = new_status
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            else:
                f.write(line)

def remove_line_from_file(filepath, original_line):
    lines = []
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    with open(filepath, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.strip() != original_line.strip():
                f.write(line)

if __name__ == "__main__":
    review_dpo_pairs()