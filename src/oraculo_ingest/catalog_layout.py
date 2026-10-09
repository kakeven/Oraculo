"""Linhas visuais do livro, em ordem de leitura por coluna."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pypdf import PdfReader


def page_lines(page: Any) -> list[dict[str, Any]]:
    """Lê a coluna esquerda inteira antes da direita, preservando a fonte dos títulos."""
    width = float(page.mediabox.width)
    middle = width / 2
    fragments: dict[int, list[dict[str, Any]]] = defaultdict(list)

    def visit(text: str, _cm: list[float], tm: list[float], font: Any,
              font_size: float) -> None:
        if not text.strip():
            return
        x, y = float(tm[4]), float(tm[5])
        if y < 35 or y > float(page.mediabox.height) - 22:
            return
        fragments[int(x >= middle)].append({
            "x": x, "y": y, "text": text,
            "font": str(font.get("/BaseFont", "")) if font else "",
            "size": round(abs(float(tm[0]) * font_size)),
        })

    page.extract_text(visitor_text=visit)
    # Uma linha larga pode atravessar o meio da página com mudanças de fonte.
    # Seus fragmentos à direita continuam na mesma linha, antes das colunas.
    wide_y = [span["y"] for span in fragments[0]
              if span["x"] < 90 and len(span["text"]) >= 70]
    fragments[0].extend(span for span in fragments[1]
                        if any(abs(span["y"] - y) <= 2 for y in wide_y))
    fragments[1] = [span for span in fragments[1]
                    if not any(abs(span["y"] - y) <= 2 for y in wide_y)]
    lines: list[dict[str, Any]] = []
    for column in (0, 1):
        groups: list[list[dict[str, Any]]] = []
        for span in sorted(fragments[column], key=lambda s: (-s["y"], s["x"])):
            if groups and abs(groups[-1][0]["y"] - span["y"]) <= 2:
                groups[-1].append(span)
            else:
                groups.append([span])
        for group in groups:
            group.sort(key=lambda s: s["x"])
            value = group[0]["text"].strip()
            for span in group[1:]:
                part = span["text"]
                if value.endswith((" ", "\t")) or part.startswith((" ", "\t")) or part == "-":
                    value += part
                else:
                    value += " " + part
            value = " ".join(value.split())
            if not value or value.isdigit():
                continue
            first = group[0]
            lines.append({
                "text": value, "column": column, "y": round(first["y"], 2),
                "heading": first["text"].strip() if "Newsflash" in first["font"] else "",
                "heading_size": first["size"] if "Newsflash" in first["font"] else 0,
            })
    return lines


def catalog_page_lines(reader: PdfReader, page_numbers: set[int]) -> dict[int, list[dict[str, Any]]]:
    return {number: page_lines(reader.pages[number - 1]) for number in sorted(page_numbers)
            if number <= len(reader.pages)}
