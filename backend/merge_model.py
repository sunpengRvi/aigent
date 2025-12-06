import os
# ==========================================
# 🛑 0. Network Config (Fix HuggingFace timeout)
# ==========================================
# Use domestic mirror (hf-mirror.com)
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


# ================= Configuration =================
BASE_MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"
ADAPTER_DIR = "universal_adapter"  # Output directory from previous training
OUTPUT_DIR = "merged_model_14b"    # Directory to save merged model

def merge():
    print(f"⏳ Loading base model: {BASE_MODEL_ID} (This may take a few minutes)...")
    
    # Note: To ensure merge precision, use float16 and force CPU loading to prevent VRAM OOM.
    # If you have 4090/A100, you can set device_map="auto".
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        torch_dtype=torch.float16,
        device_map="cpu", 
        trust_remote_code=True
    )

    print(f"🔗 Loading LoRA adapter: {ADAPTER_DIR}...")
    model = PeftModel.from_pretrained(base_model, ADAPTER_DIR)

    print("🧩 Merging weights (Merge and Unload)...")
    model = model.merge_and_unload()

    print("💾 Saving complete model...")
    model.save_pretrained(OUTPUT_DIR)
    
    # Remember to save Tokenizer as well
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID)
    tokenizer.save_pretrained(OUTPUT_DIR)
    
    print(f"✅ Merge complete! Full model saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    merge()