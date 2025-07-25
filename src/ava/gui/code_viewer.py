# src/ava/gui/code_viewer.py
import logging
from pathlib import Path
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QWidget, QSplitter,
                               QTabWidget, QMessageBox, QDockWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QCloseEvent
import qasync

from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager
from src.ava.gui.project_context_manager import ProjectContextManager
from src.ava.gui.file_tree_manager import FileTreeManager
from src.ava.gui.editor_tab_manager import EditorTabManager
from src.ava.gui.find_replace_dialog import FindReplaceDialog
from src.ava.gui.quick_file_finder import QuickFileFinder
from src.ava.gui.status_bar import StatusBar
from src.ava.services.lsp_client_service import LSPClientService
from src.ava.gui.executor_log_panel import ExecutorLogPanel

logger = logging.getLogger(__name__)


class CodeViewerWindow(QMainWindow):
    """
    The main code viewing and interaction window with enhanced IDE features.
    """

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager, lsp_client: LSPClientService):
        """
        Initializes the CodeViewerWindow.
        """
        super().__init__()
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.lsp_client = lsp_client
        self.editor_manager: EditorTabManager = None
        self.file_tree_manager: FileTreeManager = None
        self.executor_log_panel: ExecutorLogPanel = None
        self.executor_dock: QDockWidget = None

        self.find_replace_dialog: FindReplaceDialog = None
        self.quick_file_finder: QuickFileFinder = None

        self.setWindowTitle("Code Viewer")
        self.setGeometry(100, 100, 1400, 900)
        self._init_ui()
        self._create_menus()
        self._setup_shortcuts()
        self._connect_events()

    def _init_ui(self) -> None:
        """
        Initializes the user interface, setting up the main layout and widgets.
        """
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(main_splitter)

        # --- Left Panel: File Tree ---
        file_tree_panel_widget = QWidget()
        file_tree_panel_layout = QVBoxLayout(file_tree_panel_widget)
        file_tree_panel_layout.setContentsMargins(0, 0, 0, 0)

        self.file_tree_manager = FileTreeManager(file_tree_panel_widget, self.project_manager, self.event_bus)
        self.file_tree_manager.set_file_selection_callback(self._on_file_selected)

        file_tree_panel_layout.addWidget(self.file_tree_manager.get_widget())
        main_splitter.addWidget(file_tree_panel_widget)

        # --- Right Panel: Editor Tabs Only ---
        tab_widget = QTabWidget()
        tab_widget.setTabsClosable(True)
        tab_widget.setMovable(True)
        tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self.editor_manager = EditorTabManager(tab_widget, self.event_bus, self.project_manager)
        self.editor_manager.set_lsp_client(self.lsp_client)
        main_splitter.addWidget(tab_widget)

        main_splitter.setSizes([300, 1100])

        # --- NEW: Executor Log Panel as a Dock Widget ---
        self.executor_dock = QDockWidget("Executor Log", self)
        self.executor_dock.setObjectName("ExecutorLogDock")
        self.executor_log_panel = ExecutorLogPanel()
        self.executor_dock.setWidget(self.executor_log_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.executor_dock)

        self.status_bar = StatusBar(self.event_bus)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _create_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_current_file)
        file_menu.addAction(save_action)
        save_all_action = QAction("Save All", self)
        save_all_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_all_action.triggered.connect(self._save_all_files)
        file_menu.addAction(save_all_action)
        file_menu.addSeparator()
        close_tab_action = QAction("Close Tab", self)
        close_tab_action.setShortcut(QKeySequence("Ctrl+W"))
        close_tab_action.triggered.connect(self._close_current_tab)
        file_menu.addAction(close_tab_action)
        edit_menu = menubar.addMenu("Edit")
        find_action = QAction("Find/Replace", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self._show_find_replace)
        edit_menu.addAction(find_action)
        go_menu = menubar.addMenu("Go")
        quick_open_action = QAction("Go to File...", self)
        quick_open_action.setShortcut(QKeySequence("Ctrl+P"))
        quick_open_action.triggered.connect(self._show_quick_file_finder)
        go_menu.addAction(quick_open_action)

        # --- NEW: View Menu for toggling panels ---
        view_menu = menubar.addMenu("View")
        toggle_executor_log_action = self.executor_dock.toggleViewAction()
        toggle_executor_log_action.setText("Executor Log Panel")
        view_menu.addAction(toggle_executor_log_action)

    def _setup_shortcuts(self) -> None:
        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        save_shortcut.activated.connect(self._save_current_file)
        find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        find_shortcut.activated.connect(self._show_find_replace)
        quick_open_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        quick_open_shortcut.activated.connect(self._show_quick_file_finder)

    def _connect_events(self) -> None:
        self.event_bus.subscribe("workflow_finalized", self._on_workflow_finalized)

    def _on_workflow_finalized(self, final_code: dict) -> None:
        if self.file_tree_manager:
            self.file_tree_manager.refresh_tree_from_disk()
        self.display_code(final_code)

    def _save_current_file(self) -> None:
        if self.editor_manager:
            if self.editor_manager.save_current_file():
                self.status_bar.showMessage("File saved", 2000)

    def _save_all_files(self) -> None:
        if self.editor_manager:
            if self.editor_manager.save_all_files():
                self.status_bar.showMessage("All files saved", 2000)

    def _close_current_tab(self) -> None:
        if self.editor_manager:
            current_index = self.editor_manager.tab_widget.currentIndex()
            if current_index >= 0:
                self.editor_manager.close_tab(current_index)

    def _show_find_replace(self) -> None:
        if not self.find_replace_dialog:
            self.find_replace_dialog = FindReplaceDialog(self)
        current_editor = self._get_current_editor()
        if current_editor:
            self.find_replace_dialog.set_editor(current_editor)
            cursor = current_editor.textCursor()
            if cursor.hasSelection():
                self.find_replace_dialog.set_find_text(cursor.selectedText())
        self.find_replace_dialog.show_and_focus()

    def _show_quick_file_finder(self) -> None:
        if not self.project_manager.active_project_path:
            self.status_bar.showMessage("No project loaded to search.", 2000)
            return
        if not self.quick_file_finder:
            self.quick_file_finder = QuickFileFinder(self)
            self.quick_file_finder.set_file_open_callback(self._open_file_from_finder)
        self.quick_file_finder.set_project_root(self.project_manager.active_project_path)
        self.quick_file_finder.show_and_focus()

    def _open_file_from_finder(self, file_path: str) -> None:
        file_path_obj = Path(file_path)
        if file_path_obj.exists():
            self.editor_manager.open_file_in_tab(file_path_obj)
            self.status_bar.showMessage(f"Opened {file_path_obj.name}", 2000)

    def _get_current_editor(self) -> QWidget | None:
        if self.editor_manager:
            current_path = self.editor_manager.get_active_file_path()
            if current_path and current_path in self.editor_manager.editors:
                return self.editor_manager.editors[current_path]
        return None

    def get_active_file_path(self) -> str | None:
        return self.editor_manager.get_active_file_path() if self.editor_manager else None

    def prepare_for_new_project_session(self) -> None:
        if self.editor_manager:
            self.editor_manager.prepare_for_new_project()
        if self.file_tree_manager: self.file_tree_manager.clear_tree()
        logger.info("[CodeViewer] Prepared for new project session")

    def load_project(self, project_path_str: str) -> None:
        project_path = Path(project_path_str)
        if self.file_tree_manager:
            self.file_tree_manager.load_existing_project_tree(project_path)
        if self.quick_file_finder:
            self.quick_file_finder.set_project_root(project_path)
        logger.info(f"[CodeViewer] Loaded project: {project_path.name}")
        self.status_bar.showMessage(f"Loaded project: {project_path.name}", 3000)

    def prepare_for_generation(self, filenames: list, project_path: str = None, is_modification: bool = False) -> None:
        if not is_modification and project_path:
            if self.file_tree_manager:
                self.file_tree_manager.setup_new_project_tree(Path(project_path), filenames)
            logger.info(f"[CodeViewer] Prepared for new project generation: {len(filenames)} files")
            self.show_window()
        elif is_modification:
            if self.file_tree_manager:
                self.file_tree_manager.add_placeholders_for_new_files(filenames)
            self._prepare_tabs_for_modification(filenames)
            logger.info(f"[CodeViewer] Prepared for modification: {len(filenames)} files")
            self.show_window()

    def _prepare_tabs_for_modification(self, filenames: list) -> None:
        if self.project_manager.active_project_path:
            for filename in filenames:
                abs_path = self.project_manager.active_project_path / filename
                if abs_path and abs_path.is_file():
                    self.editor_manager.open_file_in_tab(abs_path)

    @qasync.Slot(dict)
    def display_code(self, files: dict) -> None:
        """
        Displays the final generated code by telling the editor manager to update tabs.
        The manager is responsible for path resolution and normalization.
        """
        logger.info(f"[CodeViewer] Displaying {len(files)} file(s) and refreshing UI.")
        for filename, content in files.items():
            self.editor_manager.create_or_update_tab(filename, content)

    def display_scaffold(self, scaffold_files: dict):
        """NEW: Displays the entire project scaffold at once."""
        logger.info(f"[CodeViewer] Displaying {len(scaffold_files)} scaffold file(s).")
        self.show_window()
        if self.file_tree_manager and self.project_manager.active_project_path:
            self.file_tree_manager.setup_new_project_tree(
                self.project_manager.active_project_path,
                list(scaffold_files.keys())
            )
        self.display_code(scaffold_files)


    def _on_file_selected(self, file_path: Path) -> None:
        """Callback for when a file is selected in the file tree."""
        self.editor_manager.open_file_in_tab(file_path)

    def _on_tab_close_requested(self, index: int) -> None:
        """Callback for when a tab close button is clicked."""
        self.editor_manager.close_tab(index)

    def show_window(self) -> None:
        """Shows the code viewer window, bringing it to the front."""
        if not self.isVisible():
            self.show()
        self.activateWindow()
        self.raise_()

    def clear_all_error_highlights(self) -> None:
        """Clears all diagnostic error highlights from all open editor tabs."""
        if self.editor_manager:
            self.editor_manager.clear_all_error_highlights()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handles the window close event, checking for unsaved changes."""
        if self.editor_manager and self.editor_manager.has_unsaved_changes():
            reply = QMessageBox.question(self, "Unsaved Changes",
                                         "You have unsaved changes. Save all before exiting?",
                                         QMessageBox.StandardButton.SaveAll | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.SaveAll:
                if not self.editor_manager.save_all_files():
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        event.accept()