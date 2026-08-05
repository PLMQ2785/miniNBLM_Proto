export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  async health() {
    return this.request("/health");
  }

  async getCurrentUser() {
    return this.request("/auth/me");
  }

  async register(username, password) {
    return this.request("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  }

  async login(username, password) {
    return this.request("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  }

  async logout() {
    return this.request("/auth/logout", { method: "POST" });
  }

  async getRetrievalAdminState() {
    return this.request("/admin/retrieval");
  }

  async activateRetrievalPreset(presetKey) {
    return this.request(`/admin/retrieval/presets/${encodeURIComponent(presetKey)}/activate`, {
      method: "POST",
    });
  }

  async activateSearchAlgorithm(algorithmKey) {
    return this.request(`/admin/retrieval/algorithms/${encodeURIComponent(algorithmKey)}/activate`, {
      method: "POST",
    });
  }

  async getReindexJob(jobId) {
    return this.request(`/admin/retrieval/jobs/${jobId}`);
  }

  async retryReindexJob(jobId) {
    return this.request(`/admin/retrieval/jobs/${jobId}/retry`, { method: "POST" });
  }

  async listDocuments() {
    const response = await this.request("/documents");
    return response.documents;
  }

  async getDocument(documentId) {
    return this.request(`/documents/${documentId}`);
  }

  async uploadDocument(file) {
    const body = new FormData();
    body.append("file", file);
    return this.request("/documents", { method: "POST", body });
  }

  async deleteDocument(documentId) {
    return this.request(`/documents/${documentId}`, { method: "DELETE" });
  }

  async sendQuestion(question) {
    return this.request("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  }

  getPdfUrl(documentId, page = null) {
    const base = `${this.baseUrl}/documents/${documentId}/file`;
    return page ? `${base}#page=${page}&view=FitH` : base;
  }

  async request(path, options = {}) {
    let response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, { credentials: "same-origin", ...options });
    } catch (error) {
      throw new ApiError("서버에 연결할 수 없습니다.", { detail: error.message });
    }

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      if (response.status === 401 && !path.startsWith("/auth/")) {
        window.dispatchEvent(new CustomEvent("authrequired"));
      }
      throw new ApiError(this.errorMessage(response.status, detail), {
        status: response.status,
        detail,
      });
    }
    return payload;
  }

  errorMessage(status, detail) {
    if (status === 400) return detail || "요청한 파일을 확인해 주세요.";
    if (status === 401) return "사용자명 또는 비밀번호를 확인해 주세요.";
    if (status === 403) return "이 작업을 수행할 권한이 없습니다.";
    if (status === 404) return "요청한 문서를 찾을 수 없습니다.";
    if (status === 409) return "문서 처리가 아직 완료되지 않았습니다.";
    if (status === 422) return "입력 내용을 확인해 주세요.";
    if (status === 503 && detail === "Retrieval maintenance is in progress") {
      return "검색 설정 변경 작업이 진행 중입니다. 완료 후 다시 시도해 주세요.";
    }
    if (status === 503) return "AI 서비스가 일시적으로 준비되지 않았습니다.";
    return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }
}
