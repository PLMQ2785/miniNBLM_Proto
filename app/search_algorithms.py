from dataclasses import dataclass
from enum import StrEnum


class SearchAlgorithmKey(StrEnum):
    DENSE = "dense"
    KEYWORD = "keyword"
    SUBSTRING = "substring"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class SearchAlgorithmDefinition:
    key: SearchAlgorithmKey
    display_name: str
    description: str


BUILT_IN_SEARCH_ALGORITHMS = (
    SearchAlgorithmDefinition(
        key=SearchAlgorithmKey.DENSE,
        display_name="의미 검색",
        description="BGE-M3 embedding과 cosine 유사도로 표현이 다른 관련 문장을 찾습니다.",
    ),
    SearchAlgorithmDefinition(
        key=SearchAlgorithmKey.KEYWORD,
        display_name="키워드 검색",
        description="PostgreSQL FTS로 질문에 포함된 용어가 직접 등장하는 청크를 찾습니다.",
    ),
    SearchAlgorithmDefinition(
        key=SearchAlgorithmKey.SUBSTRING,
        display_name="부분 문자열 검색",
        description="pg_trgm으로 약어, 영문 용어, 일부만 입력한 문자열과 유사한 청크를 찾습니다.",
    ),
    SearchAlgorithmDefinition(
        key=SearchAlgorithmKey.HYBRID,
        display_name="하이브리드 RRF",
        description="의미·키워드·부분 문자열 검색 순위를 RRF로 합쳐 일반적인 질문에 대응합니다.",
    ),
)

DEFAULT_SEARCH_ALGORITHM_KEY = SearchAlgorithmKey.DENSE
