"""Fenn's Drop-to-Convert tile and image conversion worker."""

import os
import sys
import tempfile
import threading
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

import fenn


FORMATS = ("PNG", "JPEG", "WebP")
EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WebP": ".webp"}
INPUT_FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF", "ICO")
MAX_BATCH = 100
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def convert(source, target):
    if not source.is_file():
        raise ValueError("Drop an image file.")

    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source, formats=INPUT_FORMATS) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated and multi-page images are unsupported.")
            oriented = ImageOps.exif_transpose(image)
            pixels = oriented.convert("RGBA")

    options = {}
    if target == "JPEG":
        background = Image.new("RGB", pixels.size, "white")
        background.paste(pixels, mask=pixels.getchannel("A"))
        pixels = background
        options = {"quality": 90}
    elif target == "WebP":
        options = {"quality": 85}

    # Save pixels only. Embedded metadata and color profiles are discarded.
    pixels.info.clear()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=source.parent, prefix=".drop-to-convert-", suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            pixels.save(output, format=target.upper(), **options)
        size = temporary.stat().st_size
        for number in range(1, 10001):
            suffix = "" if number == 1 else f"-{number}"
            name = f"{source.stem}-converted{suffix}{EXTENSIONS[target]}"
            destination = source.with_name(name)
            try:
                # On Windows, rename publishes the finished file without replacing anything.
                temporary.rename(destination)
                return destination, size
            except FileExistsError:
                continue
        raise ValueError("Too many output files with this name.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def display_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class Converter:
    def __init__(self):
        self.app = fenn.Plugin()
        self.format_index = 0
        self.pending = []
        self.results = []
        self.total = 0
        self.busy = False
        self.notice = ""
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.generation = 0
        self.app.on_message("files")(self.add_files)
        self.app.on_message("layout")(self.on_layout)
        self.app.on_message("event")(self.on_event)
        self.app.on_message("shutdown")(lambda _: self.stopping.set())

    def draw(self):
        icon = fenn.icon("arrows-left-right", color="accent", size=18)
        if self.app.tile_size == "small":
            self.app.tile(fenn.column([icon], align="center", justify="center"))
        else:
            label = "Converting" if self.busy else "Convert"
            self.app.tile(fenn.row([icon, fenn.text(label)], align="center", gap=5))

        children = [
            fenn.text("Drop images onto the notch", size="title"),
            fenn.text("Converted copies go beside the originals.", color="dim"),
            fenn.chips("format", list(FORMATS), selected=self.format_index),
        ]
        if self.busy:
            children.extend([
                fenn.text(f"Converting {len(self.results)} of {self.total}"),
                fenn.progress(len(self.results) / self.total),
            ])
        elif self.pending:
            children.append(fenn.row([
                fenn.button("convert", label=f"Convert {len(self.pending)}", primary=True),
                fenn.button("clear", label="Clear"),
            ]))
        elif self.results:
            successes = [path for path, _ in self.results if path is not None]
            children.append(fenn.text(
                f"{len(successes)} converted, {self.total - len(successes)} failed",
                bold=True,
            ))
            if successes:
                children.append(fenn.button("folder", label="Open folder", icon="folder-open"))
        if self.notice:
            children.append(fenn.text(self.notice, color="orange", wrap=True))

        if self.pending:
            children.append(fenn.list_view([
                fenn.item(f"queued:{index}", path.name, icon="file-image")
                for index, path in enumerate(self.pending)
            ]))
        if self.results:
            children.append(fenn.list_view([item for _, item in self.results]))
        self.app.page(fenn.column(children, scroll=True, gap=8))

    def on_layout(self, message):
        if message.get("target") == "tile":
            with self.lock:
                self.draw()

    def add_files(self, message):
        with self.lock:
            if self.busy:
                self.notice = "Wait for this batch to finish, then drop more files."
            else:
                self.notice = ""
                self.results.clear()
                for raw in message.get("paths", []):
                    path = Path(raw)
                    if not path.is_absolute() or path in self.pending:
                        continue
                    if len(self.pending) == MAX_BATCH:
                        self.notice = f"Up to {MAX_BATCH} files per batch."
                        break
                    self.pending.append(path)
            self.draw()

    def on_event(self, event):
        control = event.get("id", "")
        kind = event.get("kind")
        with self.lock:
            if control == "format" and kind == "change":
                index = event.get("value", {}).get("index")
                if isinstance(index, int) and 0 <= index < len(FORMATS):
                    self.format_index = index
                    self.draw()
                return
            if self.busy or kind != "click":
                return
            if control == "convert" and self.pending:
                batch, self.pending = self.pending, []
                self.total = len(batch)
                self.results.clear()
                self.notice = ""
                self.busy = True
                self.generation += 1
                self.draw()
                threading.Thread(
                    target=self.convert_batch,
                    args=(batch, FORMATS[self.format_index], self.generation),
                    daemon=True,
                ).start()
            elif control == "clear":
                self.pending.clear()
                self.notice = ""
                self.draw()
            elif control == "folder":
                folder = next((path.parent for path, _ in self.results if path), None)
                if folder:
                    self.app.open(str(folder))
            elif control.startswith(f"result:{self.generation}:"):
                for path, item in self.results:
                    if path and item["id"] == control:
                        self.app.open(str(path.parent))
                        break

    def convert_batch(self, batch, target, generation):
        for index, source in enumerate(batch):
            if self.stopping.is_set():
                return
            result_id = f"result:{generation}:{index}"
            path = None
            try:
                path, size = convert(source, target)
            except (Image.DecompressionBombError, Image.DecompressionBombWarning):
                problem = "Image exceeds 40 megapixels."
            except UnidentifiedImageError:
                problem = "Unsupported or unreadable image."
            except PermissionError:
                problem = "Cannot read the file or write to its folder."
            except (OSError, ValueError, SyntaxError) as error:
                problem = str(error)
            except Exception as error:
                print(f"{type(error).__name__}: {error}", file=sys.stderr)
                problem = "Could not convert this image."

            if path is None:
                item = fenn.item(result_id, source.name, subtitle=problem, icon="warning-circle")
            else:
                item = fenn.item(
                    result_id, path.name, subtitle="Click to open its folder",
                    trailing=display_size(size), icon="check-circle",
                )
            with self.lock:
                if self.stopping.is_set():
                    return
                self.results.append((path, item))
                self.busy = index + 1 < len(batch)
                self.draw()


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    plugin = Converter()
    plugin.draw()
    plugin.app.run()
