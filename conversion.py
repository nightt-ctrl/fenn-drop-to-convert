"""Discover valid destinations and convert into a staging folder beside the source."""

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import warnings
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import imageio_ffmpeg
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError


@dataclass(frozen=True)
class Target:
    label: str
    extension: str
    arguments: tuple[str, ...] = ()


IMAGE_TARGETS = (
    Target("PNG", "png"), Target("JPEG", "jpg"), Target("WebP", "webp"),
    Target("AVIF", "avif"), Target("BMP", "bmp"), Target("GIF", "gif"),
    Target("TIFF", "tiff"), Target("ICO", "ico"), Target("PDF", "pdf"),
    Target("JPEG 2000", "jp2"), Target("TGA", "tga"), Target("PPM", "ppm"),
)
IMAGE_ENCODERS = {"jpg": "JPEG", "tiff": "TIFF", "jp2": "JPEG2000"}
IMAGE_READERS = (
    "AVIF", "BMP", "DDS", "DIB", "GIF", "ICNS", "ICO", "JPEG", "JPEG2000",
    "MPO", "PCX", "PNG", "PPM", "QOI", "SGI", "TGA", "TIFF", "WEBP", "XBM",
)
AUDIO_TARGETS = (
    Target("MP3", "mp3", ("-c:a", "libmp3lame", "-q:a", "2")),
    Target("WAV", "wav", ("-c:a", "pcm_s16le")),
    Target("FLAC", "flac", ("-c:a", "flac")),
    Target("M4A", "m4a", ("-c:a", "aac", "-b:a", "192k")),
    Target("OGG", "ogg", ("-c:a", "libvorbis", "-q:a", "5")),
    Target("Opus", "opus", ("-c:a", "libopus", "-b:a", "128k")),
    Target("AAC", "aac", ("-c:a", "aac", "-b:a", "192k")),
    Target("AIFF", "aiff", ("-c:a", "pcm_s16be")),
    Target("WMA", "wma", ("-c:a", "wmav2", "-b:a", "192k")),
)
H264 = ("-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-c:a", "aac")
VIDEO_TARGETS = (
    Target("MP4", "mp4", H264 + ("-movflags", "+faststart")),
    Target("WebM", "webm", ("-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-c:a", "libopus")),
    Target("MKV", "mkv", H264),
    Target("MOV", "mov", H264),
    Target("AVI", "avi", ("-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame")),
    Target("GIF", "gif", ("-an", "-vf", "fps=12,scale='min(640,iw)':-1", "-loop", "0")),
)
MEDIA_INPUTS = set((
    "3g2 3gp aac ac3 aif aiff alac amr ape asf avi caf dv f4v flac flv m2ts m4a m4v "
    "mka mkv mov mp2 mp3 mp4 mpeg mpg mts mxf oga ogg ogv opus ra rm ts vob wav webm wma wmv wv"
).split())
OFFICE = {
    "Document": (
        "doc docx odt rtf txt html htm fodt ott sxw wpd wps abw pages",
        (("PDF", "pdf", "writer_pdf_Export"), ("DOCX", "docx", "Office Open XML Text"),
         ("ODT", "odt", "writer8"), ("DOC", "doc", "MS Word 97"),
         ("RTF", "rtf", "Rich Text Format"), ("TXT", "txt", "Text (encoded):UTF8"),
         ("HTML", "html", "XHTML Writer File:UTF8"), ("EPUB", "epub", "EPUB")),
    ),
    "Spreadsheet": (
        "xls xlsx xlsb ods csv tsv tab fods ots sxc numbers",
        (("PDF", "pdf", "calc_pdf_Export"), ("XLSX", "xlsx", "Calc MS Excel 2007 XML"),
         ("ODS", "ods", "calc8"), ("XLS", "xls", "MS Excel 97"),
         ("CSV", "csv", "Text - txt - csv (StarCalc):44,34,76,1"),
         ("TSV", "tsv", "Text - txt - csv (StarCalc):9,34,76,1")),
    ),
    "Presentation": (
        "ppt pptx odp fodp otp sxi pps ppsx key",
        (("PDF", "pdf", "impress_pdf_Export"),
         ("PPTX", "pptx", "Impress MS PowerPoint 2007 XML"),
         ("ODP", "odp", "impress8"), ("PPT", "ppt", "MS PowerPoint 97")),
    ),
}
OFFICE_INPUTS = {
    extension: (family, tuple(Target(label, ext, (filter_name,)) for label, ext, filter_name in outputs))
    for family, (extensions, outputs) in OFFICE.items() for extension in extensions.split()
}
PDF_TARGETS = tuple(t for t in IMAGE_TARGETS if t.extension in ("png", "jpg", "webp")) + (
    Target("TXT", "txt"),
)
ARCHIVE_TARGETS = (
    Target("ZIP", "zip"), Target("TAR", "tar"), Target("TAR.GZ", "tar.gz"),
    Target("TAR.BZ2", "tar.bz2"), Target("TAR.XZ", "tar.xz"),
)
TAR_MODES = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}
ARCHIVE_ALIASES = {"tgz": "tar.gz", "tbz": "tar.bz2", "tbz2": "tar.bz2", "txz": "tar.xz"}
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
Image.init()
AVAILABLE_IMAGE_READERS = tuple(name for name in IMAGE_READERS if name in Image.OPEN)


def available_office():
    override = os.environ.get("FENN_CONVERT_SOFFICE")
    candidates = [
        override, shutil.which("soffice.com"), shutil.which("soffice.exe"),
        *[Path(root) / "LibreOffice/program/soffice.com" for root in (
            os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
            os.environ.get("ProgramFiles(x86)"),
        ) if root],
    ]
    return next((str(Path(path).resolve()) for path in candidates if path and Path(path).is_file()), None)


def run_tool(command, stopping, timeout):
    with subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ) as process:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not stopping.is_set():
            try:
                data, _ = process.communicate(timeout=0.1)
                return process.returncode, data.decode("utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                continue
        process.kill()
        process.communicate()
        raise ValueError("Conversion cancelled." if stopping.is_set() else "The converter timed out.")


def ffmpeg_input(ffmpeg, path):
    return [ffmpeg, "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(path)]


def image_format(target):
    return IMAGE_ENCODERS.get(target.extension, target.extension.upper())


def inspect(source, stopping):
    if not source.is_file():
        raise ValueError("Drop a file rather than a folder.")
    ext = source.suffix.lower().lstrip(".")
    archive_ext = ARCHIVE_ALIASES.get(ext, ext)
    if source.name.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        archive_ext = f"tar.{ext}"
    if archive_ext == "zip" or archive_ext in TAR_MODES:
        return "Archive", tuple(t for t in ARCHIVE_TARGETS if t.extension != archive_ext), archive_ext
    if ext == "pdf":
        return "PDF", PDF_TARGETS, None
    if ext in OFFICE_INPUTS:
        family, targets = OFFICE_INPUTS[ext]
        office = available_office()
        if not office:
            raise ValueError(f"{family} conversion needs LibreOffice. See the README for setup.")
        return family, tuple(t for t in targets if t.extension != {"htm": "html", "tab": "tsv"}.get(ext, ext)), office

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source, formats=AVAILABLE_IMAGE_READERS) as image:
                animated = getattr(image, "n_frames", 1) > 1
                if animated and image.format not in {"GIF", "AVIF", "PNG", "WEBP"}:
                    raise ValueError("Multi-page images are unsupported.")
                options = tuple(
                    t for t in IMAGE_TARGETS
                    if image_format(t) in Image.SAVE
                    and (not animated or t.extension in {"png", "gif", "webp"})
                )
                # Allow a same-format output as a new copy, useful for batch normalization.
                return "Animated image" if animated else "Image", options, None
    except UnidentifiedImageError:
        pass

    if ext not in MEDIA_INPUTS:
        raise ValueError("Unsupported or unreadable file.")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    _, details = run_tool(ffmpeg_input(ffmpeg, source), stopping, 20)
    streams = re.findall(r"Stream #\d+:\d+[^\n]*?: (Audio|Video):([^\n]*)", details)
    audio = any(kind == "Audio" for kind, _ in streams)
    video = any(kind == "Video" and "attached pic" not in description for kind, description in streams)
    if not audio and not video:
        raise ValueError("FFmpeg found no playable audio or video streams.")
    targets = (VIDEO_TARGETS if video else ()) + (AUDIO_TARGETS if audio else ())
    return "Video" if video else "Audio", targets, ffmpeg


def save_image(image, output, target):
    pixels = image.convert("RGBA")
    options = {}
    if target.extension in {"jpg", "pdf", "ppm"}:
        background = Image.new("RGB", pixels.size, "white")
        background.paste(pixels, mask=pixels.getchannel("A"))
        pixels = background
    if target.extension == "jpg":
        options = {"quality": 90}
    elif target.extension == "webp":
        options = {"quality": 85}
    elif target.extension == "ico":
        pixels.thumbnail((256, 256), Image.Resampling.LANCZOS)
        options = {"sizes": [pixels.size]}
    pixels.info.clear()
    pixels.save(output, format=image_format(target), **options)


def convert_image(source, output, target, stopping):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(source, formats=AVAILABLE_IMAGE_READERS) as image:
            frames = getattr(image, "n_frames", 1)
            if frames == 1:
                save_image(ImageOps.exif_transpose(image), output, target)
                return
            if target.extension not in {"png", "gif", "webp"}:
                raise ValueError("Choose PNG, GIF, or WebP to keep animation.")
            if frames * image.width * image.height > MAX_PIXELS:
                raise ValueError("Animation exceeds 40 million pixels across its frames.")
            pictures, durations = [], []
            loop = image.info.get("loop", 0)
            first_frame = int(image.info.get("default_image", False))
            for index in range(first_frame, frames):
                if stopping.is_set():
                    raise ValueError("Conversion cancelled.")
                image.seek(index)
                frame = ImageOps.exif_transpose(image).convert("RGBA")
                durations.append(int(image.info.get("duration", 100)))
                frame.info.clear()
                pictures.append(frame)
            pictures[0].save(
                output, format=image_format(target), save_all=True,
                append_images=pictures[1:], duration=durations, loop=loop,
            )


def convert_pdf(source, output, target, stopping):
    with pdfium.PdfDocument(source) as document:
        if target.extension == "txt":
            has_text = False
            with output.open("w", encoding="utf-8", newline="\n") as file:
                for index, page in enumerate(document):
                    if stopping.is_set():
                        raise ValueError("Conversion cancelled.")
                    if index:
                        file.write("\n\n")
                    with closing(page), closing(page.get_textpage()) as text_page:
                        text = text_page.get_text_bounded().replace("\r\n", "\n")
                        file.write(text)
                        has_text = has_text or bool(text.strip())
            if not has_text:
                raise ValueError("No text layer found. Scanned PDFs need OCR.")
            return output

        output = output.with_suffix("")
        output.mkdir()
        for index, page in enumerate(document, 1):
            if stopping.is_set():
                raise ValueError("Conversion cancelled.")
            with closing(page):
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("Invalid PDF page dimensions.")
                scale = min(2, (MAX_PIXELS / (width * height)) ** 0.5 * 0.99)
                with closing(page.render(scale=scale)) as bitmap:
                    save_image(bitmap.to_pil(), output / f"page-{index:04d}.{target.extension}", target)
        return output


def convert_office(source, output, target, office, stopping):
    profile = output.parent / "profile"
    export = output.parent / "export"
    export.mkdir()
    user = profile / "user"
    user.mkdir(parents=True)
    (user / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
        '</item></oor:items>', encoding="utf-8",
    )
    command = [office, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore"]
    input_extension = source.suffix.lower()
    if input_extension in {".csv", ".tsv", ".tab"}:
        separator = 44 if input_extension == ".csv" else 9
        command.append(f"--infilter=Text - txt - csv (StarCalc):{separator},34,76,1")
    code, details = run_tool(command + [
        "--convert-to", f"{target.extension}:{target.arguments[0]}",
        "--outdir", str(export), str(source),
    ], stopping, 180)
    generated = export / f"{source.stem}.{target.extension}"
    if code or not generated.is_file():
        raise ValueError("LibreOffice could not export this file. " + last_line(details))
    if target.extension == "html" and any(path != generated for path in export.iterdir()):
        return export
    return generated


def last_line(details):
    return next((line.strip()[:180] for line in reversed(details.splitlines()) if line.strip()), "")


def convert_media(source, output, target, ffmpeg, stopping):
    if target in AUDIO_TARGETS:
        mapping = ["-map", "0:a:0", "-vn", "-ac", "2"]
    else:
        mapping = ["-map", "0:V:0", "-map", "0:a:0?"]
        if target.extension != "gif":
            mapping += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-ac", "2"]
    code, details = run_tool(ffmpeg_input(ffmpeg, source) + [
        *mapping, "-map_metadata", "-1", "-map_chapters", "-1", *target.arguments,
        "-y", str(output),
    ], stopping, 3600)
    if code:
        raise ValueError("FFmpeg could not export this file. " + last_line(details))


def archive_name(raw):
    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts):
        raise ValueError("The archive contains an unsafe member path.")
    return path.as_posix()


def archive_entries(archive):
    if isinstance(archive, zipfile.ZipFile):
        for member in archive.infolist():
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("The archive contains a symbolic link.")
            yield member.filename, member.file_size, member.is_dir(), member
    else:
        for member in archive:
            if not (member.isfile() or member.isdir()):
                raise ValueError("The archive contains a link or special file.")
            yield member.name, member.size, member.isdir(), member


def convert_archive(source, output, target, source_ext, stopping):
    original = zipfile.ZipFile(source) if source_ext == "zip" else tarfile.open(source, "r:*")
    with original:
        destination = (
            zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED)
            if target.extension == "zip" else tarfile.open(output, TAR_MODES[target.extension])
        )
        with destination:
            seen = set()
            for raw, size, is_dir, member in archive_entries(original):
                if stopping.is_set():
                    raise ValueError("Conversion cancelled.")
                name = archive_name(raw)
                if is_dir and name == ".":
                    continue
                if name.casefold() in seen:
                    raise ValueError("The archive contains duplicate member paths.")
                seen.add(name.casefold())
                tar_info = tarfile.TarInfo(name)
                tar_info.size = size
                if is_dir:
                    tar_info.type = tarfile.DIRTYPE
                    tar_info.mode = 0o755
                    if target.extension == "zip":
                        destination.writestr(name + "/", b"")
                    else:
                        destination.addfile(tar_info)
                    continue
                read = original.open(member) if source_ext == "zip" else original.extractfile(member)
                with read:
                    if target.extension == "zip":
                        with destination.open(name, "w", force_zip64=size >= 2**31) as write:
                            shutil.copyfileobj(read, write, length=1024 * 1024)
                    else:
                        destination.addfile(tar_info, read)


def convert(source, family, target, engine, stopping):
    with tempfile.TemporaryDirectory(prefix=".drop-to-convert-", dir=source.parent) as scratch:
        output = Path(scratch) / f"result.{target.extension}"
        if family in OFFICE:
            output = convert_office(source, output, target, engine, stopping)
        elif family == "PDF":
            output = convert_pdf(source, output, target, stopping)
        elif family in {"Video", "Audio"}:
            convert_media(source, output, target, engine, stopping)
        elif family == "Archive":
            convert_archive(source, output, target, engine, stopping)
        else:
            convert_image(source, output, target, stopping)
        if stopping.is_set():
            raise ValueError("Conversion cancelled.")
        is_folder = output.is_dir()
        size = (
            sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
            if is_folder else output.stat().st_size
        )
        if not size:
            raise ValueError("The converter produced an empty output.")
        extension = f".{target.extension}"
        if is_folder:
            extension = f"-{target.extension}-{'pages' if family == 'PDF' else 'files'}"
        stem = source.stem
        if family == "Archive" and source.name.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
            stem = Path(stem).stem
        for number in range(1, 10001):
            suffix = "" if number == 1 else f"-{number}"
            destination = source.with_name(f"{stem}-converted{suffix}{extension}")
            try:
                # On Windows, rename atomically publishes without replacing an existing output.
                output.rename(destination)
                return destination, size
            except FileExistsError:
                continue
        raise ValueError("Too many output files with this name.")
