"""Per-session workspaces on the runtime host, and the sample files the report writer produces in them.

The files are built without third-party libraries so the demo needs no keys and no extra packages: a Markdown report,
an HTML page with a script (to show that previews run isolated), a CSV, a JSON summary, an SVG chart, a PNG chart,
a one-page PDF and a Jupyter notebook with saved outputs.
"""

from __future__ import annotations

import base64
import itertools
import json
import re
import struct
import zlib
from pathlib import Path

from app.settings import get_settings

QUARTERS = ("Q1", "Q2", "Q3", "Q4")


def workspace_for(session_id: str | None) -> Path:
    """``<RUNTIME_WORKSPACE_DIR>/<session id>``, created on first use. Session ids are reduced to safe characters."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "no-session")[:120] or "no-session"
    path = Path(get_settings().workspace_dir).resolve() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _series(topic: str) -> list[int]:
    seed = sum(ord(char) for char in topic) or 7
    return [40 + (seed * (index + 3)) % 55 for index in range(len(QUARTERS))]


def _svg_chart(topic: str, values: list[int]) -> str:
    bars = "".join(
        f'<rect x="{30 + index * 60}" y="{170 - value * 1.5:.0f}" width="40" height="{value * 1.5:.0f}" '
        'fill="#6d8cff"/>'
        f'<text x="{50 + index * 60}" y="190" text-anchor="middle" font-size="12" fill="#9aa4b2">{quarter}</text>'
        for index, (quarter, value) in enumerate(zip(QUARTERS, values, strict=True))
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="200" viewBox="0 0 280 200">'
        f'<title>{topic}: quarterly volume</title><rect width="280" height="200" fill="#11151c"/>{bars}</svg>'
    )


def _png_chart(values: list[int]) -> bytes:
    width, height = 160, 100
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            bar, offset = divmod(x, 40)
            filled = 8 <= offset < 32 and (height - y) <= values[bar]
            row += bytes((109, 140, 255) if filled else (17, 21, 28))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def _pdf(title: str, lines: list[str]) -> bytes:
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text = ["BT", "/F1 20 Tf", "72 760 Td", f"({escape(title)}) Tj", "/F1 12 Tf"]
    for line in lines:
        text += ["0 -22 Td", f"({escape(line)}) Tj"]
    text.append("ET")
    stream = "\n".join(text).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _lines(text: str) -> list[str]:
    """``text`` as nbformat stores multi-line strings: a list of lines, each but the last ending in a newline."""
    return text.splitlines(keepends=True)


def _notebook(topic: str, values: list[int], png: bytes) -> str:
    """An nbformat 4 notebook of the same analysis, with the outputs a kernel would have saved."""
    total = sum(values)
    peak = QUARTERS[values.index(max(values))]
    growth = [round(later / earlier - 1, 3) for earlier, later in itertools.pairwise(values)]
    rows = "".join(
        f"<tr><th>{index}</th><td>{quarter}</td><td>{value}</td><td>{value / total:.3f}</td></tr>\n"
        for index, (quarter, value) in enumerate(zip(QUARTERS, values, strict=True))
    )
    frame = (
        "<div>\n<style scoped>\n    .dataframe tbody tr th { vertical-align: top; }\n</style>\n"
        '<table border="1" class="dataframe">\n<thead><tr style="text-align: right;">'
        "<th></th><th>quarter</th><th>volume</th><th>share</th></tr></thead>\n"
        f"<tbody>\n{rows}</tbody>\n</table>\n</div>"
    )
    plain = "\n".join(
        f"{index}  {quarter}  {value}  {value / total:.3f}"
        for index, (quarter, value) in enumerate(zip(QUARTERS, values, strict=True))
    )
    traceback = [
        "\x1b[0;31m---------------------------------------------------------------------------\x1b[0m",
        "\x1b[0;31mZeroDivisionError\x1b[0m                         Traceback (most recent call last)",
        "Cell \x1b[0;32mIn[5], line 1\x1b[0m\n\x1b[0;32m----> 1\x1b[0m growth_rate(\x1b[38;5;241m0\x1b[39m, total)",
        "\x1b[0;31mZeroDivisionError\x1b[0m: division by zero",
    ]

    def code(count: int, source: str, outputs: list[dict[str, object]]) -> dict[str, object]:
        return {
            "cell_type": "code",
            "execution_count": count,
            "id": f"code-{count}",
            "metadata": {},
            "source": _lines(source),
            "outputs": outputs,
        }

    def markdown(identifier: str, source: str) -> dict[str, object]:
        return {"cell_type": "markdown", "id": identifier, "metadata": {}, "source": _lines(source)}

    def result(count: int, data: dict[str, object]) -> dict[str, object]:
        return {"output_type": "execute_result", "execution_count": count, "metadata": {}, "data": data}

    cells = [
        markdown(
            "intro",
            f"# Analysis: {topic}\n\n"
            "Quarterly volume, its share of the year and the growth between quarters.\n\n"
            "- Data: `data.csv`, written alongside this notebook\n"
            "- Growth from one quarter to the next is $g_t = \\frac{v_t}{v_{t-1}} - 1$\n",
        ),
        code(
            1,
            "import pandas as pd\n\n"
            'frame = pd.read_csv("data.csv")\n'
            'frame["share"] = frame["volume"] / frame["volume"].sum()\n'
            "frame",
            [result(1, {"text/html": _lines(frame), "text/plain": _lines(plain)})],
        ),
        code(
            2,
            'total = frame["volume"].sum()\n'
            'peak = frame.loc[frame["volume"].idxmax(), "quarter"]\n'
            'print(f"Total {total}, peak in {peak}")',
            [{"output_type": "stream", "name": "stdout", "text": [f"Total {total}, peak in {peak}\n"]}],
        ),
        markdown(
            "growth",
            "## Growth\n\nThe mean growth over the year:\n\n"
            "$$\n\\bar{g} = \\frac{1}{n-1} \\sum_{t=2}^{n} \\left( \\frac{v_t}{v_{t-1}} - 1 \\right)\n$$\n",
        ),
        code(
            3,
            "def growth_rate(earlier: float, later: float) -> float:\n"
            '    """Relative change from one quarter to the next."""\n'
            "    return later / earlier - 1\n\n"
            "[round(growth_rate(a, b), 3) for a, b in zip(frame.volume, frame.volume[1:])]",
            [result(3, {"text/plain": [repr(growth)]})],
        ),
        code(
            4,
            'import matplotlib.pyplot as plt\n\nframe.plot.bar(x="quarter", y="volume", legend=False)\nplt.show()',
            [
                {
                    "output_type": "display_data",
                    "metadata": {},
                    "data": {
                        "image/png": base64.b64encode(png).decode("ascii"),
                        "text/plain": ["<Figure size 640x480 with 1 Axes>"],
                    },
                }
            ],
        ),
        code(
            5,
            "growth_rate(0, total)",
            [
                {
                    "output_type": "error",
                    "ename": "ZeroDivisionError",
                    "evalue": "division by zero",
                    "traceback": traceback,
                }
            ],
        ),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12.7", "file_extension": ".py"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1) + "\n"


def write_sample_report(root: Path, topic: str) -> list[str]:
    """Write the sample report files under ``root/outputs`` and return their paths relative to ``root``."""
    topic = " ".join(topic.split())[:80] or "the quarter"
    values = _series(topic)
    outputs = root / "outputs"
    (outputs / "charts").mkdir(parents=True, exist_ok=True)
    table = "\n".join(f"| {quarter} | {value} |" for quarter, value in zip(QUARTERS, values, strict=True))
    files: dict[str, str | bytes] = {
        "outputs/report.md": (
            f"# Report: {topic}\n\n"
            "A short brief produced by the report writer.\n\n"
            "## Volume by quarter\n\n| Quarter | Volume |\n|---|---|\n"
            f"{table}\n\n![Chart](charts/volume.svg)\n\n"
            "## How it was computed\n\n```python\n"
            "values = [40 + (seed * (i + 3)) % 55 for i in range(4)]\n```\n\n"
            f"- Peak quarter: **{QUARTERS[values.index(max(values))]}**\n- Total: {sum(values)}\n"
        ),
        "outputs/summary.html": (
            "<!doctype html><html><head><meta charset='utf-8'><title>Summary</title>"
            "<style>body{font:14px system-ui;margin:24px;background:#fff;color:#111}"
            "button{padding:6px 12px}</style></head><body>"
            f"<h1>{topic}</h1><p>Total volume: <b>{sum(values)}</b></p>"
            "<button id='b'>Clicked 0 times</button>"
            "<p id='cookie'></p>"
            "<script>let n=0;const b=document.getElementById('b');"
            "b.onclick=()=>{b.textContent='Clicked '+(++n)+' times'};"
            "try{document.getElementById('cookie').textContent='Cookies visible: '+(document.cookie||'none')}"
            "catch(e){document.getElementById('cookie').textContent='Cookies blocked: isolated preview'}"
            "</script></body></html>"
        ),
        "outputs/data.csv": "quarter,volume\n"
        + "".join(f"{quarter},{value}\n" for quarter, value in zip(QUARTERS, values, strict=True)),
        "outputs/summary.json": json.dumps(
            {"topic": topic, "quarters": dict(zip(QUARTERS, values, strict=True)), "total": sum(values)}, indent=2
        ),
        "outputs/charts/volume.svg": _svg_chart(topic, values),
        "outputs/charts/volume.png": _png_chart(values),
        "outputs/analysis.ipynb": _notebook(topic, values, _png_chart(values)),
        "outputs/report.pdf": _pdf(
            f"Report: {topic}", [f"{quarter}: {value}" for quarter, value in zip(QUARTERS, values, strict=True)]
        ),
    }
    for relative, content in files.items():
        target = root / relative
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return list(files)
