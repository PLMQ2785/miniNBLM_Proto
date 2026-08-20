const STATUS_LABELS = {
  uploaded: "대기 중",
  processing: "인덱싱 중",
  indexed: "사용 가능",
  failed: "처리 실패",
};

// 서버 문서 상태를 목록에 표시할 짧은 한국어로 바꾼다.
export function formatStatus(status) {
  return STATUS_LABELS[status] || status;
}

// 서버 시각을 한국어 목록용 월·일·시각으로 표시한다.
export function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

// 출처 페이지 번호를 표시하고 값이 없으면 상태를 알려 준다.
export function formatPage(page) {
  return page ? `p. ${page}` : "페이지 미상";
}
