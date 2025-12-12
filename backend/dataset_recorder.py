import os
import json
import base64
import datetime
import uuid

class DatasetRecorder:
    def __init__(self, base_dir="agent_datasets"):
        self.base_dir = base_dir
        self.demo_assets_dir = os.path.join(self.base_dir, "demo_assets")
        
        if not os.path.exists(self.base_dir):
            os.makedirs(self.base_dir)
        if not os.path.exists(self.demo_assets_dir):
            os.makedirs(self.demo_assets_dir)
            
        self.current_session_dir = None
        self.current_session_id = None

    def start_new_session(self, task_goal):
        """
        Creates a new directory for the current task session.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        folder_name = f"session_{timestamp}_{unique_id}"
        
        self.current_session_dir = os.path.join(self.base_dir, folder_name)
        self.current_session_id = folder_name
        
        if not os.path.exists(self.current_session_dir):
            os.makedirs(self.current_session_dir)
            
        # Save session metadata
        meta = {
            "session_id": folder_name,
            "goal": task_goal,
            "start_time": timestamp
        }
        self._append_jsonl("session_info.jsonl", meta)
        print(f"📼 Recording started: {self.current_session_dir}")

    def save_demo_image(self, b64_str, filename):
        """
        Saves a detached image (full screen or crop) to demo_assets folder.
        Returns the relative path.
        """
        if not b64_str: return None
        try:
            # Clean base64 header if present
            if "," in b64_str:
                b64_str = b64_str.split(",")[1]
            
            file_path = os.path.join(self.demo_assets_dir, filename)
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_str))
                
            return os.path.join("demo_assets", filename)
        except Exception as e:
            print(f"❌ Failed to save demo image {filename}: {e}")
            return None

    def record_step(self, step_index, data_packet):
        """
        Saves all data for a single step (Screenshots, DOM, Prompt, Thought, Action).
        """
        if not self.current_session_dir:
            print("⚠️ No active session to record.")
            return

        # 1. Save Images
        raw_img_path = self._save_image(data_packet.get("raw_screenshot"), f"step_{step_index:02d}_raw.jpg")
        marked_img_path = self._save_image(data_packet.get("marked_screenshot"), f"step_{step_index:02d}_marked.jpg")

        # 2. Extract Logic (Input/Output Pair)
        entry = {
            "step": step_index,
            "timestamp": datetime.datetime.now().isoformat(),
            "attempt": data_packet.get("attempt", 0),
            "model": data_packet.get("model", "unknown"),
            
            # Inputs
            "images": {
                "raw": raw_img_path,
                "marked": marked_img_path
            },
            "context": {
                "dom": data_packet.get("dom"),
                "prompt_inputs": data_packet.get("prompt") 
            },
            
            # Outputs (The Gold Mine for Training)
            "llm_output": {
                "raw_response": data_packet.get("response_raw"), # Contains <think> chain!
                "parsed_action": data_packet.get("action_json")
            }
        }

        # 3. Save to JSONL
        self._append_jsonl("trajectory.jsonl", entry)
        print(f"💾 Step {step_index} saved to dataset.")

    def _save_image(self, b64_str, filename):
        """Decodes and saves base64 image to current session dir."""
        if not b64_str: return None
        try:
            if "," in b64_str:
                b64_str = b64_str.split(",")[1]
            
            file_path = os.path.join(self.current_session_dir, filename)
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64_str))
            return filename
        except Exception as e:
            print(f"❌ Failed to save image {filename}: {e}")
            return None

    def _append_jsonl(self, filename, data):
        """Appends a line to a JSONL file."""
        file_path = os.path.join(self.current_session_dir, filename)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")