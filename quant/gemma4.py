"""Gemma 4를 보정 데이터로 W4A16 양자화해 압축 저장한다."""

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

# Gemma 4 12B Unified 양자화 설정
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
        # max_memory={"cpu": 14 * 1024**3},  # CPU 메모리 상한이 필요할 때 사용
        offload_folder="./offload",
    )
processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer = processor.tokenizer

# 3. 데이터셋 전처리 (Gemma 4 멀티모달 템플릿 적용)
print("Preprocessing dataset...")
ds = load_dataset("HuggingFaceH4/ultrachat_200k", split="train_sft")
ds = ds.shuffle(seed=42).select(range(NUM_CALIBRATION_SAMPLES))


def preprocess_fn(example):
    """대화 표본을 Gemma 채팅 템플릿의 보정 텍스트로 바꾼다."""
    return {
        "text": tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False
        )
    }


ds = ds.map(preprocess_fn, remove_columns=ds.column_names)

# 4. 비전 타워를 보존하는 W4A16 AWQ 레시피 구성
# 레이어별 전역·슬라이딩 어텐션 구조에 맞춰 균형 조정 대상을 만든다.
config = AutoConfig.from_pretrained(MODEL_ID)
layer_types = config.text_config.layer_types
num_layers = len(layer_types)

awq_mappings = []
for i in range(num_layers):
    layer_prefix = f"re:.*layers\\.{i}\\."
    
    # 어텐션 블록 매핑
    if layer_types[i] == "full_attention":
        # 전역 어텐션은 k_proj가 있고 v_proj는 공유한다.
        awq_mappings.append(
            AWQMapping(
                smooth_layer=f"{layer_prefix}input_layernorm$",
                balance_layers=[f"{layer_prefix}self_attn.q_proj$", f"{layer_prefix}self_attn.k_proj$"]
            )
        )
    else:
        # 슬라이딩 어텐션은 q_proj, k_proj, v_proj를 모두 쓴다.
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

    # MLP 블록에서 정규화 출력을 gate_proj와 up_proj에 맞춘다.
    awq_mappings.append(
        AWQMapping(
            smooth_layer=f"{layer_prefix}pre_feedforward_layernorm$",
            balance_layers=[f"{layer_prefix}mlp.gate_proj$", f"{layer_prefix}mlp.up_proj$"]
        )
    )
    # up_proj 출력을 down_proj에 맞춘다.
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
            # vLLM은 Unified 멀티모달 연결부를 BF16 ReplicatedLinear로 만든다.
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

# 저장 전에 보정 데이터와 레시피가 점유한 GPU 메모리를 회수한다.
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
