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

  async changePassword(currentPassword, newPassword) {
    return this.request("/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  }

  async deleteAccount(currentPassword, usernameConfirmation) {
    return this.request("/auth/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        username_confirmation: usernameConfirmation,
      }),
    });
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

  async listChatSessions() {
    const response = await this.request("/chat/sessions");
    return response.sessions;
  }

  async getChatSession(sessionId, { limit = 100, beforeId = null } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (beforeId !== null) params.set("before_id", String(beforeId));
    return this.request(`/chat/sessions/${sessionId}?${params}`);
  }

  async deleteChatSession(sessionId) {
    return this.request(`/chat/sessions/${sessionId}`, { method: "DELETE" });
  }

  async sendQuestion(question, sessionId = null) {
    const payload = { question };
    if (sessionId !== null) payload.session_id = sessionId;
    return this.request("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async streamQuestion(question, sessionId = null, onEvent = null) {
    const payload = { question };
    if (sessionId !== null) payload.session_id = sessionId;

    let response;
    try {
      response = await fetch(`${this.baseUrl}/chat/stream`, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "text/event-stream",
        },
        body: JSON.stringify(payload),
      });
    } catch (error) {
      throw new ApiError("서버에 연결할 수 없습니다.", { detail: error.message });
    }

    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";
      const errorPayload = contentType.includes("application/json")
        ? await response.json()
        : await response.text();
      const detail = typeof errorPayload === "object" ? errorPayload.detail : errorPayload;
      if (response.status === 401) window.dispatchEvent(new CustomEvent("authrequired"));
      throw new ApiError(this.errorMessage(response.status, detail, "/chat/stream"), {
        status: response.status,
        detail,
      });
    }
    if (!response.body) {
      throw new ApiError("스트리밍 응답을 읽을 수 없습니다.");
    }

    const result = { answer: "", sources: [], session: null };
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;

    const processBlock = (block) => {
      if (!block.trim()) return;
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (dataLines.length === 0) return;
      const data = JSON.parse(dataLines.join("\n"));
      if (event === "error") {
        throw new ApiError(data.detail || "답변 스트리밍에 실패했습니다.", { detail: data });
      }
      if (event === "session") result.session = data;
      else if (event === "delta") result.answer += data.text || "";
      else if (event === "revision") result.answer = data.text || "";
      else if (event === "sources") result.sources = data;
      else if (event === "done") {
        result.session = data.session || result.session;
        completed = true;
      }
      onEvent?.(event, data, result);
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        buffer = buffer.replaceAll("\r\n", "\n");
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          processBlock(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf("\n\n");
        }
        if (done) break;
      }
      if (buffer.trim()) processBlock(buffer);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError("답변 스트리밍 연결이 중단되었습니다.", { detail: error.message });
    } finally {
      reader.releaseLock();
    }

    if (!completed) {
      throw new ApiError("답변 스트리밍이 완료되기 전에 연결이 종료되었습니다.");
    }
    return result;
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
      throw new ApiError(this.errorMessage(response.status, detail, path), {
        status: response.status,
        detail,
      });
    }
    return payload;
  }

  errorMessage(status, detail, path = "") {
    if (path === "/auth/password") {
      if (status === 409) return "현재 비밀번호와 다른 비밀번호를 사용해 주세요.";
      if (status === 400 && detail === "Current password is incorrect") {
        return "현재 비밀번호가 올바르지 않습니다.";
      }
      if (status === 400 && detail === "Password must not contain the username") {
        return "새 비밀번호에 사용자명을 포함할 수 없습니다.";
      }
      if (status === 400 && detail === "Password is too common") {
        return "추측하기 어려운 새 비밀번호를 사용해 주세요.";
      }
      if (status === 400) {
        return "영문 대·소문자, 숫자, 기호 중 3종 이상을 사용해 주세요.";
      }
    }
    if (path === "/auth/account") {
      if (status === 400 && detail === "Current password is incorrect") {
        return "현재 비밀번호가 올바르지 않습니다.";
      }
      if (status === 400 && detail === "Username confirmation does not match") {
        return "사용자명이 일치하지 않습니다.";
      }
      if (status === 409) return "문서 인덱싱이 끝난 후 회원탈퇴를 진행해 주세요.";
    }
    if (status === 400) return detail || "요청한 파일을 확인해 주세요.";
    if (status === 401) return "사용자명 또는 비밀번호를 확인해 주세요.";
    if (status === 403) return "이 작업을 수행할 권한이 없습니다.";
    if (status === 404 && path.startsWith("/chat/")) return "요청한 대화를 찾을 수 없습니다.";
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
