#!/usr/bin/env python3
"""
actutopdf.py - Fusionner des fichiers markdown en un seul document PDF.

Utilisation:
    actutopdf.py --directory /chemin/du/dossier --output-format pdf

Les fichiers markdown du dossier sont triés par nom de fichier puis fusionnés
dans l'ordre pour créer un PDF.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path


# ---------------------------------------------------------------------------
# Nettoyage du markdown avant conversion
# ---------------------------------------------------------------------------

_EMOJI_REPLACEMENTS = {
    '\u2713': '[OK]',   '\u2717': '[KO]',
    '\u26A0': '[!]',    '\u2605': '[*]',
    '\u2192': '->',     '\u2190': '<-',
    '\u2191': 'up',     '\u2193': 'down',
    '\u2611': '[x]',    '\u2610': '[ ]',
    '\u2714': '[OK]',   '\u2718': '[KO]',
    '\u2022': '*',      '\u2023': '-',
}


def sanitize_unicode(text: str) -> str:
    """
    Supprimer ou remplacer les caractères Unicode que LaTeX
    (même en mode xelatex) peut avoir du mal à rendre,
    notamment les emojis (catégorie So hors BMP latin).
    """
    cleaned = []
    for ch in text:
        cp = ord(ch)

        # ASCII et Latin-1 : tout passe
        if cp < 0x180:
            cleaned.append(ch)
            continue

        # Punctuation courante (–, —, «, », …, etc.) : garder
        if 0x2000 <= cp <= 0x206F:
            cleaned.append(ch)
            continue

        # Lettres accentuées, Cyrillic, Grec, etc. : garder (xelatex gère)
        if unicodedata.category(ch) in ('Lu', 'Ll', 'Lt', 'Lo',
                                        'Nl', 'Nd', 'Mn', 'Mc'):
            cleaned.append(ch)
            continue

        # Symboles / pictogrammes : remplacer ou supprimer
        if ch in _EMOJI_REPLACEMENTS:
            cleaned.append(_EMOJI_REPLACEMENTS[ch])
        elif unicodedata.category(ch) in ('So', 'Sk'):
            # Emoji et symboles divers → supprimer silencieusement
            pass
        else:
            cleaned.append(ch)

    return ''.join(cleaned)


def strip_front_matter(content: str) -> str:
    """Supprimer le bloc YAML front matter (---...---) en tête du fichier."""
    return re.sub(r'\A---\s*\n.*?\n---\s*\n', '', content, count=1, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Fusion des fichiers markdown
# ---------------------------------------------------------------------------

def find_markdown_files(directory: str) -> list[str]:
    """Trouver tous les fichiers .md dans le dossier, triés par nom."""
    md_files = sorted(Path(directory).glob("*.md"))
    return [str(f) for f in md_files]


def merge_markdown(files: list[str], output_path: str) -> None:
    """
    Fusionner plusieurs fichiers markdown en un seul.
    - Stripse le YAML front matter de chaque fichier.
    - Insère un saut de page (\\newpage) entre chaque document.
    - Sanitise les caractères Unicode problématiques.
    """
    with open(output_path, "w", encoding="utf-8") as merged:
        for i, filepath in enumerate(files):
            with open(filepath, "r", encoding="utf-8") as md_file:
                content = md_file.read()

            # 1. Retirer le YAML front matter (sinon il apparaît en texte brut)
            content = strip_front_matter(content)

            # 2. Supprimer les emojis / symboles non supportés
            content = sanitize_unicode(content)

            # 3. Saut de page entre les documents (pas de séparateur pour le 1er)
            if i > 0:
                merged.write("\n\\newpage\n\n")

            merged.write(content)


# ---------------------------------------------------------------------------
# Conversion PDF
# ---------------------------------------------------------------------------

# Chaîne d'extensions pandoc à activer
PANDOC_FROM = "markdown+task_lists+strikeout+raw_html+header_attributes"

# Ordre de préférence des moteurs LaTeX (du plus permissif au plus restrictif)
LATEX_ENGINES = ["xelatex", "lualatex", "pdflatex"]


def _run_pandoc(md_path: str, pdf_path: str, engine: str) -> subprocess.CompletedProcess:
    """Lancer pandoc avec le moteur LaTeX donné."""
    return subprocess.run(
        [
            "pandoc",
            md_path,
            "-o", pdf_path,
            "--from", PANDOC_FROM,
            "--pdf-engine", engine,
            "--variable", "geometry:margin=25mm",
            "--variable", "colorlinks=true",
            "--variable", "linkcolor=blue",
            # Pour xelatex / lualatex : polices avec support Unicode
            "--variable", "mainfont=Noto Serif",
			"--variable", "monofont=Noto Sans Mono",
			"--variable", "sansfont=Noto Sans",
            # Désactiver l'auto-indentation LaTeX (pandoc gère déjà)
            "--variable", "indent=false",
            "--variable", "linestretch=1.2",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def create_pdf_from_latex(md_path: str, pdf_path: str) -> None:
    """
    Convertir un fichier markdown en PDF via pandoc + LaTeX.
    Essaie xelatex, puis lualatex, puis pdflatex.
    Lève RuntimeError si tous les moteurs échouent.
    """
    last_error = ""

    for engine in LATEX_ENGINES:
        try:
            result = _run_pandoc(md_path, pdf_path, engine)
        except FileNotFoundError:
            # Moteur non installé sur cette machine → essayer le suivant
            print(f"  [info] {engine} non trouvé, essai du moteur suivant…",
                  file=sys.stderr)
            continue
        except subprocess.TimeoutExpired:
            last_error = f"{engine} : délai dépassé (180 s)"
            continue

        if result.returncode == 0:
            print(f"  [ok] PDF généré via {engine}")
            return  # Succès

        last_error = f"{engine} : {result.stderr[:800]}"

    raise RuntimeError(
        f"Tous les moteurs LaTeX ont échoué.\nDernière erreur : {last_error}"
    )


def create_pdf_from_html(md_path: str, pdf_path: str) -> None:
    """Fallback : markdown → HTML (pandoc) → PDF (Playwright/Chromium)."""
    html_path = md_path.replace(".md", ".html")

    # 1. markdown → HTML
    result = subprocess.run(
        [
            "pandoc", md_path,
            "-o", html_path,
            "--from", PANDOC_FROM,
            "--to", "html5",
            "--standalone",
            "--metadata", "title=Document fusionné",
            "--css", "-",   # CSS intégré ci-dessous via -V
            "--variable", "pagetitle=Document fusionné",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pandoc HTML : {result.stderr[:500]}")

    # 2. HTML → PDF via Playwright
    import http.server
    import threading

    html_dir = os.path.dirname(os.path.abspath(html_path))
    html_filename = os.path.basename(html_path)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=html_dir, **kwargs)
        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), QuietHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/{html_filename}")
            page.wait_for_load_state("networkidle")
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={
                    "top": "25mm",
                    "bottom": "25mm",
                    "left": "25mm",
                    "right": "25mm",
                },
            )
            browser.close()
    finally:
        server.shutdown()
        if os.path.exists(html_path):
            os.unlink(html_path)


# ---------------------------------------------------------------------------
# Entrée principale
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fusionner des fichiers markdown en un seul document PDF."
    )
    parser.add_argument(
        "--directory", type=str, required=True,
        help="Dossier contenant les fichiers markdown à fusionner",
    )
    parser.add_argument(
        "--output-format", type=str, default="pdf",
        choices=["pdf", "html"],
        help="Format de sortie (pdf ou html)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Nom du fichier de sortie (sans extension). Par défaut: nom du dossier",
    )
    parser.add_argument(
        "--no-sort", action="store_true",
        help="Ne pas trier les fichiers par nom",
    )

    args = parser.parse_args()

    directory = Path(args.directory)

    if not directory.exists():
        print(f"Erreur : le dossier '{directory}' n'existe pas.", file=sys.stderr)
        sys.exit(1)
    if not directory.is_dir():
        print(f"Erreur : '{directory}' n'est pas un dossier.", file=sys.stderr)
        sys.exit(1)

    # --- Recherche des fichiers ---
    if args.no_sort:
        md_files = [str(f) for f in directory.glob("*.md")]
    else:
        md_files = find_markdown_files(str(directory))

    if not md_files:
        print(f"Aucun fichier markdown trouvé dans '{directory}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Trouvé {len(md_files)} fichier(s) markdown :")
    for f in md_files:
        print(f"  - {os.path.basename(f)}")

    # --- Nom de sortie ---
    output_name = args.output if args.output else directory.name

    # --- Format HTML (pas de fusion via LaTeX) ---
    if args.output_format == "html":
        output_path = str(directory / f"{output_name}.html")
        # Écrire dans un tmp .md puis convertir en HTML
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=str(directory),
            delete=False, encoding="utf-8",
        ) as tmp:
            merge_markdown(md_files, tmp.name)
            tmp_path = tmp.name
        try:
            create_pdf_from_html(tmp_path, output_path.replace(".html", ".html"))
            # rename to .html
            final = output_path
            if os.path.exists(final):
                os.unlink(final)
            tmp_html = tmp_path.replace(".md", ".html")
            if os.path.exists(tmp_html):
                os.rename(tmp_html, final)
            print(f"\nHTML fusionné : {final}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # --- Format PDF ---
    elif args.output_format == "pdf":
        pdf_path = str(directory / f"{output_name}.pdf")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=str(directory),
            delete=False, encoding="utf-8",
        ) as tmp:
            merge_markdown(md_files, tmp.name)
            tmp_md_path = tmp.name

        try:
            try:
                create_pdf_from_latex(tmp_md_path, pdf_path)
                print(f"\nPDF créé (via LaTeX) : {pdf_path}")
            except RuntimeError as exc:
                print(f"\n⚠️  Conversion LaTeX échouée :\n{exc}", file=sys.stderr)
                print("→ Fallback : conversion via HTML + Chromium\n", file=sys.stderr)

                create_pdf_from_html(tmp_md_path, pdf_path)
                print(f"\nPDF créé (via HTML) : {pdf_path}")

        finally:
            if os.path.exists(tmp_md_path):
                os.unlink(tmp_md_path)
            print("Fichiers temporaires nettoyés.")


if __name__ == "__main__":
    main()
