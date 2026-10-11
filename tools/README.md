# tools

Utility scripts that live in this project and run from the local virtualenv.

## Available tools

| Tool | Purpose |
|------|---------|
| `mdtopdf.py` | Merge the markdown files of a directory into a single PDF document. Files are sorted by filename and merged in order (YAML front matter stripped, Unicode/emoji sanitized, page break between documents). |

### Usage

```bash
# from the project root, using the project venv
.venv/bin/python tools/mdtopdf.py --directory /path/to/folder --output-format pdf

# options
#   --directory DIR          folder containing the .md files (required)
#   --output-format pdf|html output format (default: pdf)
#   --output NAME            output filename without extension (default: folder name)
#   --no-sort                do not sort files by name
```

Conversion strategy: markdown → PDF via `pandoc` + a LaTeX engine (`xelatex`,
then `lualatex`, then `pdflatex`). If every LaTeX engine fails, the script
falls back to markdown → HTML (`pandoc`) → PDF (Playwright/Chromium).

## Python dependencies

All Python dependencies are already declared in the project
[`requirements.txt`](../requirements.txt) (`playwright>=1.45`). Install them
into the venv:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

`playwright` is only needed for the HTML→PDF fallback path; after installing
it, download the browser once:

```bash
playwright install chromium
```

## OS-level dependencies

`pandoc` and the LaTeX engines are **system binaries** called through
`subprocess` — they cannot be installed with pip and must be provided by the
operating system. The script also expects Unicode fonts referenced by pandoc
variables: **Noto Serif** (main), **Noto Sans** (sans), **Noto Sans Mono**
(mono).

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y \
  pandoc \
  texlive-xetex \
  texlive-luatex \
  texlive-latex-recommended \
  texlive-latex-extra \
  fonts-noto-core \
  fonts-noto-mono

# Python side (venv) + Chromium for the HTML fallback
pip install -r requirements.txt
playwright install --with-deps chromium
```

Notes:
- `texlive-xetex` provides `xelatex`, `texlive-luatex` provides `lualatex`;
  `pdflatex` comes from `texlive-latex-base` (pulled in as a dependency).
- `fonts-noto-core` provides Noto Serif/Sans, `fonts-noto-mono` provides
  Noto Sans Mono. Install `fonts-noto` for the full family (incl. CJK).
- `playwright install --with-deps chromium` also installs the system
  libraries Chromium needs.

### Manjaro / Arch Linux

```bash
sudo pacman -S --needed \
  pandoc \
  texlive-basic \
  texlive-latex \
  texlive-latexextra \
  texlive-fontsrecommended \
  texlive-xetex \
  texlive-luatex \
  noto-fonts

# Python side (venv) + Chromium for the HTML fallback
pip install -r requirements.txt
playwright install chromium
```

Notes:
- On Arch packaging, `texlive-xetex` provides `xelatex` and `texlive-luatex`
  provides `lualatex`; `pdflatex` is in `texlive-latex`.
- `noto-fonts` provides Noto Serif, Noto Sans and Noto Sans Mono. Add
  `noto-fonts-extra` for the complete family.
- If Chromium dependencies are missing, install the `chromium` package or run
  `sudo pacman -S $(pacman -Qq | grep -E '^(nss|alsa-lib|atk|cups|libxkbcommon|libpulse|mesa|cairo|pango)$')`
  — or simply install `chromium` from the repos and let Playwright use its own
  bundled build via `playwright install chromium`.

### Windows (not tested)

The script has **not been tested on Windows**. The expected setup is:

```powershell
# pandoc
winget install --id JohnMacFarlane.Pandoc

# LaTeX distribution providing xelatex / lualatex / pdflatex
# (MiKTeX is the common Windows choice; full TeX Live also works)
winget install --id MiKTeX.MiKTeX

# Noto fonts (or download from https://fonts.google.com/noto and install)
winget install --id Google.NotoSans --exact   # if available, otherwise manual install

# Python side (venv) + Chromium for the HTML fallback
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

Caveats on Windows:
- Restart the terminal (or re-open it) after installing pandoc/MiKTeX so the
  updated `PATH` is picked up — the script calls `pandoc`, `xelatex`, etc. by
  name through `subprocess`.
- MiKTeX may prompt to install missing LaTeX packages on first run; enable
  "install missing packages on the fly" or pre-install them, otherwise the
  first conversion can fail and the script silently falls back to HTML.
- The Noto fonts must be installed for the current user or all users; if they
  are missing, xelatex fails and the LaTeX path is abandoned in favor of the
  Chromium fallback.
- The HTML fallback serves a temporary local HTTP server on `127.0.0.1`; a
  firewall prompt may appear — allow loopback only.
