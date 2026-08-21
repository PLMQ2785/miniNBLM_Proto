// 관리자 화면에서 JSON 기반 LLM endpoint 목록과 편집 폼을 관리한다.
export class LanguageModelAdminView {
  // endpoint 카드·입력·작업 버튼과 controller handler를 연결한다.
  constructor({
    list,
    form,
    key,
    displayName,
    baseUrl,
    model,
    authentication,
    apiKey,
    apiKeyNote,
    supportsVision,
    enabled,
    submit,
    cancel,
    message,
    revision,
    reloadError,
  }) {
    this.list = list;
    this.form = form;
    this.key = key;
    this.displayName = displayName;
    this.baseUrl = baseUrl;
    this.model = model;
    this.authentication = authentication;
    this.apiKey = apiKey;
    this.apiKeyNote = apiKeyNote;
    this.supportsVision = supportsVision;
    this.enabled = enabled;
    this.submit = submit;
    this.cancel = cancel;
    this.message = message;
    this.revision = revision;
    this.reloadError = reloadError;
    this.state = null;
    this.editingKey = null;
    this.editingAuthentication = null;
    this.saveHandler = null;
    this.defaultHandler = null;
    this.deleteHandler = null;

    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!this.saveHandler || !this.state) return;
      if (!this.validateApiKey()) {
        this.showMessage(
          this.editingKey
            ? "managed 인증으로 변경하려면 API key를 입력하세요."
            : "managed 인증 endpoint에는 API key가 필요합니다.",
          true,
        );
        this.apiKey.focus();
        return;
      }
      const payload = {
        key: this.key.value.trim(),
        display_name: this.displayName.value.trim(),
        base_url: this.baseUrl.value.trim(),
        model: this.model.value.trim(),
        authentication: this.authentication.value,
        supports_vision: this.supportsVision.checked,
        enabled: this.enabled.checked,
      };
      const apiKey = this.apiKey.value;
      if (this.authentication.value === "managed" && apiKey.trim()) payload.api_key = apiKey;
      this.saveHandler(this.editingKey, payload, this.state.revision);
    });
    this.authentication.addEventListener("change", () => this.syncAuthenticationInput());
    this.apiKey.addEventListener("input", () => this.validateApiKey());
    this.cancel.addEventListener("click", () => this.resetForm());
    this.list.addEventListener("click", (event) => this.handleListAction(event));
    this.syncAuthenticationInput();
  }

  // endpoint 저장 요청을 controller에 위임한다.
  onSave(handler) {
    this.saveHandler = handler;
  }

  // 기본 endpoint 변경 요청을 controller에 위임한다.
  onSetDefault(handler) {
    this.defaultHandler = handler;
  }

  // endpoint 삭제 요청을 controller에 위임한다.
  onDelete(handler) {
    this.deleteHandler = handler;
  }

  // 서버 상태를 카드 목록과 JSON revision에 반영한다.
  render(state) {
    this.state = state;
    this.revision.textContent = `revision ${state.revision.slice(0, 12)}`;
    this.reloadError.textContent = state.reload_error || "";
    this.list.replaceChildren();
    for (const endpoint of state.endpoints) this.list.append(this.endpointCard(endpoint));
    if (this.editingKey) {
      const current = state.endpoints.find((endpoint) => endpoint.key === this.editingKey);
      if (current) this.beginEdit(current, false);
      else this.resetForm();
    }
  }

  // 비밀을 제외한 endpoint 정보와 관리 작업을 한 카드로 만든다.
  endpointCard(endpoint) {
    const article = document.createElement("article");
    article.className = "llm-endpoint-card";
    article.dataset.enabled = String(endpoint.enabled);

    const heading = document.createElement("div");
    heading.className = "llm-endpoint-heading";
    const title = document.createElement("strong");
    title.textContent = endpoint.display_name;
    const key = document.createElement("code");
    key.textContent = endpoint.key;
    heading.append(title, key);

    const badges = document.createElement("div");
    badges.className = "llm-endpoint-badges";
    if (endpoint.is_default) badges.append(this.badge("기본", "default"));
    badges.append(this.badge(endpoint.enabled ? "활성" : "비활성", endpoint.enabled ? "enabled" : "disabled"));
    badges.append(this.badge(endpoint.supports_vision ? "Vision" : "Text", "capability"));

    const details = document.createElement("dl");
    details.innerHTML = `
      <div><dt>Model</dt><dd></dd></div>
      <div><dt>Base URL</dt><dd></dd></div>
      <div><dt>인증</dt><dd></dd></div>
      <div><dt>API key 상태</dt><dd></dd></div>
    `;
    const values = details.querySelectorAll("dd");
    values[0].textContent = endpoint.model;
    values[1].textContent = endpoint.base_url;
    values[2].textContent = endpoint.authentication === "managed" ? "API key 관리" : "인증 없음";
    values[3].textContent = endpoint.api_key_configured ? "설정됨" : "미설정";

    const actions = document.createElement("div");
    actions.className = "llm-endpoint-actions";
    actions.append(this.actionButton("편집", "edit", endpoint.key));
    if (!endpoint.is_default && endpoint.enabled) {
      actions.append(this.actionButton("기본값 지정", "default", endpoint.key));
    }
    if (!endpoint.is_default) actions.append(this.actionButton("삭제", "delete", endpoint.key, true));
    article.append(heading, badges, details, actions);
    return article;
  }

  // 상태 badge를 데이터 속성과 함께 생성한다.
  badge(text, state) {
    const badge = document.createElement("span");
    badge.className = "llm-endpoint-badge";
    badge.dataset.state = state;
    badge.textContent = text;
    return badge;
  }

  // 이벤트 위임에 사용할 endpoint 작업 버튼을 만든다.
  actionButton(text, action, key, danger = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.dataset.action = action;
    button.dataset.key = key;
    if (danger) button.className = "danger-button";
    return button;
  }

  // 카드 버튼의 편집·기본값·삭제 동작을 분기한다.
  handleListAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button || !this.list.contains(button) || !this.state) return;
    const endpoint = this.state.endpoints.find((item) => item.key === button.dataset.key);
    if (!endpoint) return;
    if (button.dataset.action === "edit") this.beginEdit(endpoint);
    if (button.dataset.action === "default" && this.defaultHandler) {
      this.defaultHandler(endpoint.key, this.state.revision);
    }
    if (button.dataset.action === "delete" && this.deleteHandler) {
      this.deleteHandler(endpoint.key, this.state.revision);
    }
  }

  // 선택 endpoint의 비밀 없는 값을 폼에 채우고 key를 잠근다.
  beginEdit(endpoint, scroll = true) {
    this.editingKey = endpoint.key;
    this.editingAuthentication = endpoint.authentication;
    this.key.value = endpoint.key;
    this.key.disabled = true;
    this.displayName.value = endpoint.display_name;
    this.baseUrl.value = endpoint.base_url;
    this.model.value = endpoint.model;
    this.authentication.value = endpoint.authentication;
    this.apiKey.value = "";
    this.supportsVision.checked = endpoint.supports_vision;
    this.enabled.checked = endpoint.enabled;
    this.submit.textContent = "Endpoint 변경 적용";
    this.cancel.hidden = false;
    this.syncAuthenticationInput();
    this.showMessage("");
    if (scroll) this.form.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // 새 endpoint 입력 상태로 폼과 편집 key를 초기화한다.
  resetForm() {
    this.editingKey = null;
    this.editingAuthentication = null;
    this.form.reset();
    this.key.disabled = false;
    this.enabled.checked = true;
    this.submit.textContent = "Endpoint 연결 확인 후 추가";
    this.cancel.hidden = true;
    this.syncAuthenticationInput();
    this.showMessage("");
  }

  // authentication 종류에 맞는 API key 입력 상태와 안내를 적용한다.
  syncAuthenticationInput() {
    const usesManagedAuthentication = this.authentication.value === "managed";
    if (!usesManagedAuthentication) {
      this.apiKey.value = "";
      this.apiKey.disabled = true;
      this.apiKey.required = false;
      this.apiKeyNote.textContent = "인증 없음으로 연결합니다. API key는 사용하지 않습니다.";
    } else {
      this.apiKey.disabled = false;
      this.apiKey.required = this.apiKeyIsRequired();
      this.apiKeyNote.textContent = this.apiKey.required
        ? "새 managed endpoint에는 API key가 필요합니다."
        : "API key를 비워 두면 기존 managed API key를 유지합니다. 변경하려면 새 API key를 입력하세요.";
    }
    this.validateApiKey();
  }

  // 새 managed endpoint와 none에서 managed로 바꾸는 경우 API key를 요구한다.
  apiKeyIsRequired() {
    return this.authentication.value === "managed"
      && (!this.editingKey || this.editingAuthentication !== "managed");
  }

  // API key가 필요한 경우 빈 입력을 저장 요청으로 보내지 않도록 막는다.
  validateApiKey() {
    const isBlank = !this.apiKey.value.trim();
    const isInvalid = this.apiKeyIsRequired() && isBlank;
    this.apiKey.setCustomValidity(isInvalid ? "API key를 입력하세요." : "");
    return !isInvalid;
  }

  // 저장·삭제 중 endpoint 입력과 카드 버튼을 함께 잠근다.
  setBusy(isBusy) {
    for (const input of this.form.querySelectorAll("input, select, button")) input.disabled = isBusy;
    for (const button of this.list.querySelectorAll("button")) button.disabled = isBusy;
    if (!isBusy) {
      this.key.disabled = Boolean(this.editingKey);
      this.cancel.hidden = !this.editingKey;
      this.syncAuthenticationInput();
    }
  }

  // endpoint 작업 결과를 성공 또는 오류 상태로 표시한다.
  showMessage(message, isError = false) {
    this.message.textContent = message;
    this.message.dataset.state = isError ? "error" : "success";
  }
}
