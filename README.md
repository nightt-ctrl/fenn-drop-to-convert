# Drop-to-Convert for Fenn

Batch-convert images from the Windows notch.

## Install

1. Install [Python 3.10 or newer](https://www.python.org/downloads/windows/) for Windows if needed. Use a version with a Pillow wheel, such as Python 3.12 x64. Make `python` available on PATH, or pass the full path to `python.exe` as the first argument to the installer.
2. Download this repository as a ZIP from **Code → Download ZIP** and extract it. Open PowerShell in the extracted folder and run `.\install.cmd`.
3. Turn on **Plugin dev mode** in Fenn Settings. Open the notch grid and select **Convert**. Fenn's [development guide](https://fenn.click/docs/develop) covers building a compatible host if your Fenn build requires it.

The installer downloads Pillow into a virtual environment under `%APPDATA%\Fenn\plugin-data\drop-to-convert` and installs the plugin under `%APPDATA%\Fenn\plugins\drop-to-convert`. To update, run the installer from the new checkout. To uninstall, remove both folders.

## Use

1. Open the Convert tile and drop images onto the notch while the plugin page is open.
2. Choose **PNG**, **JPEG**, or **WebP**, then click **Convert**.
3. Check the output sizes and any errors in the results. Click an output row to open its folder. **Open folder** opens the folder of the first successful result.

Outputs appear beside each input as `name-converted.ext`, with a numeric suffix if that name already exists. A batch can contain up to 100 files. Inputs can be single-frame PNG, JPEG, WebP, BMP, GIF, TIFF, or ICO images up to 40 megapixels. Conversion applies EXIF orientation and strips embedded metadata and color profiles. PNG and WebP keep transparency. JPEG flattens it against white. JPEG and WebP use lossy quality settings of 90 and 85, respectively.

Conversion runs locally. The plugin makes no network requests.

See the [Fenn plugin docs](https://fenn.click/docs) for the host protocol and `%APPDATA%\Fenn\fenn.log` for diagnostics.
