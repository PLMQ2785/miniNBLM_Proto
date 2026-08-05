import os

os.environ["CUDA_VISIBLE_DEVICES"] = "0"

import torch
from compressed_tensors.offload import load_offloaded_model
from datasets import load_dataset
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import QuantizationModifier
from llmcompressor.modifiers.transform import AWQModifier
from llmcompressor.modifiers.transform.awq import AWQMapping
from transformers import (
    AutoConfig,
    AutoProcessor,
    Gemma4UnifiedForConditionalGeneration,
)

# ──────────────────────────────────────────────
# 설정 (Gemma 4 12B Unified)
# ──────────────────────────────────────────────
MODEL_ID = os.getenv("QUANT_MODEL_ID", "google/gemma-4-12B-it")
OUTPUT_DIR = os.getenv(
    "QUANT_OUTPUT_DIR", "./google/gemma-4-12B-it-W4A16-vllm"
)
NUM_CALIBRATION_SAMPLES = int(os.getenv("QUANT_CALIBRATION_SAMPLES", "512"))
MAX_SEQUENCE_LENGTH = int(os.getenv("QUANT_MAX_SEQUENCE_LENGTH", "2048"))

# 1. 기존 체크포인트를 실수로 덮어쓰지 않도록 새 출력 경로만 허용
if os.path.exists(OUTPUT_DIR):
    raise FileExistsError(
        f"Output directory already exists: {OUTPUT_DIR}. "
        "Set QUANT_OUTPUT_DIR to a new path."
    )

# 2. 모델 및 프로세서 로드
print(f"Loading model: {MODEL_ID}...")
with load_offloaded_model(model_class=Gemma4UnifiedForConditionalGeneration):
    model = Gemma4UnifiedForConditionalGeneration.from_pretrained(
        MODEL_ID,
        device_map="auto_offload",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        # max_memory={"cpu": 14 * 1024**3},
        offload_folder="./offload",
    )
processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer = processor.tokenizer

# 3. 데이터셋 전처리 (Gemma 4 멀티모달 템플릿 적용)
print("Preprocessing dataset...")
ds = load_dataset("HuggingFaceH4/ultrachat_200k", split="train_sft")
ds = ds.shuffle(seed=42).select(range(NUM_CALIBRATION_SAMPLES))


def preprocess_fn(example):
    return {
        "text": tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
    }


ds = ds.map(preprocess_fn, remove_columns=ds.column_names)

# 4. W4A16 레시피 설정 (비전 타워 보호 필히 포함)
# AWQ(Activation-Weighted Quantization) 방식을 적용합니다.
# Gemma 4의 슬라이딩(sliding) 및 전역(full) 어텐션 레이어 구성을 파악하여 적절한 AWQ 맵핑을 생성합니다.
config = AutoConfig.from_pretrained(MODEL_ID)
layer_types = config.text_config.layer_types
num_layers = len(layer_types)

awq_mappings = []
for i in range(num_layers):
    layer_prefix = f"re:.*layers\\.{i}\\."
    
    # 1. Attention block mapping
    if layer_types[i] == "full_attention":
        # Full attention has k_proj, but no v_proj (attention_k_eq_v=True)
        awq_mappings.append(
            AWQMapping(
                smooth_layer=f"{layer_prefix}input_layernorm$",
                balance_layers=[f"{layer_prefix}self_attn.q_proj$", f"{layer_prefix}self_attn.k_proj$"]
            )
        )
    else:
        # Sliding attention has q_proj, k_proj, v_proj
        awq_mappings.append(
            AWQMapping(
                smooth_layer=f"{layer_prefix}input_layernorm$",
                balance_layers=[
                    f"{layer_prefix}self_attn.q_proj$",
                    f"{layer_prefix}self_attn.k_proj$",
                    f"{layer_prefix}self_attn.v_proj$"
                ]
            )
        )

    # 2. MLP block mappings
    # pre_feedforward_layernorm -> gate_proj, up_proj
    awq_mappings.append(
        AWQMapping(
            smooth_layer=f"{layer_prefix}pre_feedforward_layernorm$",
            balance_layers=[f"{layer_prefix}mlp.gate_proj$", f"{layer_prefix}mlp.up_proj$"]
        )
    )
    # up_proj -> down_proj
    awq_mappings.append(
        AWQMapping(
            smooth_layer=f"{layer_prefix}mlp.up_proj$",
            balance_layers=[f"{layer_prefix}mlp.down_proj$"]
        )
    )

recipe = [
    AWQModifier(mappings=awq_mappings),
    QuantizationModifier(
        targets="Linear",
        scheme="W4A16",
        ignore=[
            "lm_head",
            # vLLM builds Unified multimodal connectors as BF16 ReplicatedLinear.
            r"re:.*embed_audio.*",
            r"re:.*embed_vision.*",
            r"re:.*vision_embedder.*",
            r"re:.*audio.*",
            r"re:.*vision.*",
            r"re:.*multi_modal_projector.*",
            r"re:.*connector.*",
            r"re:.*linear_attn.*",
            r"re:.*mtp.*",
        ],
    ),
]


# 5. 양자화 실행
print("Starting W4A16 quantization...")
oneshot(
    model=model,
    dataset=ds,
    recipe=recipe,
    tokenizer=tokenizer,
    max_seq_length=MAX_SEQUENCE_LENGTH,
    num_calibration_samples=NUM_CALIBRATION_SAMPLES,
    pipeline="sequential",
)

# 메모리 확보를 위해 불필요한 개체 삭제 및 가비지 컬렉션 수행
import gc
del ds
del recipe
gc.collect()
torch.cuda.empty_cache()

# 6. 압축 저장
print("Saving compressed model...")
model.save_pretrained(
    OUTPUT_DIR,
    save_compressed=True,
    max_shard_size="2GB"
)
processor.save_pretrained(OUTPUT_DIR)

print(f"✅ W4A16 양자화 완료: {OUTPUT_DIR}")
