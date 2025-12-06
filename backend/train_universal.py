import os
# ==========================================
# 🛑 0. Network Config
# ==========================================
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import os
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq
)
from peft import LoraConfig, get_peft_model, TaskType

# ================= Configuration =================
MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Qwen-14B"
OUTPUT_DIR = "universal_adapter"
DATA_FILE = "train_dataset.json"

# ================= 1. Hardware Adaptation =================
bnb_config = None
use_fp16 = False
use_bf16 = False
optimizer_type = "adamw_torch"
device_map_config = None 

if torch.cuda.is_available():
    print("🚀 Using NVIDIA CUDA")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )
    use_fp16 = True
    optimizer_type = "adamw_8bit"
    device_map_config = "auto"
elif torch.backends.mps.is_available():
    print("🍎 Using Apple Metal (MPS)")
    use_bf16 = True
    device_map_config = None 
else:
    print("🐢 Using CPU")
    device_map_config = "cpu"

# ================= 2. Load Model =================
print("⏳ Loading model...")

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=bnb_config,
    device_map=device_map_config,
    torch_dtype=torch.bfloat16 if use_bf16 else torch.float16,
    trust_remote_code=True
)

if torch.backends.mps.is_available():
    print("🔄 Moving model to MPS device...")
    model.to("mps")

# 🔥 Fix: Enable input gradients for gradient checkpointing
model.enable_input_require_grads()
model.config.use_cache = False 

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
tokenizer.pad_token = tokenizer.eos_token

# ================= 3. LoRA Config =================
peft_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    inference_mode=False,
    r=8,
    lora_alpha=32,
    lora_dropout=0.1,
    target_modules=["q_proj", "v_proj"] 
)
model = get_peft_model(model, peft_config)
model.print_trainable_parameters()

# ================= 4. Data Processing =================
def format_prompt(sample):
    return f"<|im_start|>user\n{sample['instruction']}\n{sample['input']}<|im_end|>\n<|im_start|>assistant\n{sample['output']}<|im_end|>"

def preprocess(example):
    model_inputs = tokenizer(
        format_prompt(example),
        padding="max_length",
        truncation=True,
        max_length=512
    )
    # 🔥 Fix: Ensure labels exist
    model_inputs["labels"] = model_inputs["input_ids"].copy()
    return model_inputs

print("📂 Processing dataset...")
dataset = load_dataset("json", data_files=DATA_FILE, split="train")
tokenized_dataset = dataset.map(preprocess, remove_columns=dataset.column_names)

# ================= 5. Training =================
print(f"⚙️ Optimizer: {optimizer_type}")

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=1, 
    gradient_accumulation_steps=4,
    learning_rate=2e-4,
    logging_steps=1,
    num_train_epochs=3,
    save_steps=50,
    fp16=use_fp16,
    bf16=use_bf16,
    optim=optimizer_type,
    use_cpu=False,
    ddp_find_unused_parameters=False,
    gradient_checkpointing=True 
)

trainer = Trainer(
    model=model,
    train_dataset=tokenized_dataset,
    args=training_args,
    data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True)
)

print("🚀 Starting training...")
trainer.train()

# ================= 6. Save =================
print(f"💾 Saving adapter to {OUTPUT_DIR}")
model.save_pretrained(OUTPUT_DIR)
print("✅ Done")