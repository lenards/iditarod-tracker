"""Parses Iditarod log HTML into structured musher data.

The standings table uses checkpoint names as GROUP HEADER rows (not per-row columns).
Each checkpoint group has a spanning header like "Nikolai", followed by musher rows.

Data row column layout (0-indexed, NO checkpoint column):
  0  Pos
  1  Musher
  2  Bib
  3  In > Time
  4  In > Dogs
  5  Out > Time
  6  Out > Dogs
  7  Rest In Chkpt
  8  Time Enroute
  9  Previous

Empty Out Time/Dogs = musher is currently resting at the checkpoint.
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


def _looks_like_timestamp(value: str) -> bool:
    """Detect if a string is a date/time rather than a checkpoint name."""
    return bool(re.match(r"\d+/\d+", value.strip()))


def _is_checkpoint_header(tr) -> str | None:
    """
    Returns the checkpoint name if this row is a group header, else None.
    Group headers are rows with a single colspan cell (or one meaningful cell)
    that contains a checkpoint name (not a timestamp, not a number).
    """
    cells = tr.find_all(["td", "th"])
    if not cells:
        return None

    # Single cell spanning multiple columns
    if len(cells) == 1:
        text = cells[0].get_text(strip=True)
        colspan = int(cells[0].get("colspan", 1))
        if colspan > 2 and text and not _looks_like_timestamp(text):
            return text

    # Row where only the first cell has content and rest are empty — also a header
    non_empty = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
    if len(non_empty) == 1:
        text = non_empty[0]
        if not _looks_like_timestamp(text) and not text.isdigit():
            return text

    return None


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
            "checkpoint": str,    # from group header row
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

    # -- Build column map from headers --
    # Default layout assumes no "Checkpoint" column in data rows:
    col = {
        "pos": 0,
        "musher": 1,
        "bib": 2,
        "in_time": 3,
        "in_dogs": 4,
        "out_time": 5,
        "out_dogs": 6,
        "rest": 7,
        "enroute": 8,
        "previous": 9,
    }

    all_rows = table.find_all("tr")

    # Find header rows (contain <th> elements)
    header_rows = [tr for tr in all_rows if tr.find("th")]

    def expand_headers(tr) -> list[str]:
        result = []
        for th in tr.find_all(["th", "td"]):
            text = th.get_text(strip=True)
            colspan = int(th.get("colspan", 1))
            result.extend([text] * colspan)
        return result

    if len(header_rows) >= 2:
        sections = expand_headers(header_rows[0])
        details = expand_headers(header_rows[1])

        while len(details) < len(sections):
            details.append("")

        for i, (sec, det) in enumerate(zip(sections, details)):
            sec_l = sec.lower().replace(" ", "")
            det_l = det.lower().replace(" ", "")

            if sec_l == "pos" or det_l == "pos":
                col["pos"] = i
            elif sec_l == "musher" or det_l == "musher":
                col["musher"] = i
            elif sec_l == "bib" or det_l == "bib":
                col["bib"] = i
            elif sec_l == "in" and det_l == "time":
                col["in_time"] = i
            elif sec_l == "in" and det_l == "dogs":
                col["in_dogs"] = i
            elif sec_l == "out" and det_l == "time":
                col["out_time"] = i
            elif sec_l == "out" and det_l == "dogs":
                col["out_dogs"] = i
            elif "rest" in sec_l or "rest" in det_l:
                col["rest"] = i
            elif "enroute" in sec_l or "enroute" in det_l:
                col["enroute"] = i
            elif "previous" in sec_l or "previous" in det_l:
                col["previous"] = i

    # -- Parse all rows, tracking checkpoint group headers --
    mushers = []
    current_checkpoint = ""

    for tr in all_rows:
        # Skip header rows
        if tr in header_rows:
            continue

        # Check if this is a checkpoint group header
        chk = _is_checkpoint_header(tr)
        if chk:
            current_checkpoint = chk
            continue

        # Data row
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            continue

        pos_text = _cell(cells, col["pos"])
        try:
            pos = int(pos_text)
        except ValueError:
            continue

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
            "checkpoint": current_checkpoint,
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
