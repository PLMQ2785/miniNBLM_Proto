export function createInitialState() {
  return {
    documents: [],
    conversation: [],
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

export function getConversation(state) {
  return state.conversation;
}
