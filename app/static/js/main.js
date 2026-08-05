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

const byId = (id) => document.getElementById(id);

const documentPanelRoot = byId("document-panel");
const sourcePanelRoot = byId("source-panel");
const backdrop = byId("drawer-backdrop");
const appRoot = byId("app");
const adminRoot = byId("admin-view");
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
});

const documentPanel = new DocumentPanel({
  listRoot: byId("document-list"),
  uploadForm: byId("upload-form"),
  fileInput: byId("pdf-input"),
  uploadStatus: byId("upload-status"),
});

const chatPanel = new ChatPanel({
  title: byId("selected-document-title"),
  status: byId("selected-document-status"),
  messageList: byId("message-list"),
  form: byId("chat-form"),
  input: byId("question-input"),
  sendButton: byId("send-button"),
});

const sourcePanel = new SourcePanel({
  root: sourcePanelRoot,
  title: byId("source-title"),
  pageLabel: byId("source-page-label"),
  content: byId("source-content"),
  closeButton: byId("source-close"),
  mobileToggle: byId("source-mobile-toggle"),
});

const controller = new AppController({
  state: createInitialState(),
  apiClient,
  pollingService: new PollingService(),
  documentPanel,
  chatPanel,
  sourcePanel,
  notificationView: new NotificationView(byId("notification-region")),
});

function syncBackdrop() {
  const open = documentPanelRoot.classList.contains("is-mobile-open")
    || sourcePanelRoot.classList.contains("is-mobile-open");
  backdrop.hidden = !open;
}

function openDocuments() {
  sourcePanelRoot.classList.remove("is-mobile-open");
  documentPanelRoot.classList.add("is-mobile-open");
  byId("documents-toggle").setAttribute("aria-expanded", "true");
  syncBackdrop();
}

function closeDrawers() {
  documentPanelRoot.classList.remove("is-mobile-open");
  sourcePanelRoot.classList.remove("is-mobile-open");
  byId("documents-toggle").setAttribute("aria-expanded", "false");
  syncBackdrop();
}

byId("documents-toggle").addEventListener("click", openDocuments);
byId("documents-close").addEventListener("click", closeDrawers);
byId("document-list").addEventListener("click", (event) => {
  if (event.target.closest("[data-document-id]")
      && window.matchMedia("(max-width: 900px)").matches) closeDrawers();
});
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

function stopAdminRefresh() {
  if (adminRefreshTimer !== null) window.clearTimeout(adminRefreshTimer);
  adminRefreshTimer = null;
}

async function refreshAdminState() {
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

async function openAdmin() {
  controller.pollingService.stopAll();
  appRoot.hidden = true;
  adminView.show();
  await refreshAdminState();
}

function closeAdmin() {
  stopAdminRefresh();
  if (workspaceNeedsRefresh) {
    window.location.reload();
    return;
  }
  adminView.hide();
  appRoot.hidden = false;
}

async function enterWorkspace(user) {
  authView.hide();
  adminView.hide();
  byId("current-username").textContent = user.username;
  byId("admin-username").textContent = user.username;
  byId("admin-button").hidden = user.role !== "admin";
  appRoot.hidden = false;
  if (!controllerStarted) {
    controllerStarted = true;
    await controller.start();
  }
}

authView.onSubmit(async (mode, username, password) => {
  authView.setBusy(true);
  authView.showError("");
  try {
    const result = mode === "register"
      ? await apiClient.register(username, password)
      : await apiClient.login(username, password);
    await enterWorkspace(result.user);
  } catch (error) {
    const message = error.status === 409
      ? "이미 사용 중인 사용자명입니다."
      : error.message;
    authView.showError(message);
  } finally {
    authView.setBusy(false);
  }
});

async function logout() {
  try {
    await apiClient.logout();
  } finally {
    window.location.reload();
  }
}

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

byId("admin-button").addEventListener("click", openAdmin);
byId("admin-close").addEventListener("click", closeAdmin);
byId("logout-button").addEventListener("click", logout);
byId("admin-logout-button").addEventListener("click", logout);

window.addEventListener("authrequired", () => window.location.reload());

async function bootstrap() {
  try {
    const result = await apiClient.getCurrentUser();
    await enterWorkspace(result.user);
  } catch (error) {
    appRoot.hidden = true;
    adminView.hide();
    authView.show();
    if (error.status !== 401) authView.showError(error.message);
  }
}

bootstrap();
