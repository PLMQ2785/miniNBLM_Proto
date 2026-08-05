import { formatDate, formatStatus } from "../formatters.js";

export class DocumentPanel {
  constructor({ listRoot, uploadForm, fileInput, uploadStatus }) {
    this.listRoot = listRoot;
    this.uploadForm = uploadForm;
    this.fileInput = fileInput;
    this.uploadStatus = uploadStatus;
    this.uploadHandler = null;
    this.selectHandler = null;
    this.deleteHandler = null;

    this.fileInput.addEventListener("change", () => {
      const [file] = this.fileInput.files;
      if (file && this.uploadHandler) this.uploadHandler(file);
    });
    this.uploadForm.addEventListener("submit", (event) => event.preventDefault());
    this.listRoot.addEventListener("click", (event) => {
      const deleteButton = event.target.closest("[data-delete-document-id]");
      if (deleteButton && this.deleteHandler) {
        this.deleteHandler(Number(deleteButton.dataset.deleteDocumentId));
        return;
      }
      const button = event.target.closest("[data-document-id]");
      if (button && this.selectHandler) {
        this.selectHandler(Number(button.dataset.documentId));
      }
    });
  }

  onUpload(handler) {
    this.uploadHandler = handler;
  }

  onSelect(handler) {
    this.selectHandler = handler;
  }

  onDelete(handler) {
    this.deleteHandler = handler;
  }

  clearFileInput() {
    this.fileInput.value = "";
  }

  render(documents, selectedId, { isLoading, isUploading, deletingDocumentId }) {
    this.uploadStatus.textContent = isUploading ? "업로드 중" : "";
    this.fileInput.disabled = isUploading;
    this.listRoot.replaceChildren();

    if (isLoading) {
      this.listRoot.append(this.emptyState("문서를 불러오는 중입니다."));
      return;
    }
    if (documents.length === 0) {
      this.listRoot.append(this.emptyState("등록된 문서가 없습니다."));
      return;
    }

    for (const documentSummary of documents) {
      const row = document.createElement("div");
      row.className = "document-row";
      row.dataset.selected = String(documentSummary.document_id === selectedId);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "document-item";
      button.dataset.documentId = documentSummary.document_id;
      button.dataset.status = documentSummary.status;
      button.setAttribute("aria-pressed", String(documentSummary.document_id === selectedId));

      const title = document.createElement("span");
      title.className = "document-title";
      title.textContent = documentSummary.title;

      const meta = document.createElement("span");
      meta.className = "document-meta";

      const status = document.createElement("span");
      status.className = `status-badge status-${documentSummary.status}`;
      status.textContent = formatStatus(documentSummary.status);

      const date = document.createElement("time");
      date.dateTime = documentSummary.created_at;
      date.textContent = formatDate(documentSummary.created_at);

      meta.append(status, date);
      button.append(title, meta);
      if (documentSummary.error_message) button.title = documentSummary.error_message;

      const deleteButton = document.createElement("button");
      const isActive = ["uploaded", "processing"].includes(documentSummary.status);
      const isDeleting = deletingDocumentId === documentSummary.document_id;
      deleteButton.type = "button";
      deleteButton.className = "document-delete-button";
      deleteButton.dataset.deleteDocumentId = documentSummary.document_id;
      deleteButton.disabled = isActive || isDeleting;
      deleteButton.textContent = isDeleting ? "삭제 중" : "삭제";
      deleteButton.setAttribute("aria-label", `${documentSummary.title} 삭제`);
      if (isActive) deleteButton.title = "인덱싱 완료 후 삭제할 수 있습니다.";

      row.append(button, deleteButton);
      this.listRoot.append(row);
    }
  }

  emptyState(message) {
    const element = document.createElement("p");
    element.className = "panel-empty-state";
    element.textContent = message;
    return element;
  }
}
