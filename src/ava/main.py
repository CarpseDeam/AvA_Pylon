# src/ava/main.py
import sys
from pathlib import Path

from src.ava.utils.exception_handler import setup_exception_hook

# --- ROBUST PATH HANDLING FOR SOURCE AND BUNDLED ENVIRONMENTS ---
# This block MUST come *before* any imports from 'src.ava.*' or 'ava.*'
# It ensures the application can be launched robustly from various working directories.

if getattr(sys, 'frozen', False):
    # We are running in a bundled environment (e.g., cx_Freeze, PyInstaller).
    # In this case, the `project_root` for assets and configurations is the directory
    # containing the executable itself. All modules are typically self-contained.
    project_root = Path(sys.executable).parent
else:
    # We are running from source.
    # Determine the absolute path to this script.
    current_script_path = Path(__file__).resolve()

    # The 'src' directory (where 'ava' resides) is two levels up from this script:
    # <repository_root>/src/ava/main.py
    # So, navigating up three parents from 'main.py' gives us the repository root.
    repo_root = current_script_path.parent.parent.parent

    # Add the repository root to Python's import search path (sys.path).
    # This allows imports like 'from src.ava.core.application import Application' to resolve correctly,
    # as Python will now search for 'src' directly within the 'repo_root'.
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Set 'project_root' for internal application components (like Application, PluginConfig,
    # LoadingIndicator) to the 'src' directory itself. These components expect to find
    # their assets and configurations relative to 'src' (e.g., 'ava/assets').
    project_root = repo_root / "src"

# END OF ROBUST PATH HANDLING
# --- Now it is safe to import application modules that rely on the 'src' package ---

import asyncio
import qasync
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon



async def main_async_logic(app_instance, root_path: Path):
    """
    The main asynchronous coroutine for the application.
    """
    ava_app = None
    shutdown_future = asyncio.get_event_loop().create_future()

    async def on_about_to_quit():
        print("[main] Application 'aboutToQuit' signal received. Starting graceful shutdown...")
        if ava_app:
            try:
                # Delegate the entire shutdown process to the application object
                # and WAIT for it to complete.
                await ava_app.shutdown()
                print("[main] Graceful shutdown complete.")
            except Exception as e:
                print(f"[main] Error during application shutdown: {e}")

        # Signal that the async cleanup is done, allowing the program to exit.
        if not shutdown_future.done():
            shutdown_future.set_result(True)

    app_instance.aboutToQuit.connect(lambda: asyncio.create_task(on_about_to_quit()))

    try:
        # Pass the correctly determined project_root to the Application
        from src.ava.core.application import Application
        ava_app = Application(project_root=root_path)
        await ava_app.initialize_async()
        ava_app.show()
        print("[main] Application ready and displayed.")
        # This will wait until the shutdown_future is resolved by the 'on_about_to_quit' handler.
        await shutdown_future
    except Exception as e:
        print(f"[main] CRITICAL ERROR during application startup: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "Startup Error", f"Failed to start Avakin.\n\nError: {e}")
        except Exception as msg_e:
            print(f"Could not show error message box: {msg_e}", file=sys.stderr)


if __name__ == "__main__":
    setup_exception_hook()
    app = QApplication(sys.argv)

    app.setApplicationName("Kintsugi AvA")
    app.setOrganizationName("Kintsugi AvA")

    # Use the project_root determined at the start to find the icon
    icon_path = project_root / "ava" / "assets" / "Ava_Icon.ico"

    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
        print(f"[main] Application icon set from: {icon_path}")
    else:
        print(f"[main] WARNING: Application icon not found at {icon_path}")

    # Pass the determined project_root to the main async logic
    qasync.run(main_async_logic(app, project_root))
    print("[main] Application has exited cleanly.")