"""Fetches log listings and individual log pages from iditarod.com."""

import re
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://iditarod.com/race/2026/logs/"
HEADERS = {"User-Agent": "iditarod-tracker/1.0 (github.com/lenards/iditarod-tracker)"}


def fetch_log_list() -> list[int]:
    """Returns sorted list of all available log numbers."""
    resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    numbers = set()
    for a in soup.find_all("a", href=re.compile(r"/race/2026/logs/\d+")):
        m = re.search(r"/race/2026/logs/(\d+)", a["href"])
        if m:
            numbers.add(int(m.group(1)))

    return sorted(numbers)


def fetch_log(number: int) -> str:
    """Returns HTML of a specific log page."""
    url = f"{BASE_URL}{number}/"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_new_logs(last_seen: int) -> list[tuple[int, str]]:
    """
    Returns list of (log_number, html) for all logs after last_seen.
    Fetches in order, with a small delay to be polite.
    """
    all_logs = fetch_log_list()
    new_numbers = [n for n in all_logs if n > last_seen]

    results = []
    for number in new_numbers:
        try:
            html = fetch_log(number)
            results.append((number, html))
            if len(new_numbers) > 1:
                time.sleep(0.5)
        except requests.RequestException as e:
            print(f"Warning: failed to fetch log {number}: {e}")

    return results
