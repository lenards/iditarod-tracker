"""Parses Iditarod log HTML into structured musher data.

Table column layout (0-indexed, accounting for colspan on In/Out):
  0  Pos
  1  Musher
  2  Bib
  3  Checkpoint
  4  In > Time
  5  In > Dogs
  6  Out > Time
  7  Out > Dogs
  8  Rest In Chkpt
  9  Time Enroute
  10 Previous
  ... (speed, layover, etc.)

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
    """Treat dashes, blank, or whitespace as empty."""
    return not value or value.strip() in ("", "-", "—", "–")


def parse_log(html: str) -> dict:
    """
    Parse a log page and return:
      {
        "log_label": str,      # e.g. "Log 98"
        "timestamp": str,      # e.g. "March 10, 2026 4:31pm"
        "mushers": [
          {
            "pos": int,
            "name": str,
            "bib": str,
            "checkpoint": str,
            "in_time": str,
            "in_dogs": int | None,
            "out_time": str,
            "out_dogs": int | None,
            "at_checkpoint": bool,   # True if Out cols are empty
            "dropped": int,          # in_dogs - out_dogs (0 if none)
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

    # Look for heading like "Log 98" or "Race Log 98"
    for tag in soup.find_all(["h1", "h2", "h3", "title"]):
        text = tag.get_text(strip=True)
        if re.search(r"log\s*\d+", text, re.I):
            log_label = text
            break

    # Timestamp often in a subtitle or meta description
    for tag in soup.find_all(class_=re.compile(r"date|time|subtitle|log.header", re.I)):
        text = tag.get_text(strip=True)
        if text:
            timestamp = text
            break

    # -- Find the standings table --
    table = None
    for t in soup.find_all("table"):
        text = t.get_text()
        if "Musher" in text and "Checkpoint" in text:
            table = t
            break

    if not table:
        return {"log_label": log_label, "timestamp": timestamp, "mushers": []}

    # -- Find the column indices from headers --
    # We look for the two-row header: row 0 has section names (In/Out with colspan),
    # row 1 has detail names (Time, Dogs). We expand colspan so we can map by index.
    all_rows = table.find_all("tr")
    header_rows = []
    data_rows = []

    for tr in all_rows:
        if tr.find("th"):
            header_rows.append(tr)
        else:
            data_rows.append(tr)

    # Expand headers with colspan into flat lists
    def expand_headers(tr) -> list[str]:
        result = []
        for th in tr.find_all(["th", "td"]):
            text = th.get_text(strip=True)
            colspan = int(th.get("colspan", 1))
            result.extend([text] * colspan)
        return result

    # Try to identify column indices robustly
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

    if len(header_rows) >= 2:
        sections = expand_headers(header_rows[0])
        details = expand_headers(header_rows[1])

        # Pad details to match sections length
        while len(details) < len(sections):
            details.append("")

        for i, (sec, det) in enumerate(zip(sections, details)):
            key = f"{sec}.{det}".lower().replace(" ", "")
            sec_l = sec.lower().replace(" ", "")
            det_l = det.lower().replace(" ", "")

            if sec_l == "pos" or det_l == "pos":
                col["pos"] = i
            elif sec_l == "musher" or det_l == "musher":
                col["musher"] = i
            elif sec_l == "bib" or det_l == "bib":
                col["bib"] = i
            elif sec_l == "checkpoint" or det_l == "checkpoint":
                col["checkpoint"] = i
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

    # -- Parse data rows --
    # If we found explicit header rows, use remaining rows; otherwise try all
    if not data_rows:
        data_rows = all_rows[len(header_rows):]

    mushers = []
    for tr in data_rows:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue

        pos_text = _cell(cells, col["pos"])
        try:
            pos = int(pos_text)
        except ValueError:
            continue  # Skip non-data rows (sub-headers, spacers, etc.)

        name_cell = cells[col["musher"]] if col["musher"] < len(cells) else None
        name = name_cell.get_text(strip=True) if name_cell else ""
        # Strip rookie indicator "(r)" for clean name but keep for reference
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
