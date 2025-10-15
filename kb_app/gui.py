"""Desktop user interface for the offline knowledge base system."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .corpus_service import CorpusService, IngestReport, KnowledgeCorpus
from .knowledge_service import KnowledgeService

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
    """Background widget providing a subtle multi-color gradient."""

    def paintEvent(self, event):  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(226, 232, 255))
        gradient.setColorAt(0.45, QColor(240, 249, 255))
        gradient.setColorAt(1.0, QColor(236, 253, 245))
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
        shadow.setOffset(0, 12)
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
        border_color = QColor(255, 255, 255, 120)
        painter.setPen(border_color)
        painter.drawPath(path)


class HeaderBar(ElevatedCard):
    """Prominent header with icon, title and subtitle."""

    def __init__(self, title: str, subtitle: str, *, parent: Optional[QWidget] = None):
        super().__init__(
            parent=parent,
            corner_radius=26,
            top_color=QColor(59, 130, 246, 220),
            bottom_color=QColor(59, 130, 246, 180),
            shadow_blur=38,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(22)

        icon_label = QLabel()
        pixmap = self.style().standardIcon(QStyle.SP_FileDialogInfoView).pixmap(64, 64)
        icon_label.setPixmap(pixmap)
        icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("HeaderTitle")
        self.title_label.setStyleSheet(
            "#HeaderTitle { font-size: 28px; font-weight: 700; color: white; letter-spacing: 1px; }"
        )

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setStyleSheet(
            "font-size: 14px; color: rgba(255, 255, 255, 0.92); font-weight: 500;"
        )

        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)


class ChatBubble(ElevatedCard):
    def __init__(self, role: str, text: str, *, parent: Optional[QWidget] = None):
        if role == "user":
            top_color = QColor(239, 246, 255, 255)
            bottom_color = QColor(219, 234, 254, 255)
        else:
            top_color = QColor(222, 247, 236, 255)
            bottom_color = QColor(191, 233, 216, 245)
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
        body.setStyleSheet("font-size: 15px; color: #0f172a; line-height: 1.5em;")

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

        self._corpora: list[KnowledgeCorpus] = []

    def populate(self, corpora: list[KnowledgeCorpus]) -> None:
        self._corpora = corpora
        self._apply_filter(self.search_field.text())

    def _emit_selection(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        corpus_id = current.data(Qt.UserRole)
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

    def set_selected_corpus(self, corpus_id: Optional[int]) -> None:
        if corpus_id is None:
            self.list_widget.setCurrentRow(-1)
            return
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.UserRole) == corpus_id:
                self.list_widget.setCurrentRow(row)
                return


class InputPanel(ElevatedCard):
    submitted = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent=parent, corner_radius=24)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("请输入需要咨询的工艺问题，系统将结合知识库给出答案...")
        self.input_field.setFixedHeight(120)
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


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path):
        super().__init__()
        self.setWindowTitle("离线知识库助手")
        self.resize(1320, 820)
        self.setMinimumSize(1120, 700)
        self.setFont(QFont("Microsoft YaHei UI", 10))

        self.db_path = db_path
        self.knowledge_service = KnowledgeService(db_path)
        self.corpus_service = CorpusService(db_path)
        self.thread_pool = QThreadPool.globalInstance()
        self.current_corpus_id: int | None = None

        central = GradientCanvas()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(36, 32, 36, 32)
        central_layout.setSpacing(26)

        self.header = HeaderBar("离线知识库助手", "请选择或挂载一个知识库以开始提问。")
        central_layout.addWidget(self.header)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(26)

        self.sidebar = KnowledgeSidebar()
        self.sidebar.setFixedWidth(320)
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

        self.input_panel = InputPanel()
        chat_layout.addWidget(self.input_panel)

        content_layout.addWidget(chat_card, 1)
        central_layout.addLayout(content_layout, 1)

        self.setCentralWidget(central)
        self._apply_global_styles()

        self.sidebar.add_button.clicked.connect(self._handle_add_corpus)
        self.sidebar.refresh_button.clicked.connect(self.refresh_corpora)
        self.sidebar.corpus_selected.connect(self._select_corpus)
        self.input_panel.submitted.connect(self._handle_question)

        self.refresh_corpora()

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------
    def _apply_global_styles(self) -> None:
        self.setStyleSheet(
            "QMainWindow { background-color: #e2e8f0; }"
            "QStatusBar { background: transparent; border: none; color: #1f2937; }"
            "QPushButton { font-size: 14px; font-weight: 600; padding: 10px 18px;"
            "border-radius: 16px; border: none; color: #0f172a; }"
            "QPushButton#AccentButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #2563eb, stop:1 #38bdf8); color: white; }"
            "QPushButton#AccentButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #1d4ed8, stop:1 #0ea5e9); }"
            "QPushButton#GhostButton { background: rgba(255, 255, 255, 0.6);"
            " color: #1f2937; border: 1px solid rgba(148, 163, 184, 120); }"
            "QPushButton#GhostButton:hover { background: rgba(255, 255, 255, 0.85); }"
            "QPushButton#PrimaryButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #2563eb, stop:1 #7c3aed); color: white; }"
            "QPushButton#PrimaryButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #1d4ed8, stop:1 #6d28d9); }"
            "QPushButton:pressed { transform: scale(0.98); }"
        )

    # ------------------------------------------------------------------
    # Corpus operations
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Chat operations
    # ------------------------------------------------------------------
    def _handle_question(self, question: str) -> None:
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

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
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
        self.status_chip.setText(message)
        self.header.set_subtitle(message)

    def _on_worker_error(self, message: str) -> None:
        QMessageBox.critical(self, "操作失败", message)


def run_gui_app(db_path: Optional[Path] = None) -> None:
    db_path = ensure_app_database(db_path or DEFAULT_DB)
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
