"""Desktop user interface for the offline knowledge base system."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
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


class ChatBubble(QWidget):
    def __init__(self, role: str, text: str, *, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.role = role
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        title = QLabel("用户" if role == "user" else "智能助手")
        title.setStyleSheet("font-weight: bold; color: #1d4ed8;" if role == "user" else "font-weight: bold; color: #047857;")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(title)
        layout.addWidget(body)

        palette = self.palette()
        if role == "user":
            palette.setColor(QPalette.Window, QColor("#eef2ff"))
        else:
            palette.setColor(QPalette.Window, QColor("#ecfdf5"))
        self.setAutoFillBackground(True)
        self.setPalette(palette)


class ChatPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)

        self.container = QWidget()
        self.messages_layout = QVBoxLayout(self.container)
        self.messages_layout.setContentsMargins(24, 24, 24, 24)
        self.messages_layout.setSpacing(12)
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


class KnowledgeSidebar(QWidget):
    corpus_selected = Signal(int)

    def __init__(self, *, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("知识库列表")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._emit_selection)
        layout.addWidget(self.list_widget, 1)

        buttons_layout = QHBoxLayout()
        self.add_button = QPushButton("挂载知识库")
        self.refresh_button = QPushButton("刷新")
        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.refresh_button)
        layout.addLayout(buttons_layout)

    def populate(self, corpora: list[KnowledgeCorpus]) -> None:
        self.list_widget.clear()
        for corpus in corpora:
            item = QListWidgetItem(corpus.name)
            item.setData(Qt.UserRole, corpus.id)
            self.list_widget.addItem(item)
        if corpora and self.list_widget.currentRow() == -1:
            self.list_widget.setCurrentRow(0)

    def _emit_selection(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        corpus_id = current.data(Qt.UserRole)
        if corpus_id is not None:
            self.corpus_selected.emit(int(corpus_id))


class InputPanel(QWidget):
    submitted = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("请输入需要咨询的工艺问题...")
        self.input_field.setFixedHeight(96)

        self.submit_button = QPushButton("发送")
        self.submit_button.setDefault(True)
        self.submit_button.setFixedWidth(120)
        self.submit_button.clicked.connect(self._handle_submit)

        layout.addWidget(self.input_field, 1)
        layout.addWidget(self.submit_button)

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
        self.resize(1180, 720)

        self.db_path = db_path
        self.knowledge_service = KnowledgeService(db_path)
        self.corpus_service = CorpusService(db_path)
        self.thread_pool = QThreadPool.globalInstance()
        self.current_corpus_id: int | None = None

        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)

        self.sidebar = KnowledgeSidebar()
        self.sidebar.setMinimumWidth(260)
        splitter.addWidget(self.sidebar)

        chat_container = QWidget()
        chat_layout = QVBoxLayout(chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        self.chat_panel = ChatPanel()
        chat_layout.addWidget(self.chat_panel, 1)

        self.status_label = QLabel("请选择或挂载一个知识库以开始提问。")
        self.status_label.setMargin(12)
        self.status_label.setAlignment(Qt.AlignLeft)
        chat_layout.addWidget(self.status_label)

        self.input_panel = InputPanel()
        chat_layout.addWidget(self.input_panel)

        splitter.addWidget(chat_container)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        self.sidebar.add_button.clicked.connect(self._handle_add_corpus)
        self.sidebar.refresh_button.clicked.connect(self.refresh_corpora)
        self.sidebar.corpus_selected.connect(self._select_corpus)
        self.input_panel.submitted.connect(self._handle_question)

        self.refresh_corpora()

    # ------------------------------------------------------------------
    # Corpus operations
    # ------------------------------------------------------------------
    def refresh_corpora(self) -> None:
        corpora = self.corpus_service.list_corpora()
        self.sidebar.populate(corpora)
        if corpora and self.current_corpus_id is None:
            self.current_corpus_id = corpora[0].id
        elif not corpora:
            self.current_corpus_id = None
            self.chat_panel.clear_messages()
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
            self.status_label.setText("请选择或挂载一个知识库以开始提问。")
        else:
            corpus = self.corpus_service.get_corpus(self.current_corpus_id)
            if corpus:
                self.status_label.setText(
                    f"当前知识库：{corpus.name}"
                    + (f"（路径：{corpus.base_path}）" if corpus.base_path else "")
                )
            else:
                self.status_label.setText("当前知识库信息不可用。")

    def _on_worker_error(self, message: str) -> None:
        QMessageBox.critical(self, "操作失败", message)


def run_gui_app(db_path: Optional[Path] = None) -> None:
    db_path = ensure_app_database(db_path or DEFAULT_DB)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(db_path)
    window.show()
    app.exec()
