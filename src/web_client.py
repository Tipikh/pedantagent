import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page

@dataclass
class GameState:
    snapshot: str

class PedantixWebClient:
    def __init__(self, page: Page, guess_input: str, text_container: str):
        self.page = page
        self.guess_input = guess_input
        self.text_container = text_container

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_selector(self.guess_input, timeout=15_000)

    def guess(self, word: str) -> None:
        self.page.fill(self.guess_input, word)
        self.page.keyboard.press("Enter")

    def read_state(self) -> GameState:
        try:
            snap = self.page.inner_text(self.text_container)
        except Exception:
            snap = ""
        return GameState(snapshot=snap)

    def has_win_marker(self, win_marker_selector: Optional[str]) -> bool:
        if not win_marker_selector:
            return False
        try:
            return self.page.locator(win_marker_selector).count() > 0
        except Exception:
            return False
