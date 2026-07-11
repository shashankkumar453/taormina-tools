"""Build docs/index.html — the landing page for the published site.

Scans the output directory for ``report-YYYY-MM-DD.html`` files, links the most
recent one prominently, and lists the rest as an archive. Run after
``generate_reports`` so GitHub Pages has a root page to serve.

Usage:
    python -m taormina_tools.generate_index
    python -m taormina_tools.generate_index --output-dir docs
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

REPORT_RE = re.compile(r"^report-(\d{4}-\d{2}-\d{2})\.html$")

PAGE_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 760px; margin: 60px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.5; }
h1 { font-size: 30px; margin-bottom: 4px; }
.subtitle { color: #666; margin-bottom: 32px; font-size: 15px; }
.latest { display: block; background: #8b1c1c; color: #fff; border-radius: 10px; padding: 22px 26px; text-decoration: none; margin-bottom: 36px; }
.latest:hover { background: #701616; }
.latest .label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.85; }
.latest .date { font-size: 24px; font-weight: 700; margin-top: 2px; }
.latest .go { font-size: 13px; opacity: 0.9; margin-top: 6px; }
h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; color: #666; border-bottom: 1px solid #eee; padding-bottom: 8px; }
ul.archive { list-style: none; padding: 0; }
ul.archive li { padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
ul.archive a { color: #2980b9; text-decoration: none; font-size: 16px; font-weight: 600; }
ul.archive a:hover { text-decoration: underline; }
.empty { color: #999; font-style: italic; }
.footer { color: #999; font-size: 12px; margin-top: 48px; border-top: 1px solid #eee; padding-top: 14px; }
"""


def find_reports(output_dir: Path) -> list[tuple[str, str]]:
    """Return (date, filename) pairs, most recent first."""
    reports = []
    for path in output_dir.glob("report-*.html"):
        m = REPORT_RE.match(path.name)
        if m:
            reports.append((m.group(1), path.name))
    reports.sort(reverse=True)
    return reports


def build_index(output_dir: Path, today: str) -> str:
    reports = find_reports(output_dir)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="robots" content="noindex, nofollow">',
        "<title>Taormina Tools — Weekly Reports</title>",
        f"<style>\n{PAGE_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>Taormina Motorsport — Weekly Reports</h1>",
        '<p class="subtitle">Underpriced exotics, salvage, and classifieds leads. Refreshed weekly.</p>',
    ]

    if reports:
        latest_date, latest_file = reports[0]
        parts.append(
            f'<a class="latest" href="{latest_file}">'
            f'<div class="label">Latest report</div>'
            f'<div class="date">{latest_date}</div>'
            f'<div class="go">View leads &rarr;</div>'
            f"</a>"
        )
        if len(reports) > 1:
            parts.append("<h2>Archive</h2>")
            parts.append('<ul class="archive">')
            for d, fname in reports[1:]:
                parts.append(f'<li><a href="{fname}">Week of {d}</a></li>')
            parts.append("</ul>")
    else:
        parts.append('<p class="empty">No reports generated yet.</p>')

    parts.append(f'<div class="footer">Last updated {today}.</div>')
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def generate_index(output_dir: Path, today: str | None = None) -> Path:
    today = today or date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "index.html"
    out_path.write_text(build_index(output_dir, today), encoding="utf-8")
    print(f"  Wrote {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the docs/ landing page")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"), help="Reports directory (default: docs)")
    args = parser.parse_args(argv)
    generate_index(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
