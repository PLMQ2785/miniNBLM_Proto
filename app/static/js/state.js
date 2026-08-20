export function createInitialState() {
  return {
    documents: [],
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

// Upserts keep server refreshes idempotent and preserve the UI's sort order.
export function upsertChatSession(sessions, incoming) {
  const next = sessions.filter((session) => session.session_id !== incoming.session_id);
  next.push(incoming);
  return next.sort((a, b) => {
    const dateDifference = new Date(b.updated_at) - new Date(a.updated_at);
    return dateDifference || b.session_id - a.session_id;
  });
}

export function upsertDocument(documents, incoming) {
  const next = documents.filter((document) => document.document_id !== incoming.document_id);
  next.push(incoming);
  return next.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

export function getConversation(state) {
  return state.conversation;
}
