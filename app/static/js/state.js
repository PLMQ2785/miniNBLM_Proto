export function createInitialState() {
  return {
    documents: [],
    selectedDocumentId: null,
    conversations: new Map(),
    selectedSource: null,
    isLoadingDocuments: true,
    documentLoadError: null,
    isUploading: false,
    deletingDocumentId: null,
    isGenerating: false,
  };
}

export function upsertDocument(documents, incoming) {
  const next = documents.filter((document) => document.document_id !== incoming.document_id);
  next.push(incoming);
  return next.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
}

export function getSelectedDocument(state) {
  return state.documents.find(
    (document) => document.document_id === state.selectedDocumentId,
  ) || null;
}

export function getConversation(state) {
  if (state.selectedDocumentId === null) return [];
  return state.conversations.get(state.selectedDocumentId) || [];
}
