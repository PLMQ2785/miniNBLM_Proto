// HTTP 실패의 상태와 상세 정보를 화면 계층까지 전달하는 오류다.
export class ApiError extends Error {
  // 사용자 메시지와 응답 메타데이터를 하나의 오류로 묶는다.
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// 인증·문서·대화 요청과 응답 오류 처리를 한곳에 모은 API 경계다.
export class ApiClient {
  // 배포 경로에 맞는 서버 기준 URL을 보관한다.
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl;
  }

  // 작업공간 시작 시 서버 연결 가능 여부를 확인한다.
  async health() {
    return this.request("/health");
  }

  // 현재 세션의 인증 사용자 정보를 조회한다.
  async getCurrentUser() {
    return this.request("/auth/me");
  }

  // 새 계정을 만들고 인증 결과를 반환한다.
  async register(username, password) {
    return this.request("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  }

  // 자격 증명으로 서버 세션을 시작한다.
  async login(username, password) {
    return this.request("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  }

  // 현재 서버 세션을 종료한다.
  async logout() {
    return this.request("/auth/logout", { method: "POST" });
  }

  // 현재 비밀번호를 확인해 계정 비밀번호를 변경한다.
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

  // 비밀번호와 사용자명 확인을 거쳐 현재 계정을 삭제한다.
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

  // 관리자가 사용자에게 임시 비밀번호를 설정한다.
  async resetUserPassword(username, temporaryPassword) {
    return this.request("/admin/users/password-reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        temporary_password: temporaryPassword,
      }),
    });
  }
  // 사용 가능한 언어모델과 현재 선택을 조회한다.
  async getLanguageModelState() {
    return this.request("/language-models");
  }

  // 작업공간이 사용할 언어모델 엔드포인트를 전환한다.
  async activateLanguageModel(endpointKey) {
    return this.request(`/language-models/${encodeURIComponent(endpointKey)}/activate`, {
      method: "POST",
    });
  }

  // 관리자용 JSON endpoint 전체 상태와 revision을 조회한다.
  async getLanguageModelAdminState() {
    return this.request("/admin/language-models");
  }

  // 새 endpoint를 연결 검증한 뒤 JSON에 추가한다.
  async createLanguageModelEndpoint(payload, revision) {
    return this.request("/admin/language-models", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "If-Match": revision,
      },
      body: JSON.stringify(payload),
    });
  }

  // 기존 key를 유지하며 endpoint 메타데이터와 credential 참조를 교체한다.
  async updateLanguageModelEndpoint(endpointKey, payload, revision) {
    return this.request(`/admin/language-models/${encodeURIComponent(endpointKey)}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "If-Match": revision,
      },
      body: JSON.stringify(payload),
    });
  }

  // 활성 endpoint를 JSON 기본값으로 지정한다.
  async setDefaultLanguageModelEndpoint(endpointKey, revision) {
    return this.request(`/admin/language-models/${encodeURIComponent(endpointKey)}/default`, {
      method: "POST",
      headers: { "If-Match": revision },
    });
  }

  // 기본값이 아닌 endpoint를 JSON에서 삭제한다.
  async deleteLanguageModelEndpoint(endpointKey, revision) {
    return this.request(`/admin/language-models/${encodeURIComponent(endpointKey)}`, {
      method: "DELETE",
      headers: { "If-Match": revision },
    });
  }


  // 관리자 화면에 필요한 검색 설정과 작업 상태를 조회한다.
  async getRetrievalAdminState() {
    return this.request("/admin/retrieval");
  }

  // 검색 프리셋을 적용하고 필요한 재인덱싱을 요청한다.
  async activateRetrievalPreset(presetKey) {
    return this.request(`/admin/retrieval/presets/${encodeURIComponent(presetKey)}/activate`, {
      method: "POST",
    });
  }

  // 활성 검색 알고리즘을 전환한다.
  async activateSearchAlgorithm(algorithmKey) {
    return this.request(`/admin/retrieval/algorithms/${encodeURIComponent(algorithmKey)}/activate`, {
      method: "POST",
    });
  }

  // 재인덱싱 작업의 현재 상태를 조회한다.
  async getReindexJob(jobId) {
    return this.request(`/admin/retrieval/jobs/${jobId}`);
  }

  // 실패한 재인덱싱 작업을 다시 실행한다.
  async retryReindexJob(jobId) {
    return this.request(`/admin/retrieval/jobs/${jobId}/retry`, { method: "POST" });
  }

  // 작업공간에 표시할 문서 목록만 추출해 반환한다.
  async listDocuments() {
    const response = await this.request("/documents");
    return response.documents;
  }

  // 폴링과 업로드 후 갱신에 사용할 문서 상태를 조회한다.
  async getDocument(documentId) {
    return this.request(`/documents/${documentId}`);
  }

  // PDF 파일을 멀티파트 요청으로 업로드한다.
  async uploadDocument(file) {
    const body = new FormData();
    body.append("file", file);
    return this.request("/documents", { method: "POST", body });
  }

  // 문서와 서버의 인덱싱 데이터를 함께 삭제한다.
  async deleteDocument(documentId) {
    return this.request(`/documents/${documentId}`, { method: "DELETE" });
  }

  // 대화 선택 목록에 표시할 세션을 조회한다.
  async listChatSessions() {
    const response = await this.request("/chat/sessions");
    return response.sessions;
  }

  // 지정한 대화의 최신 또는 이전 메시지 구간을 조회한다.
  async getChatSession(sessionId, { limit = 100, beforeId = null } = {}) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (beforeId !== null) params.set("before_id", String(beforeId));
    return this.request(`/chat/sessions/${sessionId}?${params}`);
  }

  // 저장된 대화 세션과 메시지를 삭제한다.
  async deleteChatSession(sessionId) {
    return this.request(`/chat/sessions/${sessionId}`, { method: "DELETE" });
  }

  // 선택 문서가 있으면 범위를 포함하고 없으면 전체 대상으로 질문을 전송한다.
  async sendQuestion(question, documentId, sessionId = null) {
    const payload = { question };
    if (documentId !== null) payload.document_id = documentId;
    if (sessionId !== null) payload.session_id = sessionId;
    return this.request("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  // 선택 문서가 있으면 범위를 포함한 질문을 SSE로 전송하고 결과를 누적한다.
  async streamQuestion(question, documentId, sessionId = null, onEvent = null) {
    const payload = { question };
    if (documentId !== null) payload.document_id = documentId;
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
    // 네트워크 조각과 SSE 경계가 어긋나므로 미완성 꼬리를 보관한다.
    // 하나의 SSE 블록을 해석해 누적 결과와 화면 콜백에 전달한다.
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
      else if (event === "revision") {
        // 인용 교정 결과는 토큰 스트림으로 만든 전체 답변을 대체한다.
        result.answer = data.text || "";
      } else if (event === "sources") result.sources = data;
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

  // 원문 패널이 지정 페이지를 열 수 있는 PDF 주소를 만든다.
  getPdfUrl(documentId, page = null) {
    const base = `${this.baseUrl}/documents/${documentId}/file`;
    return page ? `${base}#page=${page}&view=FitH` : base;
  }

  // 일반 API 요청의 인증 설정·응답 해석·오류 변환을 통일한다.
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

  // HTTP 상태와 서버 상세 사유를 사용자용 한국어 메시지로 바꾼다.
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
    if (path === "/admin/users/password-reset") {
      if (status === 404) return "사용자를 찾을 수 없습니다.";
      if (status === 409 && detail === "Use the account password change flow for your own account") {
        return "현재 관리자 계정은 계정 화면에서 비밀번호를 변경해 주세요.";
      }
      if (status === 409) return "기존 비밀번호와 다른 임시 비밀번호를 사용해 주세요.";
      if (status === 400 && detail === "Password must not contain the username") {
        return "임시 비밀번호에 사용자명을 포함할 수 없습니다.";
      }
      if (status === 400 && detail === "Password is too common") {
        return "추측하기 어려운 임시 비밀번호를 사용해 주세요.";
      }
      if (status === 400) {
        return "영문 대·소문자, 숫자, 기호 중 3종 이상을 사용해 주세요.";
      }
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
