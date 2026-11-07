"""Fenn tile and mixed-format conversion queue."""

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

import conversion
import fenn


MAX_BATCH = 100
FILE_ICONS = {
    "Image": "file-image", "Animated image": "file-image", "Document": "file-doc",
    "Spreadsheet": "file-xls", "Presentation": "file-ppt", "PDF": "file-pdf",
    "Audio": "file-audio", "Video": "file-video", "Archive": "file-zip",
}


@dataclass
class File:
    id: str
    path: Path
    family: str = ""
    targets: tuple = ()
    engine: str | None = None
    problem: str = ""
    target: conversion.Target | None = None

    @property
    def needs_office(self):
        return self.family in conversion.OFFICE and self.engine is None


def display_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def explain(error):
    if isinstance(error, (Image.DecompressionBombError, Image.DecompressionBombWarning)):
        return "Image exceeds 40 megapixels."
    if isinstance(error, UnidentifiedImageError):
        return "Unsupported or unreadable image."
    if isinstance(error, PermissionError):
        return "Cannot read the file or write to its folder."
    return str(error) or type(error).__name__


class Converter:
    def __init__(self):
        self.app = fenn.Plugin()
        self.pending = {}
        self.selected = None
        self.results = {}
        self.total = 0
        self.busy = ""
        self.notice = ""
        self.setup_error = ""
        self.next_id = 0
        self.worker = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.app.on_message("files")(self.add_files)
        self.app.on_message("layout")(self.on_layout)
        self.app.on_message("page_open")(self.on_page_open)
        self.app.on_message("event")(self.on_event)
        self.app.on_message("shutdown")(self.shutdown)

    def draw(self):
        icon = fenn.icon("arrows-left-right", color="accent", size=18)
        if self.app.tile_size == "small":
            self.app.tile(fenn.column([icon], align="center", justify="center"))
        else:
            label = {"inspect": "Checking", "convert": "Converting", "install": "Setting up"}.get(
                self.busy, "Convert"
            )
            self.app.tile(fenn.row([icon, fenn.text(label)], align="center", gap=5))

        children = []
        if self.busy == "install":
            children.append(fenn.card([
                fenn.text("Downloading and installing LibreOffice", size="title"),
                fenn.text("Follow any Windows setup prompts. Your queue will be here when setup finishes.",
                          color="dim", wrap=True),
            ], padding=12))
        elif self.busy == "inspect":
            children.append(fenn.card([fenn.text("Checking file types…", size="title")], padding=12))
        elif self.busy == "convert":
            children.extend([
                fenn.text(f"Converting {len(self.results)} of {self.total}"),
                fenn.progress(len(self.results) / self.total),
            ])
        elif self.pending:
            children.extend(self.queue_view())
        else:
            children.append(fenn.card([
                fenn.icon("tray-arrow-down", size=30, color="accent"),
                fenn.text("Drop files onto the notch", size="title"),
                fenn.text("Choose an output format and save a copy beside the original.",
                          color="dim", wrap=True),
            ], padding=14, gap=7))

        if self.notice:
            children.append(fenn.text(self.notice, color="orange", wrap=True))
        if self.results:
            if self.busy != "convert":
                count = sum(path is not None for path, _ in self.results.values())
                summary = [
                    fenn.text(f"{count} converted, {self.total - count} failed", bold=True),
                    fenn.spacer(),
                ]
                if count:
                    summary.append(fenn.button("folder", label="Open folder", icon="folder-open"))
                children.append(fenn.row(summary, align="center"))
            children.append(fenn.list_view([item for _, item in self.results.values()]))
        self.app.page(fenn.column(children, scroll=True, gap=8))

    def queue_view(self):
        active = self.pending[self.selected]
        ready = sum(file.target is not None for file in self.pending.values())
        details = [
            fenn.row([
                fenn.icon(FILE_ICONS.get(active.family, "files"), color="accent"),
                fenn.text(active.path.name, size="title", tooltip=active.path.name),
            ], align="center"),
        ]
        if active.needs_office:
            details.extend([
                fenn.text("Office conversion needs LibreOffice. Setup runs through Windows Package Manager.",
                          color="dim", wrap=True),
                fenn.row([
                    fenn.button("install-office", label="Download requirements",
                                icon="download-simple", primary=True),
                    fenn.button("check-office", label="Check again", icon="arrow-clockwise"),
                ]),
            ])
            if self.setup_error:
                details.extend([
                    fenn.text(self.setup_error, color="orange", wrap=True),
                    fenn.button("manual-office", label="Open LibreOffice download"),
                ])
        elif active.problem:
            details.append(fenn.text(active.problem, color="orange", wrap=True))
        else:
            details.append(fenn.text("Output format", size="small", color="dim"))
            details.append(fenn.grid(min(4, len(active.targets)), [
                fenn.button(
                    f"target:{active.id}:{target.extension}", label=target.label,
                    primary=(active.target == target), width=0,
                )
                for target in active.targets
            ], gap=5))
            if active.target and any(
                file.id != active.id and active.target.extension in {t.extension for t in file.targets}
                and (not file.target or file.target.extension != active.target.extension)
                for file in self.pending.values()
            ):
                details.append(fenn.button(f"apply:{active.id}", label="Apply to compatible files"))
        controls = [
            fenn.text(f"Queue · {len(self.pending)} files", bold=True),
            fenn.spacer(),
        ]
        if ready:
            controls.append(fenn.button("convert", label=f"Convert {ready}", primary=True))
        controls.append(fenn.button("clear", label="Clear queue"))
        files = fenn.list_view([
            fenn.item(
                file.id, file.path.name, subtitle=file.family or file.problem,
                trailing=file.target.label if file.target else
                ("Setup needed" if file.needs_office else None),
                selected=file.id == self.selected,
                icon="warning-circle" if file.problem else FILE_ICONS.get(file.family, "files"),
            )
            for file in self.pending.values()
        ])
        return [fenn.card(details, padding=10, gap=7), fenn.row(controls, align="center"), files]

    def on_layout(self, message):
        if message.get("target") == "tile":
            with self.lock:
                self.draw()

    def on_page_open(self, _):
        with self.lock:
            if not self.busy:
                self.refresh_office()
                self.draw()

    def shutdown(self, _):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=0.28)

    def start(self, action, worker, files):
        self.busy = action
        self.draw()
        self.worker = threading.Thread(target=worker, args=(files,), daemon=True)
        self.worker.start()

    def add_files(self, message):
        with self.lock:
            if self.busy:
                self.notice = "Wait for the current operation to finish, then drop more files."
                self.draw()
                return
            self.notice = ""
            batch = []
            seen = {file.path for file in self.pending.values()}
            for raw in message.get("paths", []):
                path = Path(raw)
                if not path.is_absolute() or path in seen:
                    continue
                if len(seen) == MAX_BATCH:
                    self.notice = f"Up to {MAX_BATCH} files per batch."
                    break
                seen.add(path)
                self.next_id += 1
                batch.append(File(f"file:{self.next_id}", path))
            if batch:
                self.start("inspect", self.inspect_batch, batch)
            else:
                self.draw()

    def inspect_batch(self, files):
        for file in files:
            if self.stopping.is_set():
                return
            self.inspect_file(file)
        with self.lock:
            if self.stopping.is_set():
                return
            self.pending.update((file.id, file) for file in files)
            if self.selected is None:
                self.selected = next((file.id for file in files if file.targets), files[0].id)
            self.busy = ""
            self.draw()

    def inspect_file(self, file):
        file.problem = ""
        try:
            file.family, file.targets, file.engine = conversion.inspect(file.path, self.stopping)
            if not file.targets and not file.needs_office:
                file.problem = "No compatible output is available."
        except Exception as error:
            file.family, file.targets, file.engine = "", (), None
            file.problem = explain(error)

    def refresh_office(self):
        waiting = [file for file in self.pending.values() if file.needs_office]
        if not waiting or not conversion.available_office():
            return False
        for file in waiting:
            self.inspect_file(file)
        self.setup_error = ""
        return True

    def setup_office(self, _):
        problem = ""
        try:
            conversion.install_office(self.stopping)
        except (OSError, ValueError) as error:
            problem = explain(error)
        with self.lock:
            if self.stopping.is_set():
                return
            if not self.refresh_office():
                self.setup_error = problem or "LibreOffice wasn’t detected. Try checking again."
            self.busy = ""
            self.draw()

    def on_event(self, event):
        if event.get("kind") != "click":
            return
        control = event.get("id", "")
        with self.lock:
            if self.busy:
                return
            active = self.pending.get(self.selected)
            if control in {"install-office", "check-office", "manual-office"}:
                if not active or not active.needs_office:
                    return
                if self.refresh_office():
                    self.draw()
                elif control == "install-office":
                    self.setup_error = ""
                    self.start("install", self.setup_office, None)
                elif control == "manual-office" and self.setup_error:
                    self.app.open(conversion.OFFICE_DOWNLOAD)
                else:
                    self.setup_error = "LibreOffice wasn’t detected. Finish setup, then check again."
                    self.draw()
                return
            if control == "convert":
                ready = [file for file in self.pending.values() if file.target]
                if not ready:
                    return
                for file in ready:
                    del self.pending[file.id]
                if self.selected not in self.pending:
                    self.selected = next(iter(self.pending), None)
                self.results.clear()
                self.total = len(ready)
                self.notice = ""
                self.start("convert", self.convert_batch, ready)
                return
            if control == "clear":
                self.pending.clear()
                self.selected = None
                self.notice = ""
            elif control == "folder":
                first = next((path for path, _ in self.results.values() if path is not None), None)
                if first is not None:
                    self.open_folder(first)
                return
            elif control in self.results:
                path, _ = self.results[control]
                if path is not None:
                    self.open_folder(path)
                return
            elif control in self.pending:
                self.selected = control
            elif self.selected:
                self.set_target(control, self.pending[self.selected])
            self.draw()

    def set_target(self, control, active):
        prefix = f"target:{active.id}:"
        if control.startswith(prefix):
            extension = control[len(prefix):]
            for target in active.targets:
                if target.extension == extension:
                    active.target = target
                    break
        elif control == f"apply:{active.id}" and active.target:
            for file in self.pending.values():
                for target in file.targets:
                    if target.extension == active.target.extension:
                        file.target = target
                        break

    def open_folder(self, path):
        self.app.open(str(path if path.is_dir() else path.parent))

    def convert_batch(self, files):
        for index, file in enumerate(files, 1):
            if self.stopping.is_set():
                return
            result_id = f"result:{file.id}"
            path = None
            try:
                path, size = conversion.convert(
                    file.path, file.family, file.target, file.engine, self.stopping,
                )
                item = fenn.item(
                    result_id, path.name, subtitle="Click to open its folder",
                    trailing=display_size(size), icon="check-circle",
                )
            except Exception as error:
                item = fenn.item(result_id, file.path.name, subtitle=explain(error), icon="warning-circle")
            with self.lock:
                if self.stopping.is_set():
                    return
                self.results[result_id] = (path, item)
                self.busy = "convert" if index < len(files) else ""
                self.draw()


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    plugin = Converter()
    plugin.draw()
    plugin.app.run()
