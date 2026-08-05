from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

@dataclass(frozen=True)
class RetrievalPreset:
    key: str
    display_name: str
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int

    def __post_init__(self) -> None:
        normalized_key = self.key.replace("_", "")
        if (
            not normalized_key
            or not normalized_key.isascii()
            or not normalized_key.isalnum()
            or self.key != self.key.lower()
        ):
            raise ValueError("Preset key must contain only lowercase ASCII letters, numbers, and underscores")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if not 200 <= self.chunk_size_chars <= 3500:
            raise ValueError("chunk_size_chars must be between 200 and 3500")
        if not 0 <= self.chunk_overlap_chars < self.chunk_size_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")
        if self.chunk_overlap_chars > self.chunk_size_chars // 2:
            raise ValueError("chunk_overlap_chars cannot exceed half of chunk_size_chars")
        if not 1 <= self.top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")

    @property
    def maximum_context_chars(self) -> int:
        return self.chunk_size_chars * self.top_k


@dataclass(frozen=True)
class PresetChangePlan:
    reindex_documents: bool
    runtime_settings_changed: bool


def plan_preset_change(current: RetrievalPreset, target: RetrievalPreset) -> PresetChangePlan:
    reindex_documents = (
        current.chunk_size_chars != target.chunk_size_chars
        or current.chunk_overlap_chars != target.chunk_overlap_chars
    )
    return PresetChangePlan(
        reindex_documents=reindex_documents,
        runtime_settings_changed=current.top_k != target.top_k,
    )


BUILT_IN_PRESETS = (
    RetrievalPreset(
        key="fine_grained",
        display_name="Fine grained",
        chunk_size_chars=200,
        chunk_overlap_chars=40,
        top_k=20,
    ),
    RetrievalPreset(
        key="standard",
        display_name="Standard",
        chunk_size_chars=500,
        chunk_overlap_chars=75,
        top_k=12,
    ),
    RetrievalPreset(
        key="balanced",
        display_name="Balanced",
        chunk_size_chars=1000,
        chunk_overlap_chars=150,
        top_k=8,
    ),
    RetrievalPreset(
        key="broad_context",
        display_name="Broad context",
        chunk_size_chars=2000,
        chunk_overlap_chars=300,
        top_k=5,
    ),
    RetrievalPreset(
        key="long_form",
        display_name="Long form",
        chunk_size_chars=3500,
        chunk_overlap_chars=500,
        top_k=4,
    ),
)

PRESETS_BY_KEY: Mapping[str, RetrievalPreset] = MappingProxyType(
    {preset.key: preset for preset in BUILT_IN_PRESETS}
)
DEFAULT_PRESET_KEY = "balanced"

if len(PRESETS_BY_KEY) != len(BUILT_IN_PRESETS):
    raise RuntimeError("Retrieval preset keys must be unique")
if DEFAULT_PRESET_KEY not in PRESETS_BY_KEY:
    raise RuntimeError("Default retrieval preset must exist")


def get_retrieval_preset(key: str) -> RetrievalPreset:
    try:
        return PRESETS_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unknown retrieval preset: {key}") from exc
