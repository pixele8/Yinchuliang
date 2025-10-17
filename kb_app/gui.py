"""Desktop user interface for the offline knowledge base system."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QRunnable,
    QPoint,
    QPropertyAnimation,
    Qt,
    QThreadPool,
    Signal,
    Slot,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .bootstrap import DEMO_PASSWORD, DEMO_USERNAME, ensure_seed_data
from .corpus_service import CorpusService, IngestReport, KnowledgeCorpus
from .history_service import HistoryService
from .knowledge_service import KnowledgeService
from .user_service import UserService

DEFAULT_DB = Path.home() / "OfflineKnowledge" / "knowledge.db"


def ensure_app_database(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    result = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # pragma: no cover - GUI worker threads
            traceback.print_exc()
            self.signals.error.emit(str(exc))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class GradientCanvas(QWidget):
    """Background widget providing a vibrant gradient backdrop."""

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(219, 234, 254))
        gradient.setColorAt(0.35, QColor(191, 219, 254))
        gradient.setColorAt(0.7, QColor(224, 242, 254))
        gradient.setColorAt(1.0, QColor(240, 249, 255))
        painter.fillRect(self.rect(), gradient)


class ElevatedCard(QFrame):
    """Semi-transparent card with soft shadow for glassmorphism aesthetics."""

    def __init__(
        self,
        *,
        parent: Optional[QWidget] = None,
        corner_radius: int = 22,
        top_color: QColor | None = None,
        bottom_color: QColor | None = None,
        shadow_blur: int = 28,
    ) -> None:
        super().__init__(parent)
        self.corner_radius = corner_radius
        self.top_color = top_color or QColor(255, 255, 255, 245)
        self.bottom_color = bottom_color or QColor(255, 255, 255, 220)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(shadow_blur)
        shadow.setOffset(0, 18)
        shadow.setColor(QColor(15, 23, 42, 45))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)
        path = QPainterPath()
        path.addRoundedRect(rect, self.corner_radius, self.corner_radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, self.top_color)
        gradient.setColorAt(1.0, self.bottom_color)
        painter.fillPath(path, gradient)
        border_color = QColor(255, 255, 255, 140)
        painter.setPen(border_color)
        painter.drawPath(path)


class AnimatedStack(QStackedWidget):
    """Stacked widget with a soft fade transition when switching views."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_animation: Optional[QPropertyAnimation] = None

    def setCurrentWidgetAnimated(self, widget: QWidget) -> None:
        if self.currentWidget() is widget:
            return
        index = self.indexOf(widget)
        if index == -1:
            raise ValueError("Target widget has not been added to the stack")

        super().setCurrentWidget(widget)

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(420)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.InOutCubic)

        def _cleanup() -> None:
            widget.setGraphicsEffect(None)

        animation.finished.connect(_cleanup)
        animation.start(QPropertyAnimation.DeleteWhenStopped)
        self._current_animation = animation


class NavigationPill(QPushButton):
    """Rounded navigation button with icon and neon hover glow."""

    def __init__(self, text: str, icon: QPixmap, *, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(QIcon(icon))
        self.setIconSize(icon.size())
        self.setObjectName("NavigationPill")


class NeonMenuBar(ElevatedCard):
    """Top-level navigation inspired by premium security dashboards."""

    selection_changed = Signal(str)

    def __init__(self, *, parent: Optional[QWidget] = None):
        super().__init__(
            parent=parent,
            corner_radius=28,
            top_color=QColor(56, 189, 248, 245),
            bottom_color=QColor(37, 99, 235, 230),
            shadow_blur=44,
        )
        self._buttons: dict[str, NavigationPill] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 20)
        layout.setSpacing(18)

        entries = [
            ("dashboard", "系统概览", QStyle.SP_ComputerIcon),
            ("chat", "智能问答", QStyle.SP_MessageBoxInformation),
            ("history", "决策档案", QStyle.SP_FileDialogDetailedView),
            ("corpus", "知识库管理", QStyle.SP_DirOpenIcon),
            ("settings", "系统设置", QStyle.SP_FileDialogInfoView),
        ]

        for key, label, icon_role in entries:
            button = NavigationPill(label, self.style().standardIcon(icon_role).pixmap(36, 36))
            button.toggled.connect(self._update_state)
            layout.addWidget(button)
            self._buttons[key] = button

        layout.addStretch(1)
        self.setFixedHeight(96)
        self._active_key: Optional[str] = None
        self.set_active("chat")

    def buttons(self) -> dict[str, NavigationPill]:
        return self._buttons

    def set_active(self, key: str) -> None:
        if key not in self._buttons:
            return
        if self._active_key == key:
            return
        for k, button in self._buttons.items():
            block = button.blockSignals(True)
            button.setChecked(k == key)
            button.blockSignals(block)
        self._active_key = key
        self.selection_changed.emit(key)

    def _update_state(self, checked: bool) -> None:
        if not checked:
            return
        button = self.sender()
        if not isinstance(button, NavigationPill):
            return
        for key, candidate in self._buttons.items():
            if candidate is button:
                self._trigger_glow(candidate)
                self.set_active(key)
                break

    def _trigger_glow(self, button: NavigationPill) -> None:
        effect = QGraphicsOpacityEffect(button)
        button.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", button)
        animation.setDuration(520)
        animation.setStartValue(0.0)
        animation.setKeyValueAt(0.6, 1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def _cleanup() -> None:
            button.setGraphicsEffect(None)

        animation.finished.connect(_cleanup)
        animation.start(QPropertyAnimation.DeleteWhenStopped)

class TitleBar(QWidget):
    """Custom frameless window chrome with drag support."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self._window = window
        self._drag_pos: Optional[QPoint] = None
        self.setFixedHeight(56)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(16)

        icon_label = QLabel()
        icon = window.style().standardIcon(QStyle.SP_FileDialogInfoView).pixmap(28, 28)
        icon_label.setPixmap(icon)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        self.title_label = QLabel("离线知识库决策平台")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        layout.addWidget(self.title_label, 0, Qt.AlignVCenter)

        layout.addStretch(1)

        self.min_button = QToolButton()
        self.min_button.setIcon(window.style().standardIcon(QStyle.SP_TitleBarMinButton))
        self.min_button.clicked.connect(window.showMinimized)

        self.max_button = QToolButton()
        self.max_button.clicked.connect(self._toggle_max_restore)

        self.close_button = QToolButton()
        self.close_button.setIcon(window.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.clicked.connect(window.close)

        for button in (self.min_button, self.max_button, self.close_button):
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            layout.addWidget(button, 0, Qt.AlignVCenter)

        self.update_max_restore_icon()

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor(248, 250, 252, 245))
        gradient.setColorAt(1.0, QColor(224, 231, 255, 240))
        painter.fillRect(self.rect(), gradient)
        painter.setPen(QColor(148, 163, 184, 120))
        painter.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton and not self._window.isMaximized():
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._toggle_max_restore()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _toggle_max_restore(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.update_max_restore_icon()

    def update_max_restore_icon(self) -> None:
        if self._window.isMaximized():
            icon = self._window.style().standardIcon(QStyle.SP_TitleBarNormalButton)
        else:
            icon = self._window.style().standardIcon(QStyle.SP_TitleBarMaxButton)
        self.max_button.setIcon(icon)

class AuthView(QWidget):
    """Authentication view with login and registration forms."""

    authenticated = Signal(str)

    def __init__(self, user_service: UserService):
        super().__init__()
        self.user_service = user_service
        self._showing_register = False
        self._build_ui()
        self._show_login()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(32)

        hero_card = ElevatedCard(
            corner_radius=28,
            top_color=QColor(59, 130, 246, 235),
            bottom_color=QColor(124, 58, 237, 215),
            shadow_blur=42,
        )
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(32, 36, 32, 36)
        hero_layout.setSpacing(18)

        hero_title = QLabel("离线知识库·智享决策")
        hero_title.setStyleSheet("font-size: 28px; font-weight: 700; color: white;")
        hero_subtitle = QLabel(
            "通过本地知识库与决策链档案，让工程团队在离线环境中也能获取可靠答案。"
        )
        hero_subtitle.setWordWrap(True)
        hero_subtitle.setStyleSheet("font-size: 15px; color: rgba(255,255,255,0.92);")
        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_subtitle)

        hero_points = QLabel(
            "• 支持多知识库文件夹挂载，自动解析 Markdown、JSON 等格式。\n"
            "• 记录决策链与评价，快速复用最佳实践。\n"
            "• 全离线运行，可直接打包为企业内部部署版本。"
        )
        hero_points.setWordWrap(True)
        hero_points.setStyleSheet("font-size: 14px; color: rgba(226, 232, 255, 0.92);")
        hero_layout.addWidget(hero_points)

        demo_hint = QLabel(f"示例账号：{DEMO_USERNAME} / {DEMO_PASSWORD}")
        demo_hint.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.95);"
            "background: rgba(15,118,110,0.28); padding: 10px 14px; border-radius: 16px;"
        )
        hero_layout.addWidget(demo_hint)
        hero_layout.addStretch(1)

        layout.addWidget(hero_card, 1)

        form_card = ElevatedCard(corner_radius=28)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(32, 32, 32, 32)
        form_layout.setSpacing(18)

        self.form_title = QLabel()
        self.form_title.setStyleSheet("font-size: 22px; font-weight: 700; color: #0f172a;")
        self.form_subtitle = QLabel()
        self.form_subtitle.setWordWrap(True)
        self.form_subtitle.setStyleSheet("font-size: 13px; color: #475569;")

        form_layout.addWidget(self.form_title)
        form_layout.addWidget(self.form_subtitle)

        self.form_stack = QStackedWidget()
        form_layout.addWidget(self.form_stack)

        layout.addWidget(form_card, 1)

        self._build_login_form()
        self._build_register_form()

    def _build_login_form(self) -> None:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("用户名")
        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("密码")
        self.login_password.setEchoMode(QLineEdit.Password)

        self.login_feedback = QLabel()
        self.login_feedback.setWordWrap(True)
        self.login_feedback.setStyleSheet("color: #dc2626; font-size: 13px;")

        self.login_button = QPushButton("立即登录")
        self.login_button.setObjectName("PrimaryButton")
        self.login_button.clicked.connect(self._attempt_login)

        switch_button = QPushButton("还没有账号？立刻注册")
        switch_button.setObjectName("LinkButton")
        switch_button.clicked.connect(self._show_register)

        layout.addWidget(self.login_username)
        layout.addWidget(self.login_password)
        layout.addWidget(self.login_feedback)
        layout.addWidget(self.login_button)
        layout.addWidget(switch_button, 0, Qt.AlignLeft)
        layout.addStretch(1)

        self.form_stack.addWidget(widget)

    def _build_register_form(self) -> None:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.register_username = QLineEdit()
        self.register_username.setPlaceholderText("新用户名")
        self.register_password = QLineEdit()
        self.register_password.setPlaceholderText("设置密码 (至少 6 位)")
        self.register_password.setEchoMode(QLineEdit.Password)
        self.register_confirm = QLineEdit()
        self.register_confirm.setPlaceholderText("确认密码")
        self.register_confirm.setEchoMode(QLineEdit.Password)

        self.register_feedback = QLabel()
        self.register_feedback.setWordWrap(True)
        self.register_feedback.setStyleSheet("color: #dc2626; font-size: 13px;")

        self.register_button = QPushButton("创建账号")
        self.register_button.setObjectName("PrimaryButton")
        self.register_button.clicked.connect(self._attempt_register)

        switch_button = QPushButton("返回登录")
        switch_button.setObjectName("LinkButton")
        switch_button.clicked.connect(self._show_login)

        layout.addWidget(self.register_username)
        layout.addWidget(self.register_password)
        layout.addWidget(self.register_confirm)
        layout.addWidget(self.register_feedback)
        layout.addWidget(self.register_button)
        layout.addWidget(switch_button, 0, Qt.AlignLeft)
        layout.addStretch(1)

        self.form_stack.addWidget(widget)

    def _show_login(self) -> None:
        self._showing_register = False
        self.form_stack.setCurrentIndex(0)
        self.form_title.setText("欢迎回来")
        self.form_subtitle.setText("请输入账号密码登录，或使用示例账号快速体验全功能界面。")
        self.login_feedback.setStyleSheet("color: #dc2626; font-size: 13px;")
        self.login_feedback.clear()
        self.register_feedback.clear()

    def _show_register(self) -> None:
        self._showing_register = True
        self.form_stack.setCurrentIndex(1)
        existing_users = self.user_service.list_users()
        first_user_tip = (
            "系统将自动授予第一个注册的用户管理员权限。"
            if not existing_users
            else "注册完成后即可使用知识库与决策链功能。"
        )
        self.form_title.setText("注册新账号")
        self.form_subtitle.setText(first_user_tip)
        self.login_feedback.clear()
        self.register_feedback.setStyleSheet("color: #dc2626; font-size: 13px;")
        self.register_feedback.clear()

    def _attempt_login(self) -> None:
        username = self.login_username.text().strip()
        password = self.login_password.text().strip()
        if not username or not password:
            self.login_feedback.setText("请输入用户名和密码。")
            return
        if self.user_service.authenticate(username, password):
            self.login_feedback.setStyleSheet("color: #059669; font-size: 13px;")
            self.login_feedback.setText("登录成功，正在进入系统...")
            QTimer.singleShot(180, lambda: self.authenticated.emit(username))
        else:
            self.login_feedback.setStyleSheet("color: #dc2626; font-size: 13px;")
            self.login_feedback.setText("账号或密码错误，请重试。")

    def _attempt_register(self) -> None:
        username = self.register_username.text().strip()
        password = self.register_password.text().strip()
        confirm = self.register_confirm.text().strip()
        if not username or not password or not confirm:
            self.register_feedback.setText("请完整填写所有字段。")
            return
        if len(password) < 6:
            self.register_feedback.setText("密码长度至少为 6 位。")
            return
        if password != confirm:
            self.register_feedback.setText("两次输入的密码不一致。")
            return
        is_first_user = not self.user_service.list_users()
        try:
            self.user_service.register_user(username, password, is_admin=is_first_user)
        except ValueError as exc:
            self.register_feedback.setText(str(exc))
            return
        self.register_feedback.setStyleSheet("color: #059669; font-size: 13px;")
        self.register_feedback.setText("注册成功，请使用新账号登录。")
        self.login_username.setText(username)
        self.login_password.setText(password)
        QTimer.singleShot(200, self._show_login)

    def reset(self) -> None:
        self.login_username.clear()
        self.login_password.clear()
        self.register_username.clear()
        self.register_password.clear()
        self.register_confirm.clear()
        self.login_feedback.clear()
        self.register_feedback.clear()
        self._show_login()

class ChatBubble(ElevatedCard):
    def __init__(self, role: str, text: str, *, parent: Optional[QWidget] = None):
        if role == "user":
            top_color = QColor(239, 246, 255, 255)
            bottom_color = QColor(219, 234, 254, 245)
        else:
            top_color = QColor(222, 247, 236, 255)
            bottom_color = QColor(191, 233, 216, 240)
        super().__init__(
            parent=parent,
            corner_radius=18,
            top_color=top_color,
            bottom_color=bottom_color,
            shadow_blur=22,
        )
        self.role = role
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)

        title = QLabel("用户" if role == "user" else "智能助手")
        title.setStyleSheet(
            "font-weight: 600; font-size: 14px; color: #1d4ed8;"
            if role == "user"
            else "font-weight: 600; font-size: 14px; color: #047857;"
        )
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("font-size: 15px; color: #0f172a; line-height: 1.56em;")

        layout.addWidget(title)
        layout.addWidget(body)


class ChatPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 10px; background: rgba(148, 163, 184, 40); border-radius: 5px; }"
            "QScrollBar::handle:vertical { background: rgba(71, 85, 105, 120); border-radius: 5px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self.container = QWidget()
        self.messages_layout = QVBoxLayout(self.container)
        self.messages_layout.setContentsMargins(24, 24, 24, 24)
        self.messages_layout.setSpacing(18)
        self.messages_layout.addStretch(1)
        self.scroll_area.setWidget(self.container)

        layout.addWidget(self.scroll_area)

    def add_message(self, role: str, text: str) -> None:
        bubble = ChatBubble(role, text)
        bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        index = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(index, bubble)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())


class KnowledgeSidebar(ElevatedCard):
    corpus_selected = Signal(int)
    corpus_delete_requested = Signal(int)

    def __init__(self, *, parent: Optional[QWidget] = None):
        super().__init__(parent=parent, corner_radius=26)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(16)

        header = QLabel("知识库面板")
        header.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        layout.addWidget(header)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("搜索或筛选知识库...")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._apply_filter)
        self.search_field.setStyleSheet(
            "QLineEdit { padding: 10px 14px; border-radius: 16px; border: 1px solid rgba(148, 163, 184, 120);"
            "background: rgba(255, 255, 255, 0.85); font-size: 14px; }"
            "QLineEdit:focus { border: 1px solid #2563eb; background: rgba(255, 255, 255, 0.95); }"
        )
        layout.addWidget(self.search_field)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        self.list_widget.setStyleSheet(
            "QListWidget { border: none; background: transparent; font-size: 14px; }"
            "QListWidget::item { padding: 12px 14px; border-radius: 14px; margin: 2px 0; }"
            "QListWidget::item:selected { background: rgba(37, 99, 235, 0.16); color: #1d4ed8; font-weight: 600; }"
            "QListWidget::item:hover { background: rgba(14, 165, 233, 0.12); }"
        )
        self.list_widget.currentItemChanged.connect(self._emit_selection)
        layout.addWidget(self.list_widget, 1)

        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(12)
        self.add_button = QPushButton("挂载知识库")
        self.refresh_button = QPushButton("刷新")
        self.add_button.setObjectName("AccentButton")
        self.refresh_button.setObjectName("GhostButton")
        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.refresh_button)
        layout.addLayout(buttons_layout)

        self.delete_button = QPushButton("删除知识库")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._request_delete)
        layout.addWidget(self.delete_button)

        self._corpora: list[KnowledgeCorpus] = []

    def populate(self, corpora: list[KnowledgeCorpus]) -> None:
        self._corpora = corpora
        self._apply_filter(self.search_field.text())

    def _emit_selection(self, current: QListWidgetItem | None) -> None:
        if current is None:
            self.delete_button.setEnabled(False)
            return
        corpus_id = current.data(Qt.UserRole)
        self.delete_button.setEnabled(corpus_id is not None)
        if corpus_id is not None:
            self.corpus_selected.emit(int(corpus_id))

    def _apply_filter(self, text: str) -> None:
        selected_id: int | None = None
        current_item = self.list_widget.currentItem()
        if current_item is not None:
            data = current_item.data(Qt.UserRole)
            if data is not None:
                selected_id = int(data)

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        query = text.strip().lower()
        for corpus in self._corpora:
            if query and query not in corpus.name.lower():
                continue
            item = QListWidgetItem(corpus.name)
            item.setData(Qt.UserRole, corpus.id)
            self.list_widget.addItem(item)
            if selected_id == corpus.id:
                self.list_widget.setCurrentItem(item)
        self.list_widget.blockSignals(False)
        if self.list_widget.count() and self.list_widget.currentRow() == -1:
            self.list_widget.setCurrentRow(0)
        self.delete_button.setEnabled(self.list_widget.currentItem() is not None)

    def set_selected_corpus(self, corpus_id: Optional[int]) -> None:
        if corpus_id is None:
            self.list_widget.setCurrentRow(-1)
            self.delete_button.setEnabled(False)
            return
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.UserRole) == corpus_id:
                self.list_widget.setCurrentRow(row)
                self.delete_button.setEnabled(True)
                return
        self.delete_button.setEnabled(False)

    def _request_delete(self) -> None:
        current = self.list_widget.currentItem()
        if current is None:
            return
        corpus_id = current.data(Qt.UserRole)
        if corpus_id is not None:
            self.corpus_delete_requested.emit(int(corpus_id))

    def pulse_actions(self) -> None:
        target = self.add_button
        effect = QGraphicsOpacityEffect(target)
        target.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", target)
        animation.setDuration(620)
        animation.setStartValue(0.0)
        animation.setKeyValueAt(0.4, 1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.InOutCubic)

        def _cleanup() -> None:
            target.setGraphicsEffect(None)

        animation.finished.connect(_cleanup)
        animation.start(QPropertyAnimation.DeleteWhenStopped)
        setattr(target, "_pulse_animation", animation)


class InputPanel(ElevatedCard):
    submitted = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent=parent, corner_radius=24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("请输入需要咨询的工艺问题，系统将结合知识库给出答案... (Shift+Enter 换行)")
        self.input_field.setFixedHeight(140)
        self.input_field.setStyleSheet(
            "QTextEdit { border-radius: 18px; border: 1px solid rgba(148, 163, 184, 110);"
            "background: rgba(255, 255, 255, 0.92); font-size: 15px; color: #0f172a; padding: 14px; }"
            "QTextEdit:focus { border: 1px solid #2563eb; }"
        )

        self.submit_button = QPushButton("发送")
        self.submit_button.setObjectName("PrimaryButton")
        self.submit_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowForward))
        self.submit_button.setIconSize(self.submit_button.iconSize() * 1.2)
        self.submit_button.setDefault(True)
        self.submit_button.setCursor(Qt.PointingHandCursor)
        self.submit_button.setFixedWidth(156)
        self.submit_button.clicked.connect(self._handle_submit)

        layout.addWidget(self.input_field, 1)
        layout.addWidget(self.submit_button, 0, Qt.AlignBottom)

    def _handle_submit(self) -> None:
        text = self.input_field.toPlainText().strip()
        if not text:
            return
        self.submitted.emit(text)
        self.input_field.clear()


class DecisionHistoryDialog(QDialog):
    """Dialog to search and review decision histories."""

    def __init__(self, history_service: HistoryService, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.history_service = history_service
        self.setWindowTitle("决策链检索")
        self.resize(860, 540)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        container = ElevatedCard(corner_radius=26)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(28, 28, 28, 28)
        container_layout.setSpacing(18)

        title = QLabel("决策链知识档案")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #0f172a;")
        subtitle = QLabel("快速检索历史决策链，查看步骤、结论与团队评论。")
        subtitle.setStyleSheet("font-size: 13px; color: #475569;")
        container_layout.addWidget(title)
        container_layout.addWidget(subtitle)

        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(12)
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("输入关键字，例如：热处理 停机 分析")
        self.search_field.returnPressed.connect(self._perform_search)
        search_button = QPushButton("搜索")
        search_button.setObjectName("AccentButton")
        search_button.clicked.connect(self._perform_search)
        search_layout.addWidget(self.search_field, 1)
        search_layout.addWidget(search_button)
        container_layout.addLayout(search_layout)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        self.results_list = QListWidget()
        self.results_list.setMinimumWidth(260)
        self.results_list.setStyleSheet(
            "QListWidget { border: none; background: rgba(255,255,255,0.72); border-radius: 18px; padding: 8px; }"
            "QListWidget::item { margin: 4px; padding: 10px 12px; border-radius: 14px; }"
            "QListWidget::item:selected { background: rgba(59,130,246,0.18); color: #1d4ed8; font-weight: 600; }"
        )
        self.results_list.itemSelectionChanged.connect(self._display_details)

        self.details_view = QTextEdit()
        self.details_view.setReadOnly(True)
        self.details_view.setStyleSheet(
            "QTextEdit { border: none; background: rgba(255,255,255,0.85); border-radius: 22px;"
            "padding: 18px; font-size: 14px; color: #0f172a; line-height: 1.6em; }"
        )

        content_layout.addWidget(self.results_list, 0)
        content_layout.addWidget(self.details_view, 1)

        container_layout.addLayout(content_layout, 1)

        self.empty_label = QLabel("输入关键字并点击搜索，即可查看匹配的历史决策。")
        self.empty_label.setStyleSheet("font-size: 13px; color: #64748b;")
        container_layout.addWidget(self.empty_label)

        layout.addWidget(container)

    def _perform_search(self) -> None:
        query = self.search_field.text().strip()
        self.results_list.clear()
        self.details_view.clear()
        if not query:
            self.empty_label.setText("请输入关键字后再搜索。")
            return
        histories = self.history_service.search_histories(query, limit=25)
        if not histories:
            self.empty_label.setText("未找到匹配的决策记录，尝试调整关键词。")
            return
        self.empty_label.setText("共找到 %d 条匹配记录。" % len(histories))
        for history in histories:
            item = QListWidgetItem(f"{history.title}\n标签：{', '.join(history.tags) if history.tags else '无'}")
            item.setData(Qt.UserRole, history.id)
            self.results_list.addItem(item)
        if self.results_list.count():
            self.results_list.setCurrentRow(0)

    def _display_details(self) -> None:
        current = self.results_list.currentItem()
        if current is None:
            self.details_view.clear()
            return
        history_id = current.data(Qt.UserRole)
        if history_id is None:
            self.details_view.clear()
            return
        history = self.history_service.get_history(int(history_id))
        if history is None:
            self.details_view.clear()
            return
        comments = self.history_service.list_comments(history.id)
        comment_lines = [
            f"- {comment.author}({comment.rating or '未评分'}★)：{comment.comment}" for comment in comments
        ]
        comment_block = "\n".join(comment_lines) if comment_lines else "暂无评论"
        content = (
            f"标题：{history.title}\n"
            f"创建时间：{history.created_at}\n"
            f"标签：{', '.join(history.tags) if history.tags else '无'}\n\n"
            f"【场景描述】\n{history.context}\n\n"
            f"【处理步骤】\n{history.steps}\n\n"
            f"【最终结论】\n{history.outcome or '未填写'}\n\n"
            f"【团队评论】\n{comment_block}"
        )
        self.details_view.setPlainText(content)

class HeaderBar(ElevatedCard):
    history_search_requested = Signal()
    logout_requested = Signal()

    def __init__(self, title: str, subtitle: str, *, parent: Optional[QWidget] = None):
        super().__init__(
            parent=parent,
            corner_radius=26,
            top_color=QColor(59, 130, 246, 220),
            bottom_color=QColor(124, 58, 237, 200),
            shadow_blur=38,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(22)

        icon_label = QLabel()
        pixmap = self.style().standardIcon(QStyle.SP_FileDialogListView).pixmap(64, 64)
        icon_label.setPixmap(pixmap)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("HeaderTitle")
        self.title_label.setStyleSheet(
            "#HeaderTitle { font-size: 30px; font-weight: 800; color: white; letter-spacing: 1px; }"
        )

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(
            "font-size: 14px; color: rgba(255, 255, 255, 0.92); font-weight: 500;"
        )

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)

        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(12)

        self.history_button = QPushButton("决策链检索")
        self.history_button.setObjectName("GhostButton")
        self.history_button.setCursor(Qt.PointingHandCursor)
        self.history_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.history_button.clicked.connect(self.history_search_requested.emit)
        actions_layout.addWidget(self.history_button, 0, Qt.AlignRight)

        self.user_button = QToolButton()
        self.user_button.setObjectName("UserButton")
        self.user_button.setPopupMode(QToolButton.InstantPopup)
        self.user_button.setText("未登录")
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_menu = QMenu(self)
        logout_action = self.user_menu.addAction("退出登录")
        logout_action.triggered.connect(self.logout_requested.emit)
        self.user_button.setMenu(self.user_menu)
        actions_layout.addWidget(self.user_button, 0, Qt.AlignRight)

        layout.addLayout(actions_layout, 0)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_user(self, username: Optional[str]) -> None:
        if username:
            self.user_button.setText(f"{username}")
            self.user_button.setEnabled(True)
        else:
            self.user_button.setText("未登录")
            self.user_button.setEnabled(False)


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowSystemMenuHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("GlassMainWindow")
        self.setWindowTitle("离线知识库助手")
        self.resize(1320, 840)
        self.setMinimumSize(1120, 720)
        self.setFont(QFont("Microsoft YaHei UI", 10))

        self.db_path = db_path
        self.user_service = UserService(db_path)
        self.history_service = HistoryService(db_path)
        self.knowledge_service = KnowledgeService(db_path)
        self.corpus_service = CorpusService(db_path)
        self.thread_pool = QThreadPool.globalInstance()
        self.current_user: Optional[str] = None
        self.current_corpus_id: Optional[int] = None

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(12)

        self.title_bar = TitleBar(self)
        shell_layout.addWidget(self.title_bar)

        frame = ElevatedCard(corner_radius=34, shadow_blur=48)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.gradient = GradientCanvas()
        gradient_layout = QVBoxLayout(self.gradient)
        gradient_layout.setContentsMargins(28, 28, 28, 28)
        gradient_layout.setSpacing(24)

        self.stack = AnimatedStack()
        gradient_layout.addWidget(self.stack, 1)

        frame_layout.addWidget(self.gradient)
        shell_layout.addWidget(frame, 1)
        self.setCentralWidget(shell)

        self.auth_view = AuthView(self.user_service)
        self.auth_view.authenticated.connect(self._on_authenticated)
        self.app_view = self._build_app_view()
        self.stack.addWidget(self.auth_view)
        self.stack.addWidget(self.app_view)
        self.stack.setCurrentWidget(self.auth_view)

        self._apply_global_styles()
        self.refresh_corpora()

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        if event.type() == QEvent.WindowStateChange:
            self.title_bar.update_max_restore_icon()
        super().changeEvent(event)

    def _build_app_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        self.menu_bar = NeonMenuBar()
        layout.addWidget(self.menu_bar)

        self.header = HeaderBar("离线知识库助手", "请选择或挂载一个知识库以开始提问。")
        self.header.history_search_requested.connect(self._open_history_dialog)
        self.header.logout_requested.connect(self._logout)
        layout.addWidget(self.header)

        self.menu_bar.selection_changed.connect(self._handle_menu_change)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(26)

        self.sidebar = KnowledgeSidebar()
        self.sidebar.setFixedWidth(320)
        self.sidebar.add_button.clicked.connect(self._handle_add_corpus)
        self.sidebar.refresh_button.clicked.connect(self.refresh_corpora)
        self.sidebar.corpus_selected.connect(self._select_corpus)
        self.sidebar.corpus_delete_requested.connect(self._handle_delete_corpus)
        content_layout.addWidget(self.sidebar, 0, Qt.AlignTop)

        chat_card = ElevatedCard(corner_radius=28)
        chat_layout = QVBoxLayout(chat_card)
        chat_layout.setContentsMargins(28, 28, 28, 28)
        chat_layout.setSpacing(22)

        headline_layout = QHBoxLayout()
        headline_layout.setContentsMargins(0, 0, 0, 0)
        headline_layout.setSpacing(12)
        icon_label = QLabel()
        icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation).pixmap(28, 28)
        icon_label.setPixmap(icon)
        icon_label.setStyleSheet("background: transparent;")
        title_label = QLabel("智能对话")
        title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #0f172a;")
        headline_layout.addWidget(icon_label, 0, Qt.AlignVCenter)
        headline_layout.addWidget(title_label, 0, Qt.AlignVCenter)
        headline_layout.addStretch(1)
        chat_layout.addLayout(headline_layout)

        self.chat_panel = ChatPanel()
        chat_layout.addWidget(self.chat_panel, 1)

        self.status_chip = QLabel("请选择或挂载一个知识库以开始提问。")
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setWordWrap(True)
        self.status_chip.setStyleSheet(
            "QLabel#StatusChip { background: rgba(37, 99, 235, 0.12); border-radius: 18px;"
            "padding: 12px 16px; color: #1d4ed8; font-size: 14px; font-weight: 600; }"
        )
        chat_layout.addWidget(self.status_chip)

        self._status_effect = QGraphicsOpacityEffect(self.status_chip)
        self.status_chip.setGraphicsEffect(self._status_effect)
        self._status_effect.setOpacity(1.0)
        self._status_anim = QPropertyAnimation(self._status_effect, b"opacity", self)
        self._status_anim.setDuration(520)
        self._status_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.input_panel = InputPanel()
        self.input_panel.submitted.connect(self._handle_question)
        chat_layout.addWidget(self.input_panel)

        content_layout.addWidget(chat_card, 1)
        layout.addLayout(content_layout, 1)

        return container

    def _apply_global_styles(self) -> None:
        self.setStyleSheet(
            "QMainWindow#GlassMainWindow { background: transparent; }"
            "QPushButton { font-size: 14px; font-weight: 600; padding: 10px 18px;"
            "border-radius: 16px; border: none; color: #0f172a; }"
            "QPushButton#NavigationPill {"
            " background: rgba(255, 255, 255, 0.22); color: white; border: 1px solid rgba(255,255,255,0.26);"
            " padding: 14px 22px; border-radius: 22px; font-size: 15px; letter-spacing: 0.5px; }"
            "QPushButton#NavigationPill:checked {"
            " background: rgba(255, 255, 255, 0.42); color: #0f172a;"
            " border: 1px solid rgba(30, 64, 175, 0.55); }"
            "QPushButton#NavigationPill:hover { background: rgba(255, 255, 255, 0.55); color: #1e3a8a; }"
            "QPushButton#AccentButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #2563eb, stop:1 #38bdf8); color: white; }"
            "QPushButton#AccentButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #1d4ed8, stop:1 #0ea5e9); }"
            "QPushButton#GhostButton { background: rgba(255, 255, 255, 0.7);"
            " color: #1f2937; border: 1px solid rgba(148, 163, 184, 120); }"
            "QPushButton#GhostButton:hover { background: rgba(255, 255, 255, 0.9); }"
            "QPushButton#PrimaryButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #2563eb, stop:1 #7c3aed); color: white; }"
            "QPushButton#PrimaryButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #1d4ed8, stop:1 #6d28d9); }"
            "QPushButton#DangerButton { background: rgba(254, 226, 226, 0.88); color: #b91c1c;"
            " border: 1px solid rgba(239, 68, 68, 0.4); }"
            "QPushButton#DangerButton:hover { background: rgba(254, 202, 202, 0.96); }"
            "QPushButton#LinkButton { color: #2563eb; background: transparent; padding: 6px; }"
            "QPushButton#LinkButton:hover { text-decoration: underline; }"
            "QToolButton#UserButton { padding: 8px 14px; border-radius: 16px;"
            " background: rgba(236, 254, 255, 0.7); color: #0f172a; font-weight: 600; border: 1px solid rgba(79, 70, 229, 0.2); }"
            "QToolButton#UserButton::menu-indicator { image: none; }"
            "QStatusBar { background: transparent; border: none; color: #1f2937; }"
        )

    def refresh_corpora(self) -> None:
        corpora = self.corpus_service.list_corpora()
        self.sidebar.populate(corpora)
        corpus_ids = {corpus.id for corpus in corpora}
        if corpora and (self.current_corpus_id is None or self.current_corpus_id not in corpus_ids):
            self.current_corpus_id = corpora[0].id
        elif not corpora:
            self.current_corpus_id = None
            self.chat_panel.clear_messages()
        self.sidebar.set_selected_corpus(self.current_corpus_id)
        self._update_status()

    def _handle_menu_change(self, key: str) -> None:
        if key == "chat":
            self.header.set_title("离线知识库助手")
            self.header.set_subtitle(self.status_chip.text())
            return
        if key == "dashboard":
            self.header.set_title("系统概览")
            self.header.set_subtitle("一览知识库覆盖率、最近导入与活跃决策链。")
            self.statusBar().showMessage("仪表盘即将上线，当前版本请通过知识库与决策链快速检索。", 5000)
            QTimer.singleShot(1600, lambda: self.menu_bar.set_active("chat"))
            return
        elif key == "history":
            self._open_history_dialog()
        elif key == "corpus":
            self.sidebar.pulse_actions()
            self.statusBar().showMessage("在左侧面板中挂载、刷新或删除知识库文件夹。", 5000)
            QTimer.singleShot(1000, lambda: self.menu_bar.set_active("chat"))
            return
        elif key == "settings":
            QMessageBox.information(
                self,
                "系统设置",
                "当前版本已启用离线运行、账号管理与知识库维护。更多高级配置将在后续版本提供。",
            )
            QTimer.singleShot(1000, lambda: self.menu_bar.set_active("chat"))
            return
        self.menu_bar.set_active("chat")

    def _handle_add_corpus(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择知识库文件夹")
        if not directory:
            return
        name, ok = QInputDialog.getText(self, "知识库名称", "请输入知识库名称：")
        if not ok or not name.strip():
            return
        name = name.strip()
        corpus = self.corpus_service.ensure_corpus(name, base_path=Path(directory))
        self.statusBar().showMessage("正在加载知识库内容...", 5000)

        worker = Worker(self.corpus_service.ingest_directory, corpus.id, Path(directory))
        worker.signals.result.connect(self._on_ingest_complete)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self.statusBar().clearMessage)
        self.thread_pool.start(worker)

    def _handle_delete_corpus(self, corpus_id: int) -> None:
        corpus = self.corpus_service.get_corpus(corpus_id)
        if not corpus:
            return
        confirm = QMessageBox.question(
            self,
            "删除知识库",
            f"确定要删除知识库“{corpus.name}”吗？相关知识条目也将一并移除。",
        )
        if confirm != QMessageBox.Yes:
            return
        success = self.corpus_service.delete_corpus(corpus_id)
        if success:
            if self.current_corpus_id == corpus_id:
                self.current_corpus_id = None
                self.chat_panel.clear_messages()
            self.statusBar().showMessage(f"已删除知识库 {corpus.name}", 4000)
            self.refresh_corpora()
        else:
            QMessageBox.warning(self, "删除失败", "知识库删除失败，请稍后再试。")

    def _select_corpus(self, corpus_id: int) -> None:
        self.current_corpus_id = corpus_id
        self.chat_panel.clear_messages()
        self._update_status()

    def _on_ingest_complete(self, report: IngestReport) -> None:
        message_lines = [
            f"成功导入 {report.files_processed} 个文件，生成 {report.chunks_created} 条知识片段。"
        ]
        if report.skipped:
            message_lines.append(
                "未处理的文件: " + ", ".join(report.skipped[:6]) + (" 等" if len(report.skipped) > 6 else "")
            )
        QMessageBox.information(self, "知识库更新完成", "\n".join(message_lines))
        self.refresh_corpora()

    def _handle_question(self, question: str) -> None:
        if self.current_user is None:
            QMessageBox.information(self, "请先登录", "请登录后再进行提问。")
            return
        if self.current_corpus_id is None:
            QMessageBox.warning(self, "请选择知识库", "请先挂载或选择一个知识库，再进行提问。")
            return
        self.chat_panel.add_message("user", question)
        self.statusBar().showMessage("正在检索最佳答案...", 3000)
        worker = Worker(self._resolve_answer, question, self.current_corpus_id)
        worker.signals.result.connect(self._display_answer)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(self.statusBar().clearMessage)
        self.thread_pool.start(worker)

    def _resolve_answer(self, question: str, corpus_id: int) -> str:
        matches = self.knowledge_service.answer(question, limit=5, corpus_id=corpus_id)
        if not matches:
            return "知识库暂未匹配到答案，请尝试补充知识或调整提问方式。"
        chunks = []
        for entry, score in matches:
            snippet = entry.answer.strip()
            if len(snippet) > 480:
                snippet = snippet[:480] + "..."
            chunks.append(
                f"《{entry.title}》\n匹配度: {score:.2f}\n{snippet}"
            )
        return "\n\n".join(chunks)

    def _display_answer(self, answer: str) -> None:
        self.chat_panel.add_message("assistant", answer)

    def _update_status(self) -> None:
        if self.current_corpus_id is None:
            message = "请选择或挂载一个知识库以开始提问。"
        else:
            corpus = self.corpus_service.get_corpus(self.current_corpus_id)
            if corpus:
                extra = f"（路径：{corpus.base_path}）" if corpus.base_path else ""
                message = f"当前知识库：{corpus.name}{extra}"
            else:
                message = "当前知识库信息不可用。"
        if self.current_user:
            message = f"用户 {self.current_user} · {message}"
        self.status_chip.setText(message)
        self.header.set_subtitle(message)
        self.header.set_user(self.current_user)
        self._pulse_status_chip()

    def _pulse_status_chip(self) -> None:
        if self._status_anim.state() == QPropertyAnimation.Running:
            self._status_anim.stop()
        self._status_effect.setOpacity(0.35)
        self._status_anim.setStartValue(0.35)
        self._status_anim.setEndValue(1.0)
        self._status_anim.start()

    def _on_worker_error(self, message: str) -> None:
        QMessageBox.critical(self, "操作失败", message)

    def _on_authenticated(self, username: str) -> None:
        self.current_user = username
        self.header.set_user(username)
        self.stack.setCurrentWidgetAnimated(self.app_view)
        self.menu_bar.set_active("chat")
        self.chat_panel.clear_messages()
        self.statusBar().showMessage(f"欢迎回来，{username}", 3000)
        self._update_status()
        self.input_panel.input_field.setFocus()

    def _logout(self) -> None:
        if QMessageBox.question(self, "退出登录", "确认退出当前账号吗？") != QMessageBox.Yes:
            return
        self.current_user = None
        self.header.set_user(None)
        self.chat_panel.clear_messages()
        self.stack.setCurrentWidgetAnimated(self.auth_view)
        self.auth_view.reset()
        self._update_status()
        self.menu_bar.set_active("chat")

    def _open_history_dialog(self) -> None:
        dialog = DecisionHistoryDialog(self.history_service, parent=self)
        dialog.exec()


def run_gui_app(db_path: Optional[Path] = None) -> None:
    db_path = ensure_app_database(db_path or DEFAULT_DB)
    ensure_seed_data(db_path)
    app = QApplication.instance() or QApplication([])
    app.setApplicationDisplayName("离线知识库助手")
    app.setStyle("Fusion")
    base_palette = app.palette()
    base_palette.setColor(QPalette.Window, QColor("#e2e8f0"))
    base_palette.setColor(QPalette.Base, QColor(255, 255, 255, 230))
    base_palette.setColor(QPalette.AlternateBase, QColor(248, 250, 252))
    base_palette.setColor(QPalette.Text, QColor("#0f172a"))
    base_palette.setColor(QPalette.Button, QColor(255, 255, 255, 230))
    base_palette.setColor(QPalette.ButtonText, QColor("#0f172a"))
    app.setPalette(base_palette)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow(db_path)
    window.show()
    app.exec()
