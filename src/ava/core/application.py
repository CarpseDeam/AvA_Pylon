# src/ava/core/application.py

import asyncio
import sys
from pathlib import Path

# --- NEW: Import QApplication for programmatic shutdown ---
from PySide6.QtWidgets import QApplication

from src.ava.core.event_bus import EventBus
from src.ava.core.managers import WindowManager, ServiceManager, TaskManager, WorkflowManager, EventCoordinator
from src.ava.core.plugins.plugin_manager import PluginManager
from src.ava.core.project_manager import ProjectManager


class Application:
    """
    Main application class that coordinates all components.
    """

    def __init__(self, project_root: Path):
        """
        Initialize the application with the project root path.

        Args:
            project_root: Root directory for data files.
        """
        self.project_root = project_root
        print(f"[Application] Initializing with data_files_root: {self.project_root}")

        self.event_bus = EventBus()
        workspace_location = self.project_root.parent / "workspace"
        self.project_manager = ProjectManager(workspace_root_path=workspace_location)
        self.plugin_manager = PluginManager(self.event_bus, self.project_root)
        self.window_manager = WindowManager(self.event_bus, self.project_manager)
        self.service_manager = ServiceManager(self.event_bus, self.project_root)
        self.task_manager = TaskManager(self.event_bus)
        self.workflow_manager = WorkflowManager(self.event_bus)
        self.event_coordinator = EventCoordinator(self.event_bus)
        self._initialization_complete = False
        self._connect_events()

    def _connect_events(self):
        """Set up event connections between components."""
        self.event_bus.subscribe("open_code_viewer_requested", self.window_manager.show_code_viewer)
        # --- NEW: Subscribe to the shutdown request from the main window ---
        self.event_bus.subscribe("application_shutdown_requested", lambda: asyncio.create_task(self.shutdown()))

    async def initialize_async(self):
        """Perform async initialization of components."""
        print("[Application] Starting async initialization...")
        try:
            self.service_manager.plugin_manager = self.plugin_manager
            self._configure_plugin_paths()
            self.plugin_manager.set_service_manager(self.service_manager)
            self.service_manager.initialize_core_components(self.project_root, self.project_manager)
            await self.service_manager.initialize_plugins()
            self.service_manager.initialize_services()
            self.service_manager.launch_background_servers()
            self.window_manager.initialize_windows(
                self.service_manager.get_llm_client(),
                self.service_manager,
                self.project_root
            )
            self.update_sidebar_plugin_status()
            self.task_manager.set_managers(self.service_manager, self.window_manager)
            self.workflow_manager.set_managers(self.service_manager, self.window_manager, self.task_manager)
            self.event_coordinator.set_managers(self.service_manager, self.window_manager, self.task_manager,
                                                self.workflow_manager)
            self.event_coordinator.wire_all_events()
            self._initialization_complete = True
            print("[Application] Async initialization complete")
        except Exception as e:
            print(f"[Application] CRITICAL ERROR during initialization: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise

    def _configure_plugin_paths(self):
        if getattr(sys, 'frozen', False):
            bundled_builtin_plugins_dir = self.project_root / "ava" / "core" / "plugins" / "examples"
            if bundled_builtin_plugins_dir.exists():
                self.plugin_manager.add_discovery_path(bundled_builtin_plugins_dir)
            custom_plugins_next_to_exe = self.project_root / "plugins"
            if custom_plugins_next_to_exe.exists():
                self.plugin_manager.add_discovery_path(custom_plugins_next_to_exe)
        else:
            actual_repo_root = self.project_root.parent
            builtin_plugins_src_dir = actual_repo_root / "src" / "ava" / "core" / "plugins" / "examples"
            if builtin_plugins_src_dir.exists():
                self.plugin_manager.add_discovery_path(builtin_plugins_src_dir)
            custom_plugins_repo_dir = actual_repo_root / "plugins"
            if custom_plugins_repo_dir.exists():
                self.plugin_manager.add_discovery_path(custom_plugins_repo_dir)

    def update_sidebar_plugin_status(self):
        """Gets plugin status from the manager and tells the sidebar to update."""
        if not self.plugin_manager or not self.window_manager: return
        try:
            enabled_plugins = self.plugin_manager.config.get_enabled_plugins()
            status = "off"
            if enabled_plugins:
                all_plugins_info = self.plugin_manager.get_all_plugins_info()
                status = "ok"
                for plugin in all_plugins_info:
                    if plugin['name'] in enabled_plugins and plugin.get('state') != 'started':
                        status = "error"
                        break
            main_window = self.window_manager.get_main_window()
            if main_window and hasattr(main_window, 'sidebar'):
                main_window.sidebar.update_plugin_status(status)
        except Exception as e:
            print(f"[Application] Error updating sidebar plugin status: {e}")

    def show(self):
        self.window_manager.show_main_window()

    async def shutdown(self):
        print("[Application] Shutting down application components...")
        try:
            if self.task_manager:
                await self.task_manager.cancel_all_tasks()
            if self.service_manager:
                await self.service_manager.shutdown()
            print("[Application] All components shut down.")
        finally:
            # --- NEW: This is the final command that will close the application ---
            # It is only called AFTER all the async cleanup above is complete.
            print("[Application] All cleanup complete. Exiting now.")
            QApplication.instance().quit()

    def is_fully_initialized(self) -> bool:
        return (self._initialization_complete and
                self.service_manager.is_fully_initialized() and
                self.window_manager.is_fully_initialized())