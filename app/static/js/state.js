// 컨트롤러와 화면이 공유할 작업공간 상태의 초기 전이를 정의한다.
export function createInitialState() {
  return {
    documents: [],
    selectedDocumentId: null,
    chatSessions: [],
    activeSessionId: null,
    conversation: [],
    selectedSource: null,
    isLoadingDocuments: true,
    isLoadingSessions: true,
    isLoadingConversation: false,
    isLoadingOlderMessages: false,
    hasOlderMessages: false,
    deletingSessionId: null,
    documentLoadError: null,
    isUploading: false,
    uploadProgress: null,
    deletingDocumentId: null,
    isGenerating: false,
  };
}

// 서버 갱신을 여러 번 받아도 중복 없이 최신 대화 정렬을 유지한다.
export function upsertChatSession(sessions, incoming) {
  const next = sessions.filter((session) => session.session_id !== incoming.session_id);
  next.push(incoming);
  return next.sort((a, b) => {
    const dateDifference = new Date(b.updated_at) - new Date(a.updated_at);
    return dateDifference || b.session_id - a.session_id;
  });
}

// 문서 상태 갱신을 기존 항목에 합치고 최신 업로드 순서를 유지한다.
export function upsertDocument(documents, incoming) {
  const next = documents.filter((document) => document.document_id !== incoming.document_id);
  next.push(incoming);
  return next.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

// 화면과 컨트롤러가 같은 현재 대화 배열을 사용하게 한다.
export function getConversation(state) {
  return state.conversation;
}
