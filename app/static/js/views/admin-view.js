const PRESET_LABELS = {
  fine_grained: "세밀 검색",
  standard: "짧은 문단",
  balanced: "균형",
  broad_context: "넓은 문맥",
  long_form: "긴 서술",
};

const JOB_STATUS_LABELS = {
  pending: "대기 중",
  running: "처리 중",
  completed: "완료",
  completed_with_errors: "일부 실패",
  failed: "실패",
};

// 관리자 라우팅에 연결되어 검색 설정과 유지보수 상태를 렌더링한다.
export class AdminView {
  // 관리 화면 요소와 설정·재시도·비밀번호 초기화 이벤트를 연결한다.
  constructor({
    root,
    presetList,
    form,
    activateButton,
    algorithmList,
    algorithmForm,
    activateAlgorithmButton,
    error,
    activePreset,
    activeAlgorithm,
    indexVersion,
    maintenance,
    jobStatus,
    retryButton,
    passwordResetForm,
    resetUsername,
    temporaryPassword,
    temporaryPasswordConfirmation,
    passwordResetMessage,
    passwordResetButton,
  }) {
    this.root = root;
    this.presetList = presetList;
    this.form = form;
    this.activateButton = activateButton;
    this.algorithmList = algorithmList;
    this.algorithmForm = algorithmForm;
    this.activateAlgorithmButton = activateAlgorithmButton;
    this.error = error;
    this.activePreset = activePreset;
    this.activeAlgorithm = activeAlgorithm;
    this.indexVersion = indexVersion;
    this.maintenance = maintenance;
    this.jobStatus = jobStatus;
    this.retryButton = retryButton;
    this.passwordResetForm = passwordResetForm;
    this.resetUsername = resetUsername;
    this.temporaryPassword = temporaryPassword;
    this.temporaryPasswordConfirmation = temporaryPasswordConfirmation;
    this.passwordResetMessage = passwordResetMessage;
    this.passwordResetButton = passwordResetButton;
    this.state = null;
    this.selectedKey = null;
    this.selectedAlgorithmKey = null;
    this.activateHandler = null;
    this.activateAlgorithmHandler = null;
    this.retryHandler = null;
    this.passwordResetHandler = null;

    this.form.addEventListener("change", () => {
      this.selectedKey = new FormData(this.form).get("preset");
      this.syncActivateButton();
    });
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.activateHandler && this.selectedKey) this.activateHandler(this.selectedKey);
    });
    this.algorithmForm.addEventListener("change", () => {
      this.selectedAlgorithmKey = new FormData(this.algorithmForm).get("algorithm");
      this.syncAlgorithmButton();
    });
    this.algorithmForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.activateAlgorithmHandler && this.selectedAlgorithmKey) {
        this.activateAlgorithmHandler(this.selectedAlgorithmKey);
      }
    });
    this.retryButton.addEventListener("click", () => {
      if (this.retryHandler && this.state?.latest_job) this.retryHandler(this.state.latest_job.job_id);
    });
    this.passwordResetForm.addEventListener("submit", (event) => {
      event.preventDefault();
      this.showPasswordResetMessage("");
      if (this.temporaryPassword.value !== this.temporaryPasswordConfirmation.value) {
        this.showPasswordResetMessage("임시 비밀번호 확인이 일치하지 않습니다.", true);
        this.temporaryPasswordConfirmation.focus();
        return;
      }
      if (this.passwordResetHandler) {
        this.passwordResetHandler(this.resetUsername.value.trim(), this.temporaryPassword.value);
      }
    });
  }

  // 청킹 프리셋 적용 요청을 처리할 핸들러를 등록한다.
  onActivate(handler) {
    this.activateHandler = handler;
  }

  // 실패한 재인덱싱 작업의 재시도 핸들러를 등록한다.
  onRetry(handler) {
    this.retryHandler = handler;
  }

  // 검색 알고리즘 적용 요청을 처리할 핸들러를 등록한다.
  onActivateAlgorithm(handler) {
    this.activateAlgorithmHandler = handler;
  }

  // 사용자 임시 비밀번호 설정 핸들러를 등록한다.
  onPasswordReset(handler) {
    this.passwordResetHandler = handler;
  }

  // 관리자 화면을 표시한다.
  show() {
    this.root.hidden = false;
  }

  // 관리자 화면을 숨긴다.
  hide() {
    this.root.hidden = true;
  }

  // 서버 관리 상태로 프리셋과 작업 현황을 다시 그린다.
  render(state) {
    this.state = state;
    this.selectedKey = state.pending_preset_key || state.active_preset_key;
    this.selectedAlgorithmKey = state.active_search_algorithm_key;
    this.activePreset.textContent = state.active_preset_key;
    this.activeAlgorithm.textContent = state.active_search_algorithm_key;
    this.indexVersion.textContent = String(state.index_version);
    this.maintenance.textContent = state.maintenance_mode ? "재인덱싱 중" : "사용 가능";
    this.maintenance.dataset.state = state.maintenance_mode ? "busy" : "ready";
    this.presetList.replaceChildren();

    for (const preset of state.presets) {
      const label = document.createElement("label");
      label.className = "preset-option";
      label.dataset.active = String(preset.key === state.active_preset_key);

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "preset";
      input.value = preset.key;
      input.checked = preset.key === this.selectedKey;
      input.disabled = state.maintenance_mode;

      const heading = document.createElement("span");
      heading.className = "preset-option-heading";
      heading.textContent = PRESET_LABELS[preset.key] || preset.display_name;

      const key = document.createElement("code");
      key.textContent = preset.key;

      const values = document.createElement("span");
      values.className = "preset-values";
      values.textContent = `${preset.chunk_size_chars} / overlap ${preset.chunk_overlap_chars} / top ${preset.top_k}`;

      heading.append(key);
      label.append(input, heading, values);
      this.presetList.append(label);
    }

    this.renderAlgorithms(state);
    this.renderJob(state.latest_job);
    this.syncActivateButton();
    this.syncAlgorithmButton();
  }

  // 선택 가능한 검색 알고리즘 카드를 렌더링한다.
  renderAlgorithms(state) {
    this.algorithmList.replaceChildren();
    for (const algorithm of state.search_algorithms) {
      const label = document.createElement("label");
      label.className = "algorithm-option";
      label.dataset.active = String(algorithm.key === state.active_search_algorithm_key);

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "algorithm";
      input.value = algorithm.key;
      input.checked = algorithm.key === this.selectedAlgorithmKey;
      input.disabled = state.maintenance_mode;

      const heading = document.createElement("span");
      heading.className = "algorithm-option-heading";
      heading.textContent = algorithm.display_name;

      const key = document.createElement("code");
      key.textContent = algorithm.key;

      const description = document.createElement("span");
      description.className = "algorithm-description";
      description.textContent = algorithm.description;

      heading.append(key);
      label.append(input, heading, description);
      this.algorithmList.append(label);
    }
  }


  // 최근 재인덱싱 작업의 진행 및 실패 상태를 표시한다.
  renderJob(job) {
    this.jobStatus.removeAttribute("title");
    this.retryButton.hidden = !job || !["failed", "completed_with_errors"].includes(job.status);
    if (!job) {
      this.jobStatus.textContent = "작업 이력이 없습니다.";
      this.jobStatus.dataset.state = "empty";
      return;
    }

    const status = JOB_STATUS_LABELS[job.status] || job.status;
    this.jobStatus.textContent = `${status} · ${job.completed_documents}/${job.total_documents} 완료 · ${job.failed_documents} 실패`;
    this.jobStatus.dataset.state = job.status;
    if (job.error_message) this.jobStatus.title = job.error_message;
  }

  // 설정 변경 중이거나 유지보수 중인 관리 입력을 잠근다.
  setBusy(isBusy) {
    const locked = isBusy || Boolean(this.state?.maintenance_mode);
    for (const input of this.presetList.querySelectorAll("input")) input.disabled = locked;
    for (const input of this.algorithmList.querySelectorAll("input")) input.disabled = locked;
    this.retryButton.disabled = locked;
    if (isBusy) {
      this.activateButton.disabled = true;
    } else {
      this.syncActivateButton();
    }
    if (isBusy) {
      this.activateAlgorithmButton.disabled = true;
    } else {
      this.syncAlgorithmButton();
    }
  }

  // 임시 비밀번호 적용 중 보안 입력을 잠근다.
  setPasswordResetBusy(isBusy) {
    this.resetUsername.disabled = isBusy;
    this.temporaryPassword.disabled = isBusy;
    this.temporaryPasswordConfirmation.disabled = isBusy;
    this.passwordResetButton.disabled = isBusy;
  }

  // 임시 비밀번호 설정 결과를 성공 또는 오류로 표시한다.
  showPasswordResetMessage(message, isError = false) {
    this.passwordResetMessage.textContent = message;
    this.passwordResetMessage.dataset.state = isError ? "error" : "success";
  }

  // 임시 비밀번호 폼의 민감한 입력을 비운다.
  resetPasswordResetForm() {
    this.passwordResetForm.reset();
  }

  // 관리 설정 오류를 화면에 표시한다.
  showError(message) {
    this.error.textContent = message;
  }


  // 현재 프리셋과 선택값에 따라 적용 버튼을 동기화한다.
  syncActivateButton() {
    this.activateButton.disabled = !this.state
      || this.state.maintenance_mode
      || !this.selectedKey
      || this.selectedKey === this.state.active_preset_key;
  }

  // 현재 알고리즘과 선택값에 따라 적용 버튼을 동기화한다.
  syncAlgorithmButton() {
    this.activateAlgorithmButton.disabled = !this.state
      || this.state.maintenance_mode
      || !this.selectedAlgorithmKey
      || this.selectedAlgorithmKey === this.state.active_search_algorithm_key;
  }
}
