// 작업공간 계정 메뉴에 연결되어 비밀번호 변경과 회원탈퇴 화면을 제어한다.
export class AccountView {
  // 계정 폼 요소와 변경·탈퇴·닫기 이벤트를 연결한다.
  constructor({
    root,
    username,
    close,
    passwordForm,
    currentPassword,
    newPassword,
    confirmPassword,
    passwordMessage,
    passwordSubmit,
    deleteForm,
    deletePassword,
    deleteConfirmation,
    deleteError,
    deleteSubmit,
  }) {
    this.root = root;
    this.username = username;
    this.close = close;
    this.passwordForm = passwordForm;
    this.currentPassword = currentPassword;
    this.newPassword = newPassword;
    this.confirmPassword = confirmPassword;
    this.passwordMessage = passwordMessage;
    this.passwordSubmit = passwordSubmit;
    this.deleteForm = deleteForm;
    this.deletePassword = deletePassword;
    this.deleteConfirmation = deleteConfirmation;
    this.deleteError = deleteError;
    this.deleteSubmit = deleteSubmit;
    this.passwordHandler = null;
    this.deleteHandler = null;
    this.closeHandler = null;

    this.passwordForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.newPassword.value !== this.confirmPassword.value) {
        this.showPasswordMessage("새 비밀번호가 일치하지 않습니다.", true);
        this.confirmPassword.focus();
        return;
      }
      this.passwordHandler?.(this.currentPassword.value, this.newPassword.value);
    });
    this.deleteForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (this.deleteConfirmation.value.trim().toLowerCase() !== this.username.textContent) {
        this.showDeleteError("사용자명이 일치하지 않습니다.");
        this.deleteConfirmation.focus();
        return;
      }
      if (!window.confirm("계정과 모든 문서 및 대화 이력을 삭제할까요? 이 작업은 되돌릴 수 없습니다.")) {
        return;
      }
      this.deleteHandler?.(this.deletePassword.value, this.deleteConfirmation.value);
    });
    this.close.addEventListener("click", () => this.closeHandler?.());
  }

  // 비밀번호 변경 요청을 처리할 상위 핸들러를 등록한다.
  onPasswordChange(handler) {
    this.passwordHandler = handler;
  }

  // 회원탈퇴 요청을 처리할 상위 핸들러를 등록한다.
  onDelete(handler) {
    this.deleteHandler = handler;
  }

  // 계정 화면 닫기 요청을 처리할 핸들러를 등록한다.
  onClose(handler) {
    this.closeHandler = handler;
  }

  // 현재 사용자 정보로 계정 화면을 열고 입력에 초점을 둔다.
  show(user) {
    this.username.textContent = user.username;
    this.root.hidden = false;
    this.currentPassword.focus();
  }

  // 계정 화면을 닫고 민감한 입력과 메시지를 초기화한다.
  hide() {
    this.root.hidden = true;
    this.passwordForm.reset();
    this.deleteForm.reset();
    this.showPasswordMessage("");
    this.showDeleteError("");
  }

  // 비밀번호 변경 중 관련 입력과 버튼을 잠근다.
  setPasswordBusy(isBusy) {
    for (const element of [
      this.currentPassword,
      this.newPassword,
      this.confirmPassword,
      this.passwordSubmit,
    ]) element.disabled = isBusy;
    this.passwordSubmit.textContent = isBusy ? "변경 중" : "비밀번호 변경";
  }

  // 회원탈퇴 처리 중 관련 입력과 버튼을 잠근다.
  setDeleteBusy(isBusy) {
    for (const element of [
      this.deletePassword,
      this.deleteConfirmation,
      this.deleteSubmit,
    ]) element.disabled = isBusy;
    this.deleteSubmit.textContent = isBusy ? "탈퇴 처리 중" : "회원탈퇴";
  }

  // 비밀번호 변경 결과를 성공 또는 오류 상태로 표시한다.
  showPasswordMessage(message, isError = false) {
    this.passwordMessage.textContent = message;
    this.passwordMessage.dataset.state = isError ? "error" : "success";
  }

  // 회원탈퇴 입력 오류를 화면에 표시한다.
  showDeleteError(message) {
    this.deleteError.textContent = message;
  }

  // 변경 폼을 비우고 현재 비밀번호 입력으로 돌아간다.
  resetPasswordForm() {
    this.passwordForm.reset();
    this.currentPassword.focus();
  }
}
