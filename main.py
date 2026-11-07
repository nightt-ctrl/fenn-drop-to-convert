"""Fenn tile and mixed-format conversion queue."""

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

import conversion
import fenn


MAX_BATCH = 100


@dataclass
class File:
    id: str
    path: Path
    family: str = ""
    targets: tuple = ()
    engine: str | None = None
    problem: str = ""
    target: conversion.Target | None = None


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
        self.next_id = 0
        self.worker = None
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.app.on_message("files")(self.add_files)
        self.app.on_message("layout")(self.on_layout)
        self.app.on_message("event")(self.on_event)
        self.app.on_message("shutdown")(self.shutdown)

    def draw(self):
        icon = fenn.icon("arrows-left-right", color="accent", size=18)
        if self.app.tile_size == "small":
            self.app.tile(fenn.column([icon], align="center", justify="center"))
        else:
            label = {"inspect": "Checking", "convert": "Converting"}.get(self.busy, "Convert")
            self.app.tile(fenn.row([icon, fenn.text(label)], align="center", gap=5))

        children = [
            fenn.text("Drop files onto the notch", size="title"),
            fenn.text("Choose an output for each file. Copies go beside the originals.", color="dim"),
        ]
        if self.busy == "inspect":
            children.append(fenn.text("Checking file types…"))
        elif self.busy == "convert":
            children.extend([
                fenn.text(f"Converting {len(self.results)} of {self.total}"),
                fenn.progress(len(self.results) / self.total),
            ])
        elif self.pending:
            children.extend(self.queue_view())

        if self.notice:
            children.append(fenn.text(self.notice, color="orange", wrap=True))
        if self.results:
            if self.busy != "convert":
                count = sum(path is not None for path, _ in self.results.values())
                children.append(fenn.text(f"{count} converted, {self.total - count} failed", bold=True))
                if count:
                    children.append(fenn.button("folder", label="Open folder", icon="folder-open"))
            children.append(fenn.list_view([item for _, item in self.results.values()]))
        self.app.page(fenn.column(children, scroll=True, gap=8))

    def queue_view(self):
        active = self.pending[self.selected]
        ready = sum(file.target is not None for file in self.pending.values())
        rows = [fenn.text(active.path.name, bold=True, tooltip=active.path.name)]
        if active.problem:
            rows.append(fenn.text(active.problem, color="orange", wrap=True))
        else:
            for start in range(0, len(active.targets), 4):
                rows.append(fenn.row([
                    fenn.button(
                        f"target:{active.id}:{target.extension}",
                        label=target.label, primary=(active.target == target),
                    )
                    for target in active.targets[start:start + 4]
                ]))
            if active.target and any(
                file.id != active.id and active.target.extension in {t.extension for t in file.targets}
                and (not file.target or file.target.extension != active.target.extension)
                for file in self.pending.values()
            ):
                rows.append(fenn.button(f"apply:{active.id}", label="Apply to compatible files"))
        controls = [fenn.button("clear", label="Clear queue")]
        if ready:
            controls.insert(0, fenn.button("convert", label=f"Convert {ready}", primary=True))
        rows.append(fenn.row(controls))
        rows.append(fenn.list_view([
            fenn.item(
                file.id, file.path.name, subtitle=file.problem or file.family,
                trailing=file.target.label if file.target else None,
                selected=file.id == self.selected,
                icon="warning-circle" if file.problem else "file-image",
            )
            for file in self.pending.values()
        ]))
        return rows

    def on_layout(self, message):
        if message.get("target") == "tile":
            with self.lock:
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
            try:
                file.family, file.targets, file.engine = conversion.inspect(file.path, self.stopping)
                if not file.targets:
                    file.problem = "No compatible output is available."
            except Exception as error:
                file.problem = explain(error)
        with self.lock:
            if self.stopping.is_set():
                return
            self.pending.update((file.id, file) for file in files)
            if self.selected is None:
                self.selected = next((file.id for file in files if file.targets), files[0].id)
            self.busy = ""
            self.draw()

    def on_event(self, event):
        if event.get("kind") != "click":
            return
        control = event.get("id", "")
        with self.lock:
            if self.busy:
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
