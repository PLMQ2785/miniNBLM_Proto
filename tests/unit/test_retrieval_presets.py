import pytest

from app.retrieval_presets import (
    BUILT_IN_PRESETS,
    DEFAULT_PRESET_KEY,
    RetrievalPreset,
    get_retrieval_preset,
    plan_preset_change,
)
from app.search_algorithms import BUILT_IN_SEARCH_ALGORITHMS, DEFAULT_SEARCH_ALGORITHM_KEY


def test_builtin_presets_are_valid_and_unique() -> None:
    """내장 검색 프리셋은 고유 키와 허용된 청크 범위를 지킨다."""
    keys = [preset.key for preset in BUILT_IN_PRESETS]

    assert len(keys) == 5
    assert len(set(keys)) == len(keys)
    assert DEFAULT_PRESET_KEY in keys
    assert all(200 <= preset.chunk_size_chars <= 3500 for preset in BUILT_IN_PRESETS)
    assert all(preset.chunk_overlap_chars <= preset.chunk_size_chars // 5 for preset in BUILT_IN_PRESETS)


def test_chunking_change_requires_reindex() -> None:
    """청크 구성이 바뀌면 문서 재색인과 런타임 갱신이 모두 필요하다."""
    plan = plan_preset_change(
        get_retrieval_preset("balanced"),
        get_retrieval_preset("standard"),
    )

    assert plan.reindex_documents is True
    assert plan.runtime_settings_changed is True


def test_top_k_only_change_is_runtime_only() -> None:
    """top-k만 바뀌면 재색인 없이 런타임 설정만 갱신한다."""
    current = RetrievalPreset("current", "Current", 1000, 150, 8)
    target = RetrievalPreset("target", "Target", 1000, 150, 12)

    plan = plan_preset_change(current, target)

    assert plan.reindex_documents is False
    assert plan.runtime_settings_changed is True


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(199, 20), (3501, 20), (500, 500), (500, 251)],
)
def test_invalid_chunking_values_are_rejected(chunk_size: int, overlap: int) -> None:
    """허용 범위 밖 크기와 과도한 겹침은 프리셋 생성에서 거부한다."""
    with pytest.raises(ValueError):
        RetrievalPreset("invalid", "Invalid", chunk_size, overlap, 8)


def test_search_algorithms_are_fixed_and_dense_is_default() -> None:
    """검색 알고리즘 목록은 고정되어 있고 dense가 기본값이다."""
    keys = [algorithm.key for algorithm in BUILT_IN_SEARCH_ALGORITHMS]

    assert [str(key) for key in keys] == ["dense", "keyword", "substring", "hybrid"]
    assert DEFAULT_SEARCH_ALGORITHM_KEY in keys

