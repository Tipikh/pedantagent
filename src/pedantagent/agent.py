import random
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .config import RateLimit
from .web_client import PedantixWebClient, GameState

@dataclass
class RunResult:
    guesses_made: int
    solved: bool

class PedantAgent:
    def __init__(
        self,
        client: PedantixWebClient,
        rate: RateLimit,
        win_marker_selector: Optional[str] = None,
    ):
        self.client = client
        self.rate = rate
        self.win_marker_selector = win_marker_selector
        self.tested: set[str] = set()

    def _sleep(self) -> None:
        dt = self.rate.base_seconds + random.uniform(self.rate.jitter_min, self.rate.jitter_max)
        time.sleep(max(0.0, dt))

    def _is_solved(self, state: GameState) -> bool:
        if self.client.has_win_marker(self.win_marker_selector):
            return True
        low = state.snapshot.lower()
        return ("bravo" in low) or ("gagn" in low)

    def run(self, words: Iterable[str], max_guesses: int = 200) -> RunResult:
        guesses = 0
        for w in words:
            w = w.strip()
            if not w or w in self.tested:
                continue

            guesses += 1
            if guesses > max_guesses:
                return RunResult(guesses_made=guesses - 1, solved=False)

            self.tested.add(w)
            self.client.guess(w)
            self._sleep()
            state = self.client.read_state()

            if self._is_solved(state):
                return RunResult(guesses_made=guesses, solved=True)

        return RunResult(guesses_made=guesses, solved=False)
