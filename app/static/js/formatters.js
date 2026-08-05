const STATUS_LABELS = {
  uploaded: "대기 중",
  processing: "인덱싱 중",
  indexed: "사용 가능",
  failed: "처리 실패",
};

export function formatStatus(status) {
  return STATUS_LABELS[status] || status;
}

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

export function formatPage(page) {
  return page ? `p. ${page}` : "페이지 미상";
}
