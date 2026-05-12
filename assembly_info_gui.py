#!/usr/bin/env python3
import os
import subprocess
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from urllib.parse import unquote
from zipfile import ZipFile

from PySide6.QtCore import QEasingCurve, QObject, QParallelAnimationGroup, QPropertyAnimation, QThread, QTimer, QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolTip,
    QVBoxLayout,
    QWidget,
    QLabel,
)


ARCHIVE_EXTENSIONS = (".zip", ".nupkg", ".jar", ".rar")
ZIP_EXTENSIONS = (".zip", ".nupkg", ".jar")
EXTERNAL_ARCHIVE_EXTENSIONS = (".rar",)
MAX_ARCHIVE_ENTRY_BYTES = 300 * 1024 * 1024
if sys.platform == "win32":
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "dll-assembly-info"
else:
    CONFIG_DIR = Path.home() / ".config" / "dll-assembly-info"
IGNORED_ASSEMBLIES_FILE = CONFIG_DIR / "ignored-assemblies.txt"
DEFAULT_IGNORED_ASSEMBLIES = {
    "0harmony",
    "calloutinterface",
    "calloutinterfaceapi",
    "discordrpc",
    "gta",
    "gta.native",
    "gta.ui",
    "lemonui",
    "lemonui.rage",
    "lemonui.shvdn2",
    "lemonui.shvdn3",
    "lspdfr",
    "lspdfirstresponse",
    "nativeui",
    "newtonsoft.json",
    "rage",
    "ragenativeui",
    "ragepluginhook",
    "scripthookvdotnet",
    "scripthookvdotnet2",
    "scripthookvdotnet3",
    "system.buffers",
    "system.memory",
    "system.numerics.vectors",
    "system.runtime.compilerservices.unsafe",
    "system.threading.tasks.extensions",
}


@dataclass
class AssemblyDisplay:
    source: str
    entry: str
    name: str | None = None
    version: str | None = None
    message: str | None = None


class PluginTypeWorker(QObject):
    finished = Signal(str)

    def __init__(self, args: list[str]) -> None:
        super().__init__()
        self.args = args

    def run(self) -> None:
        self.finished.emit(detect_plugin_type(self.args))


def main() -> int:
    text_mode = "--text" in sys.argv
    args = [arg for arg in sys.argv[1:] if arg != "--text"]
    assemblies = filter_assemblies(inspect_args(args))
    if text_mode:
        print(format_report(assemblies))
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("Assembly info")
    app.setDesktopFileName("dll-assembly-info")
    QIcon.setThemeName(QIcon.themeName() or "breeze")

    window = AssemblyInfoWindow(assemblies, args)
    window.show()
    return app.exec()


class AssemblyInfoWindow(QWidget):
    def __init__(self, assemblies: list[AssemblyDisplay], args: list[str]) -> None:
        super().__init__()
        self.type_thread: QThread | None = None
        self.type_worker: PluginTypeWorker | None = None
        self.content_layout: QVBoxLayout | None = None
        self.rows: list[tuple[AssemblyWidget, QFrame | None]] = []
        self.active_animations: list[QParallelAnimationGroup] = []
        self.undo_shortcut: QShortcut | None = None
        self.setWindowTitle("Assembly info")
        self.setWindowIcon(QIcon.fromTheme("dialog-information"))

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        self.type_label = QLabel("Chargement...")
        self.type_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        type_font = self.type_label.font()
        type_font.setBold(True)
        type_font.setPointSize(type_font.pointSize() + 5)
        self.type_label.setFont(type_font)
        root.addWidget(self.type_label)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        self.content_layout = content_layout

        for index, assembly in enumerate(assemblies):
            line = None
            if index:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                content_layout.addWidget(line)
            widget = AssemblyWidget(assembly)
            widget.ignoreRequested.connect(self.ignore_assembly)
            content_layout.addWidget(widget)
            self.rows.append((widget, line))

        root.addWidget(content)

        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.undo_shortcut.activated.connect(self.reset_rows_to_base_state)

        self.setMinimumWidth(380)
        self.resize_to_content()
        QTimer.singleShot(0, self.resize_to_content)
        self.start_type_detection(args)

    def reset_rows_to_base_state(self) -> None:
        for row, _line in self.rows:
            row.reset_to_base_state()

    def start_type_detection(self, args: list[str]) -> None:
        self.type_thread = QThread(self)
        self.type_worker = PluginTypeWorker(args)
        self.type_worker.moveToThread(self.type_thread)
        self.type_thread.started.connect(self.type_worker.run)
        self.type_worker.finished.connect(self.set_plugin_type)
        self.type_worker.finished.connect(self.type_thread.quit)
        self.type_worker.finished.connect(self.type_worker.deleteLater)
        self.type_thread.finished.connect(self.type_thread.deleteLater)
        self.type_thread.start()

    def set_plugin_type(self, plugin_type: str) -> None:
        self.type_label.setText(plugin_type)
        QTimer.singleShot(0, self.resize_to_content)

    def resize_to_content(self) -> None:
        self.adjustSize()
        hint = self.sizeHint()
        self.resize(max(450, hint.width()), max(150, hint.height()))
        self.setMinimumHeight(min(150, max(132, hint.height())))

    def ignore_assembly(self, assembly_name: str, widget: QWidget) -> None:
        add_user_ignored_assembly(assembly_name)
        QToolTip.showText(widget.mapToGlobal(widget.rect().center()), "Ajoute aux ignores", widget)

        row_index = next((index for index, (row, _line) in enumerate(self.rows) if row is widget), -1)
        if row_index < 0:
            return

        row, line = self.rows.pop(row_index)
        if len(self.rows) == 0:
            self.rows.append((row, line))
            return

        if row_index == 0 and self.rows and self.rows[0][1] is not None and self.content_layout is not None:
            first_row, first_line = self.rows[0]
            self.content_layout.removeWidget(first_line)
            first_line.deleteLater()
            self.rows[0] = (first_row, None)

        self.animate_remove(row, line)

    def animate_remove(self, row: QWidget, line: QFrame | None) -> None:
        widgets = [widget for widget in (line, row) if widget is not None]
        group = QParallelAnimationGroup(self)
        self.active_animations.append(group)

        for widget in widgets:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)

            opacity = QPropertyAnimation(effect, b"opacity", group)
            opacity.setDuration(170)
            opacity.setStartValue(1.0)
            opacity.setEndValue(0.0)
            opacity.setEasingCurve(QEasingCurve.Type.InOutQuad)
            group.addAnimation(opacity)

            height = QPropertyAnimation(widget, b"maximumHeight", group)
            height.setDuration(190)
            height.setStartValue(widget.sizeHint().height())
            height.setEndValue(0)
            height.setEasingCurve(QEasingCurve.Type.InOutQuad)
            group.addAnimation(height)

        window_height = QPropertyAnimation(self, b"minimumHeight", group)
        window_height.setDuration(190)
        window_height.setStartValue(self.height())
        window_height.setEndValue(max(132, self.height() - sum(widget.sizeHint().height() for widget in widgets) - 8))
        window_height.setEasingCurve(QEasingCurve.Type.InOutQuad)
        group.addAnimation(window_height)

        window_max_height = QPropertyAnimation(self, b"maximumHeight", group)
        window_max_height.setDuration(190)
        window_max_height.setStartValue(self.height())
        window_max_height.setEndValue(max(132, self.height() - sum(widget.sizeHint().height() for widget in widgets) - 8))
        window_max_height.setEasingCurve(QEasingCurve.Type.InOutQuad)
        group.addAnimation(window_max_height)

        group.finished.connect(lambda: self.finish_remove_animation(group, widgets))
        group.start()

    def finish_remove_animation(self, group: QParallelAnimationGroup, widgets: list[QWidget]) -> None:
        if self.content_layout is not None:
            for widget in widgets:
                self.content_layout.removeWidget(widget)
                widget.deleteLater()
        self.setMaximumHeight(16777215)
        self.resize_to_content()
        if group in self.active_animations:
            self.active_animations.remove(group)
        group.deleteLater()


class AssemblyWidget(QWidget):
    ignoreRequested = Signal(str, QWidget)

    def __init__(self, assembly: AssemblyDisplay) -> None:
        super().__init__()
        self.assembly_name = assembly.name
        self.assembly_version = assembly.version
        self.assembly_file_name = Path(assembly.entry.replace("\\", "/")).name
        self.name_mismatch = self.has_name_mismatch()
        self.version_is_zero = self.has_zero_version()
        self.default_name_checked = self.name_mismatch
        self.default_version_checked = self.should_check_version_by_default()
        self.name_checkbox: QCheckBox | None = None
        self.version_checkbox: QCheckBox | None = None
        self.message_button: QPushButton | None = None
        self.message_mode = "desc"
        self.button_animation: QPropertyAnimation | None = None
        self.button_change_timer: QTimer | None = None
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(5)

        if assembly.name is not None and assembly.version is not None:
            row = 0
            self.add_row(layout, row, "Assembly name:", assembly.name, warning=self.name_mismatch, highlighted=self.name_mismatch)
            row += 1
            if self.name_mismatch:
                self.add_row(layout, row, "DLL name:", self.assembly_file_name, include_checkbox=False, highlighted=True)
                row += 1
            self.add_row(layout, row, "Assembly version:", assembly.version, highlighted=self.version_is_zero)
            row += 1
            self.add_message_button(layout, row)
            self.reset_to_base_state()
        else:
            message = QLabel(assembly.message or "Aucune assembly trouvee.")
            message.setWordWrap(True)
            message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(message, 0, 0, 1, 4)

        layout.setColumnStretch(1, 1)

    def has_name_mismatch(self) -> bool:
        if not self.assembly_name or not self.assembly_file_name:
            return False
        file_name = normalized_file_identity(self.assembly_file_name)
        assembly_name = normalized_file_identity(self.assembly_name)
        return bool(file_name and assembly_name and file_name != assembly_name)

    def should_check_version_by_default(self) -> bool:
        version = (self.assembly_version or "").strip()
        if version == "0.0.0.0":
            return True
        if version == "1.0.0.0":
            return not self.name_mismatch
        return False

    def has_zero_version(self) -> bool:
        return (self.assembly_version or "").strip() == "0.0.0.0"

    def add_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        value: str,
        *,
        include_checkbox: bool = True,
        warning: bool = False,
        highlighted: bool = False,
    ) -> None:
        label_area = QWidget()
        label_layout = QHBoxLayout(label_area)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(4)

        label = QLabel(label_text)
        label_layout.addWidget(label)
        if warning:
            warning_label = QLabel()
            warning_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
            warning_label.setPixmap(warning_icon.pixmap(QSize(16, 16)))
            warning_label.setToolTip("Assembly name différent du nom du fichier")
            label_layout.addWidget(warning_label)
        label_layout.addStretch(1)
        label_area.setMinimumWidth(128 if warning else 108)
        layout.addWidget(label_area, row, 0)

        field = QLineEdit(value)
        field.setReadOnly(True)
        field.setClearButtonEnabled(False)
        field.setTextMargins(2, 0, 2, 0)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if highlighted:
            field.setStyleSheet(
                """
                QLineEdit {
                    border: 1px solid #d9822b;
                    border-radius: 3px;
                    padding: 2px 4px;
                }
                """
            )
        if label_text.rstrip(":") == "Assembly name":
            field.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            field.customContextMenuRequested.connect(
                lambda position, name=value, widget=field: self.show_assembly_name_menu(widget, position, name)
            )
        layout.addWidget(field, row, 1)

        button = QPushButton()
        button.setIcon(QIcon.fromTheme("edit-copy", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)))
        button.setIconSize(QSize(19, 19))
        button.setFixedSize(34, 32)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setToolTip("Copier")
        button.clicked.connect(lambda checked=False, text=value, widget=button: copy_text(text, widget))
        layout.addWidget(button, row, 2)

        if not include_checkbox:
            return

        checkbox = QCheckBox()
        checkbox.setFixedSize(26, 26)
        checkbox.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        checkbox.setToolTip(f"Inclure {label_text.rstrip(':').lower()}")
        layout.addWidget(checkbox, row, 3, Qt.AlignmentFlag.AlignCenter)
        if label_text.rstrip(":") == "Assembly name":
            self.name_checkbox = checkbox
        elif label_text.rstrip(":") == "Assembly version":
            self.version_checkbox = checkbox

    def add_message_button(self, layout: QGridLayout, row: int) -> None:
        button = QPushButton("Copier Desc.")
        button.setMinimumHeight(28)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Copier le message de description")
        button.clicked.connect(self.copy_selected_message)
        button.setStyleSheet(
            """
            QPushButton {
                border: 1px solid palette(midlight);
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: palette(alternate-base);
            }
            QPushButton:disabled {
                color: palette(highlighted-text);
                background: palette(highlight);
                border-color: palette(highlight);
            }
            QPushButton:pressed {
                padding-top: 5px;
                padding-bottom: 3px;
            }
            """
        )
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(1.0)
        button.setGraphicsEffect(effect)
        layout.addWidget(button, row, 0, 1, 4, Qt.AlignmentFlag.AlignHCenter)
        self.message_button = button

    def copy_selected_message(self) -> None:
        if self.message_button is None:
            return

        message = self.build_selected_message(self.message_mode)
        if message is None:
            QToolTip.showText(self.message_button.mapToGlobal(self.message_button.rect().center()), "Coche au moins une option", self.message_button)
            return

        QGuiApplication.clipboard().setText(message)
        QToolTip.showText(self.message_button.mapToGlobal(self.message_button.rect().center()), "Copié", self.message_button)
        if self.message_mode == "desc":
            self.message_mode = "comment"
            self.show_copied_then_change("Copier com", "Copier le commentaire")
        else:
            self.show_copied_then_change("Copier com", "Copier le commentaire")

    def build_selected_message(self, mode: str) -> str | None:
        name_checked = self.name_checkbox is not None and self.name_checkbox.isChecked()
        version_checked = self.version_checkbox is not None and self.version_checkbox.isChecked()
        if not name_checked and not version_checked:
            return None

        name = self.assembly_name or ""
        file_name = self.assembly_file_name or name
        version = self.assembly_version or ""
        if mode == "desc":
            if name_checked and version_checked:
                return f'Due to the plugin\'s incorrect assembly info, version "{version}" is logged, and the file is named "{file_name}".'
            if name_checked:
                return f'Due to the plugin\'s incorrect assembly info, the file is named "{file_name}".'
            return f"Due to the incorrect AssemblyInfo of the plugin, version {version} is logged."

        if name_checked and version_checked:
            return f"Hello, I just wanted to point out that the assembly version of your plugin is: `{version} instead of: and the Assembly name of your plugins is: `{name}"
        if name_checked:
            return f"Hello, I just wanted to point out that the assembly name of your plugins is: `{name}"
        return f"Hello, I just wanted to point out that the assembly version of your plugin is: `{version} instead of: `"

    def show_copied_then_change(self, text: str, tooltip: str) -> None:
        if self.message_button is None:
            return

        if self.button_change_timer is not None:
            self.button_change_timer.stop()
            self.button_change_timer.deleteLater()

        self.message_button.setText("Copié!")
        self.message_button.setEnabled(False)
        self.message_button.adjustSize()
        self.button_change_timer = QTimer(self)
        self.button_change_timer.setSingleShot(True)
        self.button_change_timer.timeout.connect(lambda: self.animate_message_button_change(text, tooltip))
        self.button_change_timer.start(620)

    def reset_to_base_state(self) -> None:
        if self.button_change_timer is not None:
            self.button_change_timer.stop()
            self.button_change_timer.deleteLater()
            self.button_change_timer = None

        if self.button_animation is not None:
            self.button_animation.stop()
            self.button_animation = None

        if self.name_checkbox is not None:
            self.name_checkbox.setChecked(self.default_name_checked)
        if self.version_checkbox is not None:
            self.version_checkbox.setChecked(self.default_version_checked)

        self.message_mode = "desc"
        if self.message_button is not None:
            self.message_button.setText("Copier Desc.")
            self.message_button.setToolTip("Copier le message de description")
            self.message_button.setEnabled(True)
            effect = self.message_button.graphicsEffect()
            if isinstance(effect, QGraphicsOpacityEffect):
                effect.setOpacity(1.0)
            self.message_button.adjustSize()

    def animate_message_button_change(self, text: str, tooltip: str) -> None:
        if self.message_button is None or self.message_button.graphicsEffect() is None:
            return

        if self.button_change_timer is not None:
            self.button_change_timer.deleteLater()
            self.button_change_timer = None

        effect = self.message_button.graphicsEffect()
        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(110)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def switch_text() -> None:
            if self.message_button is None:
                return
            self.message_button.setText(text)
            self.message_button.setToolTip(tooltip)
            self.message_button.setEnabled(True)
            self.message_button.adjustSize()
            fade_in = QPropertyAnimation(effect, b"opacity", self)
            fade_in.setDuration(150)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.button_animation = fade_in
            fade_in.start()

        fade_out.finished.connect(switch_text)
        self.button_animation = fade_out
        fade_out.start()

    def show_assembly_name_menu(self, field: QLineEdit, position, assembly_name: str) -> None:
        menu = field.createStandardContextMenu()
        menu.addSeparator()
        action = menu.addAction("Ignorer cet assembly")
        selected = menu.exec(field.mapToGlobal(position))
        if selected == action:
            self.ignoreRequested.emit(assembly_name, self)
        menu.deleteLater()


def copy_text(text: str, widget: QWidget) -> None:
    QGuiApplication.clipboard().setText(text)
    if isinstance(widget, QPushButton):
        widget.setDown(False)
        widget.clearFocus()
        copy_icon = widget.icon()
        copy_tooltip = widget.toolTip()
        confirm_icon = QIcon.fromTheme("dialog-ok-apply", widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        widget.setIcon(confirm_icon)
        widget.setToolTip("Copie")
        QToolTip.showText(widget.mapToGlobal(widget.rect().center()), "Copie", widget)

        def restore() -> None:
            widget.setIcon(copy_icon)
            widget.setToolTip(copy_tooltip)
            widget.setDown(False)
            widget.clearFocus()
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

        QTimer.singleShot(850, restore)
    else:
        QToolTip.showText(widget.mapToGlobal(widget.rect().center()), "Copie", widget)


def inspect_args(args: list[str]) -> list[AssemblyDisplay]:
    if not args:
        return [AssemblyDisplay("Resultat", "Assembly info", message="Glisse un fichier .dll, .exe, .zip ou .rar sur cet outil, ou lance-le depuis Dolphin.")]

    assemblies: list[AssemblyDisplay] = []
    for arg in args:
        try:
            if arg.startswith(("zip:/", "tar:/", "rar:/", "krarc:/")):
                assemblies.extend(inspect_archive_url(arg))
            else:
                path = Path(unquote(arg.removeprefix("file://"))) if arg.startswith("file://") else Path(arg)
                assemblies.extend(inspect_path(path))
        except Exception as exc:
            assemblies.append(AssemblyDisplay(arg, arg, message=f"Erreur: {exc}"))
    return assemblies or [AssemblyDisplay("Resultat", "Assembly info", message="Aucune assembly trouvee.")]


def filter_assemblies(assemblies: list[AssemblyDisplay]) -> list[AssemblyDisplay]:
    ignored = load_ignored_assemblies()
    filtered = [
        assembly for assembly in assemblies
        if assembly.name is None or normalize_assembly_name(assembly.name) not in ignored
    ]
    if any(assembly.name is not None for assembly in filtered):
        return filtered
    return assemblies


def load_ignored_assemblies() -> set[str]:
    ignored = set(DEFAULT_IGNORED_ASSEMBLIES)
    try:
        for line in IGNORED_ASSEMBLIES_FILE.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                ignored.add(normalize_assembly_name(name))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return ignored


def add_user_ignored_assembly(assembly_name: str) -> None:
    normalized = normalize_assembly_name(assembly_name)
    if not normalized:
        return
    existing = load_ignored_assemblies()
    if normalized in existing:
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with IGNORED_ASSEMBLIES_FILE.open("a", encoding="utf-8") as file:
        file.write(f"{assembly_name.strip()}\n")


def normalize_assembly_name(name: str) -> str:
    lowered = name.strip().lower()
    return lowered[:-4] if lowered.endswith(".dll") else lowered


def normalized_file_identity(name: str) -> str:
    lowered = name.strip().lower()
    for suffix in (".dll", ".exe"):
        if lowered.endswith(suffix):
            return lowered[:-len(suffix)]
    return lowered


def inspect_path(path: Path) -> list[AssemblyDisplay]:
    source = str(path)
    lower = path.name.lower()
    if path.is_dir() and lower.endswith(EXTERNAL_ARCHIVE_EXTENSIONS):
        return inspect_rar_directory(path, source)
    if not path.is_file():
        return [AssemblyDisplay(source, path.name or source, message="Introuvable ou pas un fichier normal.")]

    if lower.endswith(ZIP_EXTENSIONS):
        return inspect_zip(path, source)
    if lower.endswith(EXTERNAL_ARCHIVE_EXTENSIONS):
        return inspect_external_archive(path, source)
    return [inspect_bytes(source, path.name, path.read_bytes())]


def inspect_rar_directory(path: Path, source: str) -> list[AssemblyDisplay]:
    assemblies: list[AssemblyDisplay] = []
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.name.lower().endswith((".dll", ".exe")):
            entry = candidate.relative_to(path).as_posix()
            try:
                assemblies.append(inspect_bytes(source, entry, candidate.read_bytes()))
            except Exception as exc:
                assemblies.append(AssemblyDisplay(source, entry, message=f"Erreur de lecture dossier: {exc}"))
    if not assemblies:
        assemblies.append(AssemblyDisplay(source, path.name, message="Aucun .dll ou .exe trouve dans le dossier .rar."))
    return assemblies


def inspect_zip(path: Path, source: str) -> list[AssemblyDisplay]:
    assemblies: list[AssemblyDisplay] = []
    with ZipFile(path) as archive:
        for name in archive.namelist():
            lower = name.lower()
            if lower.endswith((".dll", ".exe")) and not name.endswith("/"):
                assemblies.append(inspect_bytes(source, name, archive.read(name)))
    if not assemblies:
        assemblies.append(AssemblyDisplay(source, path.name, message="Aucun .dll ou .exe trouve dans le zip."))
    return assemblies


def inspect_external_archive(path: Path, source: str) -> list[AssemblyDisplay]:
    assemblies: list[AssemblyDisplay] = []
    names = list_external_archive_entries(path)
    for name in names:
        lower = name.lower()
        if lower.endswith((".dll", ".exe")) and not name.endswith("/"):
            try:
                assemblies.append(inspect_bytes(source, name, read_external_archive_entry(path, name)))
            except Exception as exc:
                assemblies.append(AssemblyDisplay(source, name, message=f"Erreur de lecture archive: {exc}"))
    if not assemblies:
        assemblies.append(AssemblyDisplay(source, path.name, message="Aucun .dll ou .exe trouve dans l'archive."))
    return assemblies


def list_external_archive_entries(path: Path) -> list[str]:
    for reader in (list_archive_entries_7z, list_archive_entries_lsar, list_archive_entries_bsdtar):
        try:
            entries = reader(path)
            if entries:
                return entries
        except Exception:
            continue
    raise ValueError("Impossible de lire l'archive avec 7z, lsar ou bsdtar")


def list_archive_entries_7z(path: Path) -> list[str]:
    if which("7z") is None:
        raise ValueError("7z introuvable")
    result = subprocess.run(
        ["7z", "l", "-slt", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout or "7z n'a pas pu lire l'archive").strip())

    entries: list[str] = []
    current_path: str | None = None
    current_is_dir = False

    def flush() -> None:
        if current_path and not current_is_dir and current_path != str(path):
            entries.append(current_path.replace("\\", "/"))

    for line in result.stdout.splitlines():
        if line.startswith("Path = "):
            flush()
            current_path = line.removeprefix("Path = ").strip()
            current_is_dir = False
        elif line.startswith("Folder = "):
            current_is_dir = line.removeprefix("Folder = ").strip() == "+"
        elif line.startswith("Attributes = "):
            attrs = line.removeprefix("Attributes = ").strip().upper()
            current_is_dir = current_is_dir or "D" in attrs
    flush()
    return entries


def list_archive_entries_lsar(path: Path) -> list[str]:
    if which("lsar") is None:
        raise ValueError("lsar introuvable")
    result = subprocess.run(
        ["lsar", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout or "lsar n'a pas pu lire l'archive").strip())

    entries: list[str] = []
    for index, line in enumerate(result.stdout.splitlines()):
        if index == 0 or not line.strip():
            continue
        name = line.rstrip("/").strip()
        if name and not line.endswith("/"):
            entries.append(name.replace("\\", "/"))
    return entries


def list_archive_entries_bsdtar(path: Path) -> list[str]:
    if which("bsdtar") is None:
        raise ValueError("bsdtar introuvable")
    result = subprocess.run(
        ["bsdtar", "-tf", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or result.stdout or "bsdtar n'a pas pu lire l'archive").strip())

    entries: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if name and not name.endswith("/"):
            entries.append(name.replace("\\", "/"))
    return entries


def read_external_archive_entry(path: Path, entry_name: str, max_bytes: int = MAX_ARCHIVE_ENTRY_BYTES) -> bytes:
    errors: list[str] = []
    for reader in (read_archive_entry_7z, read_archive_entry_bsdtar, read_archive_entry_unar):
        try:
            data = reader(path, entry_name)
            if len(data) > max_bytes:
                raise ValueError("entree archive trop grande")
            return data
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError("Impossible d'extraire l'entree archive: " + " | ".join(errors[-3:]))


def read_archive_entry_7z(path: Path, entry_name: str) -> bytes:
    if which("7z") is None:
        raise ValueError("7z introuvable")
    result = subprocess.run(
        ["7z", "x", "-so", str(path), entry_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="ignore") or "7z n'a pas pu extraire l'entree"
        raise ValueError(message.strip())
    return result.stdout


def read_archive_entry_bsdtar(path: Path, entry_name: str) -> bytes:
    if which("bsdtar") is None:
        raise ValueError("bsdtar introuvable")
    result = subprocess.run(
        ["bsdtar", "-xOf", str(path), entry_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="ignore") or "bsdtar n'a pas pu extraire l'entree"
        raise ValueError(message.strip())
    return result.stdout


def read_archive_entry_unar(path: Path, entry_name: str) -> bytes:
    if which("unar") is None:
        raise ValueError("unar introuvable")
    with tempfile.TemporaryDirectory(prefix="dll-assembly-info-") as temp_dir:
        result = subprocess.run(
            ["unar", "-o", temp_dir, "-force-overwrite", "-quiet", str(path), entry_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            raise ValueError((result.stderr or result.stdout or "unar n'a pas pu extraire l'entree").strip())

        normalized = entry_name.replace("\\", "/").split("/")
        target_name = normalized[-1]
        candidates = [candidate for candidate in Path(temp_dir).rglob(target_name) if candidate.is_file()]
        for candidate in candidates:
            if candidate.as_posix().endswith("/".join(normalized)):
                return candidate.read_bytes()
        if candidates:
            return candidates[0].read_bytes()
    raise ValueError("unar n'a pas produit le fichier demande")


def inspect_archive_url(url: str) -> list[AssemblyDisplay]:
    archive_path, entry_name = parse_archive_url(url)
    if archive_path.name.lower().endswith(EXTERNAL_ARCHIVE_EXTENSIONS):
        normalized = entry_name.replace("\\", "/")
        for name in list_external_archive_entries(archive_path):
            if name.replace("\\", "/") == normalized:
                return [inspect_bytes(str(archive_path), name, read_external_archive_entry(archive_path, name))]
        return [AssemblyDisplay(str(archive_path), entry_name, message=f"Entree introuvable dans l'archive: {entry_name}")]

    with ZipFile(archive_path) as archive:
        normalized = entry_name.replace("\\", "/")
        for name in archive.namelist():
            if name.replace("\\", "/") == normalized:
                return [inspect_bytes(str(archive_path), name, archive.read(name))]
    return [AssemblyDisplay(str(archive_path), entry_name, message=f"Entree introuvable dans le zip: {entry_name}")]


def parse_archive_url(url: str) -> tuple[Path, str]:
    without_scheme = url.split(":", 1)[1].lstrip("/")
    value = "/" + without_scheme
    lower = value.lower()
    for marker in (".zip!/", ".zip/", ".nupkg!/", ".nupkg/", ".jar!/", ".jar/", ".rar!/", ".rar/"):
        index = lower.find(marker)
        if index >= 0:
            archive_end = index + (marker.index("!") if "!" in marker else marker.index("/"))
            archive = Path(unquote(value[:archive_end]))
            entry = unquote(value[index + len(marker):])
            return archive, entry
    raise ValueError("URL d'archive non reconnue")


def detect_plugin_type(args: list[str]) -> str:
    structure_votes: list[str] = []
    readme_votes: list[str] = []

    for arg in args:
        try:
            if arg.startswith(("zip:/", "tar:/", "rar:/", "krarc:/")):
                archive_path, _entry_name = parse_archive_url(arg)
                structure, readme = detect_archive_type(archive_path)
            else:
                path = Path(unquote(arg.removeprefix("file://"))) if arg.startswith("file://") else Path(arg)
                if path.is_file() and path.name.lower().endswith(ARCHIVE_EXTENSIONS):
                    structure, readme = detect_archive_type(path)
                else:
                    structure = classify_path(str(path))
                    readme = detect_nearby_readme_type(path)
            if structure:
                structure_votes.append(structure)
            if readme:
                readme_votes.append(readme)
        except Exception:
            continue

    return choose_plugin_type(structure_votes, readme_votes)


def detect_archive_type(path: Path) -> tuple[str | None, str | None]:
    structure_votes: list[str] = []
    readme_votes: list[str] = []
    if path.name.lower().endswith(EXTERNAL_ARCHIVE_EXTENSIONS):
        names = list_external_archive_entries(path)
        for name in names:
            plugin_type = classify_path(name)
            if plugin_type:
                structure_votes.append(plugin_type)

        for name in names:
            if not looks_like_readme(name):
                continue
            try:
                text = read_external_archive_entry(path, name, max_bytes=262_144).decode("utf-8", errors="ignore")
            except Exception:
                continue
            plugin_type = classify_readme(text)
            if plugin_type:
                readme_votes.append(plugin_type)
    else:
        with ZipFile(path) as archive:
            names = archive.namelist()
            for name in names:
                plugin_type = classify_path(name)
                if plugin_type:
                    structure_votes.append(plugin_type)

            for name in names:
                if not looks_like_readme(name):
                    continue
                try:
                    text = archive.read(name)[:262_144].decode("utf-8", errors="ignore")
                except Exception:
                    continue
                plugin_type = classify_readme(text)
                if plugin_type:
                    readme_votes.append(plugin_type)
    return best_vote(structure_votes), best_vote(readme_votes)


def detect_nearby_readme_type(path: Path) -> str | None:
    candidates: list[Path] = []
    current = path.parent if path.suffix else path
    for _ in range(4):
        if not current.exists():
            break
        candidates.extend(child for child in current.iterdir() if child.is_file() and looks_like_readme(child.name))
        if current.parent == current:
            break
        current = current.parent

    for readme in candidates:
        try:
            plugin_type = classify_readme(readme.read_text(encoding="utf-8", errors="ignore")[:262_144])
        except Exception:
            continue
        if plugin_type:
            return plugin_type
    return None


def choose_plugin_type(structure_votes: list[str], readme_votes: list[str]) -> str:
    structure = best_vote(structure_votes)
    if structure:
        return structure
    readme = best_vote(readme_votes)
    return readme or "Inconnu"


def best_vote(votes: list[str]) -> str | None:
    if not votes:
        return None
    priority = {"LSPDFR": 3, "SHVDN": 2, "RPH": 1}
    counts: dict[str, int] = {}
    for vote in votes:
        counts[vote] = counts.get(vote, 0) + 1
    return max(counts, key=lambda vote: (counts[vote], priority.get(vote, 0)))


def classify_path(path: str) -> str | None:
    parts = [part for part in path.replace("\\", "/").lower().split("/") if part]
    if not parts:
        return None
    if "plugins" in parts:
        for index, part in enumerate(parts[:-1]):
            if part == "plugins" and index + 1 < len(parts) and parts[index + 1] == "lspdfr":
                return "LSPDFR"
    if "scripts" in parts or "script" in parts:
        return "SHVDN"
    if "plugins" in parts:
        return "RPH"
    return None


def classify_readme(text: str) -> str | None:
    normalized = " ".join(text.lower().replace("\\", "/").split())
    if "plugins/lspdfr" in normalized or ("lspdfr" in normalized and "plugins" in normalized):
        return "LSPDFR"
    if "scripts/" in normalized or "/scripts" in normalized or "script/" in normalized or "/script" in normalized:
        return "SHVDN"
    if "scripthookvdotnet" in normalized or "script hook v .net" in normalized or "shvdn" in normalized:
        return "SHVDN"
    if "rage plugin hook" in normalized or "ragepluginhook" in normalized:
        return "RPH"
    if "plugins/" in normalized or "/plugins" in normalized:
        return "RPH"
    return None


def looks_like_readme(path: str) -> bool:
    name = Path(path.replace("\\", "/")).name.lower()
    return (
        ("readme" in name or "install" in name or "installation" in name)
        and name.endswith((".txt", ".md", ".rtf", ".html", ".htm"))
    )


def inspect_bytes(source: str, entry: str, data: bytes) -> AssemblyDisplay:
    try:
        name, version = read_dotnet_assembly(data)
        return AssemblyDisplay(source, entry, name=name, version=version)
    except Exception as exc:
        return AssemblyDisplay(source, entry, message=f"Pas une assembly .NET lisible: {exc}")


def format_report(assemblies: list[AssemblyDisplay]) -> str:
    lines: list[str] = []
    current_source: str | None = None
    for assembly in assemblies:
        if assembly.source != current_source:
            if lines:
                lines.append("")
            lines.append(f"Fichier: {assembly.source}")
            current_source = assembly.source
        if "/" in assembly.entry:
            prefix = "  Dans le dossier" if Path(assembly.source).is_dir() else "  Dans le zip"
        else:
            prefix = "  Element"
        lines.append(f"{prefix}: {assembly.entry}")
        if assembly.name is not None and assembly.version is not None:
            lines.append(f"    Assembly name: {assembly.name}")
            lines.append(f"    Assembly version: {assembly.version}")
        elif assembly.message:
            lines.append(f"    {assembly.message}")
    return "\n".join(lines)


def read_dotnet_assembly(data: bytes) -> tuple[str, str]:
    pe_offset = u32(data, 0x3C)
    require(pe_offset > 0 and pe_offset + 4 < len(data), "entete PE introuvable")
    require(u32(data, pe_offset) == 0x00004550, "signature PE absente")

    coff_offset = pe_offset + 4
    section_count = u16(data, coff_offset + 2)
    optional_size = u16(data, coff_offset + 16)
    optional_offset = coff_offset + 20
    section_offset = optional_offset + optional_size
    require(section_count > 0 and section_offset < len(data), "sections PE invalides")

    magic = u16(data, optional_offset)
    if magic == 0x10B:
        data_directory_offset = optional_offset + 96
    elif magic == 0x20B:
        data_directory_offset = optional_offset + 112
    else:
        raise ValueError("format PE inconnu")

    cli_directory_offset = data_directory_offset + 14 * 8
    require(cli_directory_offset + 8 <= len(data), "repertoire CLR absent")
    cli_rva = u32(data, cli_directory_offset)
    if cli_rva == 0:
        raise ValueError("pas d'entete CLR")

    sections = read_sections(data, section_offset, section_count)
    cli_offset = rva_to_offset(cli_rva, sections, len(data))
    require(cli_offset + 16 <= len(data), "entete CLR invalide")
    metadata_rva = u32(data, cli_offset + 8)
    metadata_offset = rva_to_offset(metadata_rva, sections, len(data))
    tables, strings = read_metadata_streams(data, metadata_offset)
    if tables is None or strings is None:
        raise ValueError("streams metadata #~/#Strings absents")
    return read_assembly_table(tables, strings)


def read_sections(data: bytes, section_offset: int, section_count: int) -> list[tuple[int, int, int, int]]:
    sections = []
    for index in range(section_count):
        offset = section_offset + index * 40
        require(offset + 40 <= len(data), "table des sections tronquee")
        virtual_size = u32(data, offset + 8)
        virtual_address = u32(data, offset + 12)
        raw_size = u32(data, offset + 16)
        raw_pointer = u32(data, offset + 20)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_pointer, raw_size))
    return sections


def rva_to_offset(rva: int, sections: list[tuple[int, int, int, int]], file_length: int) -> int:
    for virtual_address, virtual_size, raw_pointer, _raw_size in sections:
        if virtual_address <= rva < virtual_address + virtual_size:
            offset = raw_pointer + (rva - virtual_address)
            require(0 <= offset < file_length, "RVA hors fichier")
            return offset
    if 0 <= rva < file_length:
        return rva
    raise ValueError("RVA metadata introuvable")


def read_metadata_streams(data: bytes, metadata_offset: int) -> tuple[bytes | None, bytes | None]:
    require(metadata_offset + 20 <= len(data), "racine metadata tronquee")
    require(u32(data, metadata_offset) == 0x424A5342, "signature metadata CLR absente")
    version_length = u32(data, metadata_offset + 12)
    cursor = align4(metadata_offset + 16 + version_length)
    require(cursor + 4 <= len(data), "entete streams metadata tronque")
    cursor += 2
    stream_count = u16(data, cursor)
    cursor += 2

    tables = None
    strings = None
    for _ in range(stream_count):
        require(cursor + 8 <= len(data), "stream metadata tronque")
        stream_offset = u32(data, cursor)
        stream_size = u32(data, cursor + 4)
        cursor += 8
        name_start = cursor
        while cursor < len(data) and data[cursor] != 0:
            cursor += 1
        require(cursor < len(data), "nom de stream metadata invalide")
        name = data[name_start:cursor].decode("utf-8", errors="replace")
        cursor = align4(cursor + 1)
        absolute = metadata_offset + stream_offset
        require(absolute >= 0 and stream_size >= 0 and absolute + stream_size <= len(data), "stream metadata hors fichier")
        content = data[absolute:absolute + stream_size]
        if name in ("#~", "#-"):
            tables = content
        elif name == "#Strings":
            strings = content
    return tables, strings


def read_assembly_table(tables: bytes, strings: bytes) -> tuple[str, str]:
    require(len(tables) >= 24, "stream tables tronque")
    heap_sizes = tables[6]
    valid_mask = struct.unpack_from("<Q", tables, 8)[0]
    cursor = 24
    rows = [0] * 64
    for table in range(64):
        if (valid_mask >> table) & 1:
            require(cursor + 4 <= len(tables), "compteurs de tables tronques")
            rows[table] = u32(tables, cursor)
            cursor += 4

    assembly_table = 0x20
    if rows[assembly_table] < 1:
        raise ValueError("table Assembly absente")

    assembly_offset = cursor
    for table in range(assembly_table):
        assembly_offset += rows[table] * row_size(table, rows, heap_sizes)

    require(assembly_offset + 16 <= len(tables), "ligne Assembly tronquee")
    major = u16(tables, assembly_offset + 4)
    minor = u16(tables, assembly_offset + 6)
    build = u16(tables, assembly_offset + 8)
    revision = u16(tables, assembly_offset + 10)
    row_cursor = assembly_offset + 16 + blob_index_size(heap_sizes)
    name_index = heap_index(tables, row_cursor, string_index_size(heap_sizes))
    name = read_string_heap(strings, name_index)
    if not name:
        raise ValueError("nom Assembly vide")
    return name, f"{major}.{minor}.{build}.{revision}"


def row_size(table: int, rows: list[int], heap_sizes: int) -> int:
    str_i = string_index_size(heap_sizes)
    guid = guid_index_size(heap_sizes)
    blob = blob_index_size(heap_sizes)
    match table:
        case 0:
            return 2 + str_i + guid + guid + guid
        case 1:
            return coded_index_size(rows, 2, 0, 26, 35, 1) + str_i + str_i
        case 2:
            return 4 + str_i + str_i + coded_index_size(rows, 2, 2, 1, 27) + table_index_size(rows, 4) + table_index_size(rows, 6)
        case 3:
            return table_index_size(rows, 4)
        case 4:
            return 2 + str_i + blob
        case 5:
            return table_index_size(rows, 6)
        case 6:
            return 4 + 2 + 2 + str_i + blob + table_index_size(rows, 8)
        case 7:
            return table_index_size(rows, 8)
        case 8:
            return 2 + 2 + str_i
        case 9:
            return table_index_size(rows, 2) + coded_index_size(rows, 2, 2, 1, 27)
        case 10:
            return coded_index_size(rows, 3, 2, 1, 26, 6, 27) + str_i + blob
        case 11:
            return 2 + coded_index_size(rows, 2, 4, 8, 23) + blob
        case 12:
            return coded_index_size(rows, 5, 6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 44, 43) + coded_index_size(rows, 3, 6, 10) + blob
        case 13:
            return coded_index_size(rows, 1, 4, 8) + blob
        case 14:
            return 2 + coded_index_size(rows, 2, 2, 6, 32) + blob
        case 15:
            return 2 + 4 + table_index_size(rows, 2)
        case 16:
            return 4 + table_index_size(rows, 4)
        case 17:
            return blob
        case 18:
            return table_index_size(rows, 2) + table_index_size(rows, 20)
        case 19:
            return table_index_size(rows, 20)
        case 20:
            return 2 + str_i + coded_index_size(rows, 2, 2, 1, 27)
        case 21:
            return table_index_size(rows, 2) + table_index_size(rows, 23)
        case 22:
            return table_index_size(rows, 23)
        case 23:
            return 2 + str_i + blob
        case 24:
            return 2 + table_index_size(rows, 6) + coded_index_size(rows, 1, 20, 23)
        case 25:
            return table_index_size(rows, 2) + coded_index_size(rows, 1, 6, 10) + coded_index_size(rows, 1, 6, 10)
        case 26:
            return str_i
        case 27:
            return blob
        case 28:
            return 2 + coded_index_size(rows, 1, 4, 6) + str_i + table_index_size(rows, 26)
        case 29:
            return 4 + table_index_size(rows, 4)
        case 30:
            return 4 + 4
        case 31:
            return 4
    raise ValueError(f"table metadata non supportee avant Assembly: {table}")


def string_index_size(heap_sizes: int) -> int:
    return 4 if heap_sizes & 0x01 else 2


def guid_index_size(heap_sizes: int) -> int:
    return 4 if heap_sizes & 0x02 else 2


def blob_index_size(heap_sizes: int) -> int:
    return 4 if heap_sizes & 0x04 else 2


def table_index_size(rows: list[int], table: int) -> int:
    return 4 if rows[table] >= 0x10000 else 2


def coded_index_size(rows: list[int], tag_bits: int, *tables: int) -> int:
    max_rows = max((rows[table] for table in tables), default=0)
    return 2 if max_rows < (1 << (16 - tag_bits)) else 4


def heap_index(data: bytes, offset: int, size: int) -> int:
    return u32(data, offset) if size == 4 else u16(data, offset)


def read_string_heap(strings: bytes, index: int) -> str:
    require(0 <= index < len(strings), "index #Strings hors limite")
    end = strings.find(b"\0", index)
    if end < 0:
        end = len(strings)
    return strings[index:end].decode("utf-8", errors="replace")


def align4(value: int) -> int:
    return (value + 3) & ~3


def u16(data: bytes, offset: int) -> int:
    require(offset + 2 <= len(data), "lecture hors fichier")
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    require(offset + 4 <= len(data), "lecture hors fichier")
    return struct.unpack_from("<I", data, offset)[0]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


if __name__ == "__main__":
    raise SystemExit(main())
