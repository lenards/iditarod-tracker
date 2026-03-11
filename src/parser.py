"""Parses Iditarod log HTML into structured musher data.

Actual data row layout (confirmed from HTML):
  0  Pos
  1  Musher (link)
  2  Bib
  3  Checkpoint (link)
  4  In > Time
  5  In > Dogs
  6  Out > Time       (empty if musher is still at checkpoint)
  7  Out > Dogs       (empty if musher is still at checkpoint)
  8  Rest In Chkpt    (empty if still at checkpoint)
  9  Time Enroute
  10 Previous checkpoint
  11 Previous time
  12 Speed
  ...

At checkpoint = Out Time and Out Dogs are empty strings.
Dropped dogs = In Dogs - Out Dogs.
"""

import re
from bs4 import BeautifulSoup


def _cell(cells: list, idx: int) -> str:
    if idx < len(cells):
        return cells[idx].get_text(strip=True)
    return ""


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _is_empty(value: str) -> bool:
    return not value or value.strip() in ("", "-", "—", "–")


def parse_log(html: str) -> dict:
    """
    Parse a log page and return:
      {
        "log_label": str,
        "timestamp": str,
        "mushers": [
          {
            "pos": int,
            "name": str,
            "rookie": bool,
            "bib": str,
            "checkpoint": str,
            "in_time": str,
            "in_dogs": int | None,
            "out_time": str,
            "out_dogs": int | None,
            "at_checkpoint": bool,
            "dropped": int,
            "rest": str,
            "enroute": str,
            "previous": str,
          },
          ...
        ]
      }
    """
    soup = BeautifulSoup(html, "lxml")

    # -- Log label + timestamp --
    log_label = ""
    timestamp = ""
    for tag in soup.find_all(["h1", "h2", "h3", "title"]):
        text = tag.get_text(strip=True)
        if re.search(r"log\s*\d+", text, re.I):
            log_label = text
            break
    for tag in soup.find_all(class_=re.compile(r"date|time|subtitle|log.header", re.I)):
        text = tag.get_text(strip=True)
        if text:
            timestamp = text
            break

    # -- Find the standings table --
    table = None
    for t in soup.find_all("table"):
        text = t.get_text()
        if "Musher" in text and ("Pos" in text or "Bib" in text):
            table = t
            break

    if not table:
        return {"log_label": log_label, "timestamp": timestamp, "mushers": []}

    # Column indices — confirmed from actual HTML inspection.
    # Checkpoint is a per-row <td> (link), not a group header.
    col = {
        "pos": 0,
        "musher": 1,
        "bib": 2,
        "checkpoint": 3,
        "in_time": 4,
        "in_dogs": 5,
        "out_time": 6,
        "out_dogs": 7,
        "rest": 8,
        "enroute": 9,
        "previous": 10,
    }

    # -- Parse rows --
    # Skip the first 1-2 header rows (contain <th> and "Musher"/"In"/"Out" etc.)
    all_rows = table.find_all("tr")
    header_rows = set()
    for tr in all_rows:
        if tr.find("th"):
            header_rows.add(tr)
            if len(header_rows) == 2:
                break  # only skip the first two header rows

    mushers = []

    for tr in all_rows:
        if tr in header_rows:
            continue

        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue

        pos_text = _cell(cells, col["pos"])
        try:
            pos = int(pos_text)
        except ValueError:
            continue  # skip non-data rows

        name_cell = cells[col["musher"]] if col["musher"] < len(cells) else None
        name = name_cell.get_text(strip=True) if name_cell else ""
        is_rookie = "(r)" in name.lower()
        clean_name = re.sub(r"\s*\(r\)\s*", "", name, flags=re.I).strip()

        out_time = _cell(cells, col["out_time"])
        out_dogs_str = _cell(cells, col["out_dogs"])
        in_dogs_str = _cell(cells, col["in_dogs"])

        in_dogs = _safe_int(in_dogs_str)
        out_dogs = _safe_int(out_dogs_str)
        at_checkpoint = _is_empty(out_time) or _is_empty(out_dogs_str)

        dropped = 0
        if in_dogs is not None and out_dogs is not None:
            dropped = max(0, in_dogs - out_dogs)

        mushers.append({
            "pos": pos,
            "name": clean_name,
            "rookie": is_rookie,
            "bib": _cell(cells, col["bib"]),
            "checkpoint": _cell(cells, col["checkpoint"]),
            "in_time": _cell(cells, col["in_time"]),
            "in_dogs": in_dogs,
            "out_time": out_time,
            "out_dogs": out_dogs,
            "at_checkpoint": at_checkpoint,
            "dropped": dropped,
            "rest": _cell(cells, col["rest"]),
            "enroute": _cell(cells, col["enroute"]),
            "previous": _cell(cells, col["previous"]),
        })

    return {
        "log_label": log_label,
        "timestamp": timestamp,
        "mushers": mushers,
    }
