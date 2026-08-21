import { ApiClient } from "./api-client.js";
import { AppController } from "./app-controller.js";
import { PollingService } from "./polling-service.js";
import { createInitialState } from "./state.js";
import { ChatPanel } from "./views/chat-panel.js";
import { DocumentPanel } from "./views/document-panel.js";
import { NotificationView } from "./views/notification-view.js";
import { SourcePanel } from "./views/source-panel.js";
import { AuthView } from "./views/auth-view.js";
import { AdminView } from "./views/admin-view.js";
import { LanguageModelAdminView } from "./views/language-model-admin-view.js";
import { PasswordChangeView } from "./views/password-change-view.js";
import { AccountView } from "./views/account-view.js";

// 화면 요소를 의존성 구성에 연결할 때 ID 조회를 통일한다.
const byId = (id) => document.getElementById(id);

const documentPanelRoot = byId("document-panel");
const sourcePanelRoot = byId("source-panel");
const backdrop = byId("drawer-backdrop");
const appRoot = byId("app");
const workspaceRoot = appRoot.querySelector(".workspace");
const documentPanelCollapse = byId("document-panel-collapse");
const sourcePanelCollapse = byId("source-panel-collapse");
const adminRoot = byId("admin-view");
const passwordChangeRoot = byId("password-change-view");
const accountRoot = byId("account-view");
const apiClient = new ApiClient();

const authView = new AuthView({
  root: byId("auth-view"),
  form: byId("auth-form"),
  title: byId("auth-title"),
  username: byId("auth-username"),
  password: byId("auth-password"),
  error: byId("auth-error"),
  submit: byId("auth-submit"),
  loginTab: byId("login-tab"),
  registerTab: byId("register-tab"),
});

const adminView = new AdminView({
  root: adminRoot,
  presetList: byId("preset-list"),
  form: byId("preset-form"),
  activateButton: byId("activate-preset-button"),
  algorithmList: byId("algorithm-list"),
  algorithmForm: byId("algorithm-form"),
  activateAlgorithmButton: byId("activate-algorithm-button"),
  error: byId("preset-error"),
  activePreset: byId("active-preset"),
  activeAlgorithm: byId("active-algorithm"),
  indexVersion: byId("active-index-version"),
  maintenance: byId("maintenance-status"),
  jobStatus: byId("job-status"),
  retryButton: byId("retry-job-button"),
  passwordResetForm: byId("admin-password-reset-form"),
  resetUsername: byId("reset-username"),
  temporaryPassword: byId("reset-temporary-password"),
  temporaryPasswordConfirmation: byId("reset-temporary-password-confirmation"),
  passwordResetMessage: byId("admin-password-reset-message"),
  passwordResetButton: byId("admin-password-reset-button"),
});

const languageModelAdminView = new LanguageModelAdminView({
  list: byId("llm-endpoint-list"),
  form: byId("llm-endpoint-form"),
  key: byId("llm-endpoint-key"),
  displayName: byId("llm-endpoint-display-name"),
  baseUrl: byId("llm-endpoint-base-url"),
  model: byId("llm-endpoint-model"),
  authentication: byId("llm-endpoint-authentication"),
  apiKey: byId("llm-endpoint-api-key"),
  apiKeyNote: byId("llm-endpoint-api-key-note"),
  supportsVision: byId("llm-endpoint-supports-vision"),
  enabled: byId("llm-endpoint-enabled"),
  submit: byId("llm-endpoint-submit"),
  cancel: byId("llm-endpoint-cancel"),
  message: byId("llm-endpoint-message"),
  revision: byId("llm-config-revision"),
  reloadError: byId("llm-reload-error"),
});

const passwordChangeView = new PasswordChangeView({
  root: passwordChangeRoot,
  form: byId("password-change-form"),
  currentPassword: byId("current-password"),
  newPassword: byId("new-password"),
  confirmPassword: byId("confirm-password"),
  error: byId("password-change-error"),
  submit: byId("password-change-submit"),
  logout: byId("password-change-logout"),
});

const accountView = new AccountView({
  root: accountRoot,
  username: byId("account-username"),
  close: byId("account-close"),
  passwordForm: byId("account-password-form"),
  currentPassword: byId("account-current-password"),
  newPassword: byId("account-new-password"),
  confirmPassword: byId("account-confirm-password"),
  passwordMessage: byId("account-password-message"),
  passwordSubmit: byId("account-password-submit"),
  deleteForm: byId("account-delete-form"),
  deletePassword: byId("account-delete-password"),
  deleteConfirmation: byId("account-delete-confirmation"),
  deleteError: byId("account-delete-error"),
  deleteSubmit: byId("account-delete-submit"),
});

const documentPanel = new DocumentPanel({
  listRoot: byId("document-list"),
  uploadForm: byId("upload-form"),
  fileInput: byId("pdf-input"),
  uploadStatus: byId("upload-status"),
  refreshButton: byId("documents-refresh"),
});

const chatPanel = new ChatPanel({
  status: byId("workspace-chat-status"),
  messageList: byId("message-list"),
  form: byId("chat-form"),
  input: byId("question-input"),
  sendButton: byId("send-button"),
  sessionSelect: byId("conversation-select"),
  newSessionButton: byId("new-conversation-button"),
  deleteSessionButton: byId("delete-conversation-button"),
});

const sourcePanel = new SourcePanel({
  root: sourcePanelRoot,
  title: byId("source-title"),
  pageLabel: byId("source-page-label"),
  content: byId("source-content"),
  closeButton: byId("source-close"),
  mobileToggle: byId("source-mobile-toggle"),
});

const notificationView = new NotificationView(byId("notification-region"));
const languageModelSelect = byId("language-model-select");

// 공유 상태와 화면·통신 서비스를 단일 컨트롤러에 연결한다.
const controller = new AppController({
  state: createInitialState(),
  apiClient,
  pollingService: new PollingService(),
  documentPanel,
  chatPanel,
  sourcePanel,
  notificationView,
});

// 데스크톱 문서 목록을 좁은 복원 레일로 접거나 원래 너비로 펼친다.
function setDocumentPanelCollapsed(collapsed) {
  const actionLabel = collapsed ? "문서 목록 펼치기" : "문서 목록 숨기기";
  workspaceRoot.classList.toggle("is-document-panel-collapsed", collapsed);
  documentPanelCollapse.setAttribute("aria-expanded", String(!collapsed));
  documentPanelCollapse.setAttribute("aria-label", actionLabel);
  documentPanelCollapse.title = actionLabel;
  documentPanelCollapse.querySelector("[aria-hidden]").textContent = collapsed ? "›" : "‹";
}

// 데스크톱 PDF 미리보기를 좁은 복원 레일로 접거나 원래 너비로 펼친다.
function setSourcePanelCollapsed(collapsed) {
  const actionLabel = collapsed ? "PDF 미리보기 펼치기" : "PDF 미리보기 숨기기";
  workspaceRoot.classList.toggle("is-source-panel-collapsed", collapsed);
  sourcePanelCollapse.setAttribute("aria-expanded", String(!collapsed));
  sourcePanelCollapse.setAttribute("aria-label", actionLabel);
  sourcePanelCollapse.title = actionLabel;
  sourcePanelCollapse.querySelector("[aria-hidden]").textContent = collapsed ? "‹" : "›";
}

// 모바일 서랍 상태에 맞춰 공통 배경막을 동기화한다.
function syncBackdrop() {
  const open = documentPanelRoot.classList.contains("is-mobile-open")
    || sourcePanelRoot.classList.contains("is-mobile-open");
  backdrop.hidden = !open;
}

// 모바일에서 문서 서랍만 열어 패널 충돌을 막는다.
function openDocuments() {
  sourcePanelRoot.classList.remove("is-mobile-open");
  documentPanelRoot.classList.add("is-mobile-open");
  byId("documents-toggle").setAttribute("aria-expanded", "true");
  syncBackdrop();
}

// 열린 모바일 서랍을 모두 닫고 접근성 상태를 갱신한다.
function closeDrawers() {
  documentPanelRoot.classList.remove("is-mobile-open");
  sourcePanelRoot.classList.remove("is-mobile-open");
  byId("documents-toggle").setAttribute("aria-expanded", "false");
  syncBackdrop();
}

documentPanelCollapse.addEventListener("click", () => {
  setDocumentPanelCollapsed(!workspaceRoot.classList.contains("is-document-panel-collapsed"));
});
sourcePanelCollapse.addEventListener("click", () => {
  setSourcePanelCollapsed(!workspaceRoot.classList.contains("is-source-panel-collapsed"));
});

byId("documents-toggle").addEventListener("click", openDocuments);
byId("documents-close").addEventListener("click", closeDrawers);
byId("source-close").addEventListener("click", closeDrawers);
byId("source-mobile-toggle").addEventListener("click", () => {
  documentPanelRoot.classList.remove("is-mobile-open");
  sourcePanelRoot.classList.add("is-mobile-open");
  syncBackdrop();
});
backdrop.addEventListener("click", closeDrawers);
sourcePanelRoot.addEventListener("panelvisibilitychange", syncBackdrop);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawers();
});
window.addEventListener("beforeunload", () => controller.pollingService.stopAll());

let controllerStarted = false;
let adminRefreshTimer = null;
let workspaceNeedsRefresh = false;
let currentUser = null;
let accountReturnView = "workspace";

// 관리자 화면을 벗어날 때 예약된 갱신을 해제한다.
function stopAdminRefresh() {
  if (adminRefreshTimer !== null) window.clearTimeout(adminRefreshTimer);
  adminRefreshTimer = null;
}

// 유지보수 작업이 진행되는 동안만 관리자 상태를 다시 조회한다.
async function refreshAdminState() {
  // 유지보수나 작업이 끝나면 아래에서 다음 조회를 예약하지 않는다.
  stopAdminRefresh();
  try {
    const state = await apiClient.getRetrievalAdminState();
    adminView.render(state);
    const jobIsActive = ["pending", "running"].includes(state.latest_job?.status);
    if (state.maintenance_mode || jobIsActive) {
      adminRefreshTimer = window.setTimeout(refreshAdminState, 1000);
    }
  } catch (error) {
    adminView.showError(error.message);
  }
}

// 관리자용 JSON endpoint 전체 상태와 revision을 카드 목록에 반영한다.
async function refreshLanguageModelAdminState() {
  try {
    const state = await apiClient.getLanguageModelAdminState();
    languageModelAdminView.render(state);
  } catch (error) {
    languageModelAdminView.showMessage(error.message, true);
  }
}

// 작업공간 폴링을 멈추고 관리자 화면으로 전환한다.
async function openAdmin() {
  controller.pollingService.stopAll();
  appRoot.hidden = true;
  adminView.show();
  await Promise.all([refreshAdminState(), refreshLanguageModelAdminState()]);
}

// 설정 변경 여부에 따라 작업공간을 복원하거나 새로고침한다.
function closeAdmin() {
  stopAdminRefresh();
  if (workspaceNeedsRefresh) {
    window.location.reload();
    return;
  }
  adminView.hide();
  appRoot.hidden = false;
}

// 사용 가능한 언어모델과 현재 선택을 셀렉트에 반영한다.
async function loadLanguageModels() {
  languageModelSelect.disabled = true;
  const state = await apiClient.getLanguageModelState();
  languageModelSelect.replaceChildren();
  for (const endpoint of state.endpoints) {
    const option = document.createElement("option");
    option.value = endpoint.key;
    option.textContent = endpoint.display_name;
    option.title = `${endpoint.model} · ${endpoint.supports_vision ? "Vision 지원" : "텍스트 전용"}`;
    option.selected = endpoint.key === state.active_endpoint_key;
    languageModelSelect.append(option);
  }
  languageModelSelect.dataset.activeKey = state.active_endpoint_key;
  languageModelSelect.disabled = state.endpoints.length < 2;
}

// 인증된 사용자의 작업공간을 열고 컨트롤러를 최초 한 번 시작한다.
async function enterWorkspace(user) {
  currentUser = user;
  authView.hide();
  passwordChangeView.hide();
  accountView.hide();
  adminView.hide();
  byId("current-username").textContent = user.username;
  byId("admin-username").textContent = user.username;
  byId("admin-button").hidden = user.role !== "admin";
  appRoot.hidden = false;
  try {
    await loadLanguageModels();
  } catch (error) {
    notificationView.showError(`언어모델 설정을 불러오지 못했습니다: ${error.message}`);
  }
  // 화면을 다시 열 때는 같은 컨트롤러의 상태만 갱신한다.
  if (!controllerStarted) {
    controllerStarted = true;
    await controller.start();
  }
}

// 비밀번호 변경 의무에 따라 인증 사용자의 진입 화면을 결정한다.
async function routeAuthenticatedUser(user) {
  currentUser = user;
  if (user.must_change_password) {
    authView.hide();
    adminView.hide();
    appRoot.hidden = true;
    passwordChangeView.show();
    return;
  }
  await enterWorkspace(user);
}

authView.onSubmit(async (mode, username, password) => {
  authView.setBusy(true);
  authView.showError("");
  try {
    const result = mode === "register"
      ? await apiClient.register(username, password)
      : await apiClient.login(username, password);
    await routeAuthenticatedUser(result.user);
  } catch (error) {
    const message = error.status === 409
      ? "이미 사용 중인 사용자명입니다."
      : error.message;
    authView.showError(message);
  } finally {
    authView.setBusy(false);
  }
});

// 서버 세션 종료 결과와 무관하게 로컬 화면을 초기화한다.
async function logout() {
  try {
    await apiClient.logout();
  } finally {
    window.location.reload();
  }
}

passwordChangeView.onSubmit(async (currentPassword, newPassword) => {
  passwordChangeView.setBusy(true);
  passwordChangeView.showError("");
  try {
    const result = await apiClient.changePassword(currentPassword, newPassword);
    await enterWorkspace(result.user);
  } catch (error) {
    passwordChangeView.showError(error.message);
  } finally {
    passwordChangeView.setBusy(false);
  }
});

passwordChangeView.onLogout(logout);

// 현재 화면을 기억한 뒤 계정 관리 화면으로 전환한다.
function openAccount(returnView = "workspace") {
  if (!currentUser) return;
  accountReturnView = returnView;
  stopAdminRefresh();
  appRoot.hidden = true;
  adminView.hide();
  accountView.show(currentUser);
}

// 계정 관리 진입 전 화면으로 돌아간다.
function closeAccount() {
  accountView.hide();
  if (accountReturnView === "admin") {
    adminView.show();
    Promise.all([refreshAdminState(), refreshLanguageModelAdminState()]);
  } else {
    appRoot.hidden = false;
  }
}

accountView.onPasswordChange(async (currentPassword, newPassword) => {
  accountView.setPasswordBusy(true);
  accountView.showPasswordMessage("");
  try {
    const result = await apiClient.changePassword(currentPassword, newPassword);
    currentUser = result.user;
    accountView.resetPasswordForm();
    accountView.showPasswordMessage("비밀번호를 변경했습니다.");
  } catch (error) {
    accountView.showPasswordMessage(error.message, true);
  } finally {
    accountView.setPasswordBusy(false);
  }
});

accountView.onDelete(async (currentPassword, usernameConfirmation) => {
  accountView.setDeleteBusy(true);
  accountView.showDeleteError("");
  try {
    await apiClient.deleteAccount(currentPassword, usernameConfirmation);
    window.location.reload();
  } catch (error) {
    accountView.showDeleteError(error.message);
    accountView.setDeleteBusy(false);
  }
});

accountView.onClose(closeAccount);

adminView.onActivate(async (presetKey) => {
  if (!window.confirm(`${presetKey} preset을 적용할까요? 필요한 경우 전체 문서를 다시 인덱싱합니다.`)) return;
  adminView.setBusy(true);
  adminView.showError("");
  try {
    await apiClient.activateRetrievalPreset(presetKey);
    workspaceNeedsRefresh = true;
    await refreshAdminState();
  } catch (error) {
    adminView.showError(error.message);
  } finally {
    adminView.setBusy(false);
  }
});

adminView.onRetry(async (jobId) => {
  adminView.setBusy(true);
  adminView.showError("");
  try {
    await apiClient.retryReindexJob(jobId);
    workspaceNeedsRefresh = true;
    await refreshAdminState();
  } catch (error) {
    adminView.showError(error.message);
  } finally {
    adminView.setBusy(false);
  }
});

adminView.onActivateAlgorithm(async (algorithmKey) => {
  if (!window.confirm(`${algorithmKey} 검색 알고리즘을 적용할까요?`)) return;
  adminView.setBusy(true);
  adminView.showError("");
  try {
    await apiClient.activateSearchAlgorithm(algorithmKey);
    await refreshAdminState();
  } catch (error) {
    adminView.showError(error.message);
  } finally {
    adminView.setBusy(false);
  }
});

languageModelAdminView.onSave(async (editingKey, payload, revision) => {
  languageModelAdminView.setBusy(true);
  languageModelAdminView.showMessage("");
  try {
    const state = editingKey
      ? await apiClient.updateLanguageModelEndpoint(editingKey, payload, revision)
      : await apiClient.createLanguageModelEndpoint(payload, revision);
    languageModelAdminView.render(state);
    languageModelAdminView.resetForm();
    await loadLanguageModels();
    languageModelAdminView.showMessage(
      editingKey ? "Endpoint 변경을 JSON에 적용했습니다." : "Endpoint를 JSON에 추가했습니다.",
    );
  } catch (error) {
    if (error.status === 409) await refreshLanguageModelAdminState();
    languageModelAdminView.showMessage(error.message, true);
  } finally {
    languageModelAdminView.setBusy(false);
  }
});

languageModelAdminView.onSetDefault(async (endpointKey, revision) => {
  if (!window.confirm(`${endpointKey} endpoint를 기본값으로 지정할까요?`)) return;
  languageModelAdminView.setBusy(true);
  languageModelAdminView.showMessage("");
  try {
    const state = await apiClient.setDefaultLanguageModelEndpoint(endpointKey, revision);
    languageModelAdminView.render(state);
    await loadLanguageModels();
    languageModelAdminView.showMessage("기본 endpoint를 변경했습니다.");
  } catch (error) {
    if (error.status === 409) await refreshLanguageModelAdminState();
    languageModelAdminView.showMessage(error.message, true);
  } finally {
    languageModelAdminView.setBusy(false);
  }
});

languageModelAdminView.onDelete(async (endpointKey, revision) => {
  if (!window.confirm(`${endpointKey} endpoint를 삭제할까요? 해당 사용자는 다음 요청부터 기본값을 사용합니다.`)) {
    return;
  }
  languageModelAdminView.setBusy(true);
  languageModelAdminView.showMessage("");
  try {
    const state = await apiClient.deleteLanguageModelEndpoint(endpointKey, revision);
    languageModelAdminView.render(state);
    await loadLanguageModels();
    languageModelAdminView.showMessage("Endpoint를 JSON에서 삭제했습니다.");
  } catch (error) {
    if (error.status === 409) await refreshLanguageModelAdminState();
    languageModelAdminView.showMessage(error.message, true);
  } finally {
    languageModelAdminView.setBusy(false);
  }
});


adminView.onPasswordReset(async (username, temporaryPassword) => {
  adminView.setPasswordResetBusy(true);
  adminView.showPasswordResetMessage("");
  try {
    const user = await apiClient.resetUserPassword(username, temporaryPassword);
    adminView.resetPasswordResetForm();
    adminView.showPasswordResetMessage(
      `${user.username} 사용자의 임시 비밀번호를 설정하고 기존 세션을 종료했습니다.`,
    );
  } catch (error) {
    adminView.showPasswordResetMessage(error.message, true);
  } finally {
    adminView.setPasswordResetBusy(false);
  }
});

byId("admin-button").addEventListener("click", openAdmin);
byId("admin-close").addEventListener("click", closeAdmin);
byId("account-button").addEventListener("click", () => openAccount("workspace"));
byId("admin-account-button").addEventListener("click", () => openAccount("admin"));
byId("logout-button").addEventListener("click", logout);
byId("admin-logout-button").addEventListener("click", logout);

window.addEventListener("authrequired", () => window.location.reload());

languageModelSelect.addEventListener("change", async () => {
  const previousKey = languageModelSelect.dataset.activeKey || "";
  const endpointKey = languageModelSelect.value;
  languageModelSelect.disabled = true;
  try {
    const state = await apiClient.activateLanguageModel(endpointKey);
    languageModelSelect.dataset.activeKey = state.active_endpoint_key;
    await loadLanguageModels();
    notificationView.showStatus("언어모델을 변경했습니다.");
  } catch (error) {
    if (previousKey) languageModelSelect.value = previousKey;
    languageModelSelect.disabled = false;
    notificationView.showError(`언어모델을 변경하지 못했습니다: ${error.message}`);
  }
});

// 현재 세션을 확인해 인증 화면과 작업공간 중 시작 화면을 고른다.
async function bootstrap() {
  try {
    const result = await apiClient.getCurrentUser();
    await routeAuthenticatedUser(result.user);
  } catch (error) {
    appRoot.hidden = true;
    adminView.hide();
    passwordChangeView.hide();
    accountView.hide();
    authView.show();
    if (error.status !== 401) authView.showError(error.message);
  }
}

bootstrap();
