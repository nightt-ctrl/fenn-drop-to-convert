# Drop-to-Convert for Fenn

Drop files into the Windows notch and pick an output based on the file type. You can mix different kinds of files in the same batch.

## Install or update

1. Install [Python 3.11 or newer](https://www.python.org/downloads/windows/) if needed. Python 3.12 x64 is a tested option. Make `python` available on PATH, or pass the full path to `python.exe` as the first argument to the installer.
2. Download the repository using **Code → Download ZIP** and extract it. Run `.\install.cmd` from the extracted folder. The installer sets up Pillow, PDFium, and FFmpeg in the plugin's private Python environment.
3. Enable **Plugin dev mode** in Fenn Settings and open **Convert** from the notch grid. The [Fenn development guide](https://fenn.click/docs/develop) covers building a compatible host if your installed build requires it.

Office conversions use LibreOffice. If it is missing, select a queued Office file and click **Download requirements**. The plugin uses Windows Package Manager to download and install LibreOffice. Follow any setup prompts. After setup, the format choices appear automatically for the files already in your queue.

If Windows Package Manager is unavailable, install [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) and click **Check again**. For a custom installation, set `FENN_CONVERT_SOFFICE` to the full path to `soffice.com` before starting Fenn.

The installer updates the existing plugin in `%APPDATA%\Fenn\plugins\drop-to-convert` and keeps its environment in `%APPDATA%\Fenn\plugin-data\drop-to-convert`. To uninstall, remove both folders.

## Use

1. Open **Convert** and drop up to 100 files onto the notch.
2. Click a file in the queue and choose one of its output formats. **Apply to compatible files** applies that format to every queued file that can produce it. Choose other formats for the remaining files if needed.
3. Click **Convert** to run the configured jobs. Files without a selected format stay in the queue. Click a result to open its folder.

Each output is saved beside the original as `name-converted.ext`. If the name already exists, the plugin adds a numeric suffix. PDF page images are saved in their own folder. The plugin does not upload files.

## Supported conversions

| Input | Output choices |
| --- | --- |
| Images such as PNG, JPEG, WebP, AVIF, BMP, GIF, TIFF, and ICO | PNG, JPEG, WebP, AVIF, BMP, GIF, TIFF, ICO, PDF, JPEG 2000, TGA, and PPM, depending on available Pillow encoders |
| Animated GIF, WebP, AVIF, or PNG | Animated PNG, GIF, or WebP |
| PDF | PNG, JPEG, or WebP for every page, or TXT from the document's text layer |
| Word and text documents such as DOCX, DOC, ODT, RTF, TXT, and HTML | PDF, DOCX, DOC, ODT, RTF, TXT, HTML, and EPUB with LibreOffice |
| Spreadsheets such as XLSX, XLS, XLSB, ODS, CSV, and TSV | PDF, XLSX, XLS, ODS, CSV, and TSV with LibreOffice |
| Presentations such as PPTX, PPT, and ODP | PDF, PPTX, PPT, and ODP with LibreOffice |
| Audio such as MP3, WAV, FLAC, M4A, AAC, OGG, Opus, and WMA | MP3, WAV, FLAC, M4A, AAC, OGG, Opus, AIFF, and WMA |
| Video such as MP4, WebM, MKV, MOV, AVI, and WMV | MP4, WebM, MKV, MOV, AVI, GIF, and the audio formats above when the file contains an audio track |
| ZIP, TAR, TAR.GZ, TAR.BZ2, and TAR.XZ archives | Repack into any of the other listed archive formats |

Image conversion applies EXIF orientation and removes metadata. JPEG, PDF, and PPM flatten transparency against white. The image limit is 40 megapixels, including all frames combined for animations. PDF text export requires selectable text. CSV and TSV exports use the first sheet. Media conversion uses the first playable video stream and first audio stream. Archive repacking supports ordinary files and folders and rejects links and unsafe paths.

Exact compatibility depends on the input and codec. A damaged, encrypted, or unsupported file gets a per-file error. See the [LibreOffice filters](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html) and [Pillow formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) for backend details.
