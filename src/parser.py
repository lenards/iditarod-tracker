"""Parses Iditarod log HTML into structured musher data.

The log/standings pages are organized into sections, each with an <h2> heading
and its own <table>:

  - "Finished"     — mushers who reached Nome (competitive)
  - "Racing"       — mushers still on the trail (competitive)
  - "Out of Race"  — scratched or withdrawn mushers
  - "Expedition"   — Expedition Class (non-competitive), may contain its own
                     "Finished" subsection

The Racing and Out of Race tables share a column layout:
  0  Pos, 1  Musher, 2  Bib, 3  Checkpoint,
  4  In>Time, 5  In>Dogs, 6  Out>Time, 7  Out>Dogs,
  8  Rest In Chkpt, 9  Time Enroute, 10  Previous checkpoint,
  11  Previous time, 12  Speed, ...

The Finished table has a different layout:
  0  Pos, 1  Musher, 2  Bib, 3  Checkpoint(=Nome),
  4  Time In, 5  Dogs In, 6  Total Race Time, 7  Average Speed,
  8  Time Enroute, 9  Previous Checkpoint, 10  Previous Time Out
"""

from __future__ import annotations

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


def _clean_name(raw: str) -> tuple[str, bool]:
    """Returns (clean_name, is_rookie)."""
    is_rookie = "(r)" in raw.lower()
    clean = re.sub(r"\s*\(r\)\s*", "", raw, flags=re.I).strip()
    return clean, is_rookie


# ---------------------------------------------------------------------------
# Section-aware table finders
# ---------------------------------------------------------------------------

_SECTION_NAMES = {"Finished", "Racing", "Out of Race", "Expedition"}


def _find_sections(soup: BeautifulSoup) -> dict[str, list]:
    """
    Walk all <h2> headings and associate each recognized section name with the
    <table> that immediately follows it.

    Returns a dict like:
      {
        "finished": [table, ...],
        "racing": [table, ...],
        "out_of_race": [table, ...],
        "expedition_racing": [table, ...],
        "expedition_finished": [table, ...],
      }

    There can be two "Finished" headings — one for competitive, one under the
    Expedition heading.  We detect this by tracking whether we've seen the
    "Expedition" heading yet.
    """
    sections: dict[str, list] = {
        "finished": [],
        "racing": [],
        "out_of_race": [],
        "expedition_racing": [],
        "expedition_finished": [],
    }

    seen_tables: set[int] = set()
    in_expedition = False
    for h2 in soup.find_all("h2"):
        text = h2.get_text(strip=True)
        if text not in _SECTION_NAMES:
            continue

        table = h2.find_next("table")
        if not table:
            continue

        table_id = id(table)
        if table_id in seen_tables:
            continue  # same table already associated with a prior heading
        seen_tables.add(table_id)

        if text == "Expedition":
            in_expedition = True
            # The Expedition heading's next table — could be racing or finished layout
            sections["expedition_racing"].append(table)
        elif text == "Finished":
            if in_expedition:
                sections["expedition_finished"].append(table)
            else:
                sections["finished"].append(table)
        elif text == "Racing":
            sections["racing"].append(table)
        elif text == "Out of Race":
            sections["out_of_race"].append(table)

    return sections


# ---------------------------------------------------------------------------
# Row parsers for the two table layouts
# ---------------------------------------------------------------------------

def _parse_racing_rows(table, status: str) -> list[dict]:
    """
    Parse rows from a Racing or Out of Race table.

    Column layout:
      0  Pos, 1  Musher, 2  Bib, 3  Checkpoint,
      4  In>Time, 5  In>Dogs, 6  Out>Time, 7  Out>Dogs,
      8  Rest In Chkpt, 9  Time Enroute, 10  Previous,
      11  Previous time, 12  Speed, ...
      (Out of Race also has a trailing Status column like "Scratched")
    """
    col = {
        "pos": 0, "musher": 1, "bib": 2, "checkpoint": 3,
        "in_time": 4, "in_dogs": 5, "out_time": 6, "out_dogs": 7,
        "rest": 8, "enroute": 9, "previous": 10,
    }

    all_rows = table.find_all("tr")
    header_rows = set()
    for tr in all_rows:
        if tr.find("th"):
            header_rows.add(tr)
            if len(header_rows) == 2:
                break

    mushers = []
    for tr in all_rows:
        if tr in header_rows:
            continue
        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue

        pos_text = _cell(cells, col["pos"])
        pos = _safe_int(pos_text)

        name_raw = _cell(cells, col["musher"])
        if not name_raw:
            continue
        clean_name, is_rookie = _clean_name(name_raw)

        out_time = _cell(cells, col["out_time"])
        out_dogs_str = _cell(cells, col["out_dogs"])
        in_dogs_str = _cell(cells, col["in_dogs"])

        in_dogs = _safe_int(in_dogs_str)
        out_dogs = _safe_int(out_dogs_str)
        at_checkpoint = _is_empty(out_time) or _is_empty(out_dogs_str)

        dropped = 0
        if in_dogs is not None and out_dogs is not None:
            dropped = max(0, in_dogs - out_dogs)

        # For "Out of Race" rows, try to capture the reason from the last column
        withdrawal_reason = ""
        if status == "out_of_race":
            # The Status column is typically the last cell
            last_cell = _cell(cells, len(cells) - 1)
            if last_cell.lower() in ("scratched", "withdrawn", "veterinarian", "rule 34"):
                withdrawal_reason = last_cell
            # Out of Race rows often have empty Pos
            if pos is None:
                pos = 0

        if status == "racing" and pos is None:
            continue  # skip non-data rows in racing table

        mushers.append({
            "pos": pos or 0,
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
            "status": status,
            "withdrawal_reason": withdrawal_reason,
        })

    return mushers


def _parse_finished_rows(table, status: str = "finished") -> list[dict]:
    """
    Parse rows from a Finished table.

    Column layout:
      0  Pos, 1  Musher, 2  Bib, 3  Checkpoint(=Nome),
      4  Time In, 5  Dogs In, 6  Total Race Time, 7  Average Speed,
      8  Time Enroute, 9  Previous Checkpoint, 10  Previous Time Out
    """
    all_rows = table.find_all("tr")
    header_rows = set()
    for tr in all_rows:
        if tr.find("th"):
            header_rows.add(tr)
            if len(header_rows) == 2:
                break

    mushers = []
    for tr in all_rows:
        if tr in header_rows:
            continue
        cells = tr.find_all(["td", "th"])
        if len(cells) < 6:
            continue

        pos_text = _cell(cells, 0)
        pos = _safe_int(pos_text)
        if pos is None:
            continue

        name_raw = _cell(cells, 1)
        if not name_raw:
            continue
        clean_name, is_rookie = _clean_name(name_raw)

        in_dogs = _safe_int(_cell(cells, 5))
        total_race_time = _cell(cells, 6)
        avg_speed = _cell(cells, 7)

        mushers.append({
            "pos": pos,
            "name": clean_name,
            "rookie": is_rookie,
            "bib": _cell(cells, 2),
            "checkpoint": _cell(cells, 3),  # Should be "Nome"
            "in_time": _cell(cells, 4),
            "in_dogs": in_dogs,
            "out_time": "",
            "out_dogs": None,
            "at_checkpoint": False,  # they're done, not "at checkpoint"
            "dropped": 0,
            "rest": "",
            "enroute": _cell(cells, 8),
            "previous": _cell(cells, 9) if len(cells) > 9 else "",
            "status": status,
            "withdrawal_reason": "",
            "total_race_time": total_race_time,
            "avg_speed": avg_speed,
        })

    return mushers


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

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
            "status": str,           # "finished"|"racing"|"out_of_race"|"expedition"
            "withdrawal_reason": str, # "Scratched"|"Withdrawn"|"" etc.
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

    # -- Find section tables --
    sections = _find_sections(soup)

    mushers = []

    # Competitive finished
    for table in sections["finished"]:
        mushers.extend(_parse_finished_rows(table, status="finished"))

    # Competitive racing
    for table in sections["racing"]:
        mushers.extend(_parse_racing_rows(table, status="racing"))

    # Out of Race
    for table in sections["out_of_race"]:
        mushers.extend(_parse_racing_rows(table, status="out_of_race"))

    # Expedition (racing + finished)
    for table in sections["expedition_racing"]:
        # Could be racing-layout or finished-layout; detect from headers
        first_row = table.find("tr")
        if first_row and "Total Race Time" in first_row.get_text():
            mushers.extend(_parse_finished_rows(table, status="expedition"))
        else:
            mushers.extend(_parse_racing_rows(table, status="expedition"))

    for table in sections["expedition_finished"]:
        mushers.extend(_parse_finished_rows(table, status="expedition"))

    # -- Fallback: if no sections found, try the old single-table approach --
    # This handles older logs that may not have section headings yet.
    if not mushers:
        mushers = _parse_legacy_single_table(soup)

    return {
        "log_label": log_label,
        "timestamp": timestamp,
        "mushers": mushers,
    }


def _parse_legacy_single_table(soup: BeautifulSoup) -> list[dict]:
    """Fallback for logs that don't have section headings — parse the first
    table that looks like a standings table (old behavior)."""
    table = None
    for t in soup.find_all("table"):
        text = t.get_text()
        if "Musher" in text and ("Pos" in text or "Bib" in text):
            table = t
            break

    if not table:
        return []

    return _parse_racing_rows(table, status="racing")
