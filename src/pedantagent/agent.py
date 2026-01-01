import random
import time
import os
from dataclasses import dataclass
from typing import Iterable, Optional
from openai import OpenAI

from .llm import PedantixLLM
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
        debug: bool = False,
        llm_enabled: bool = False,
        llm_model: str = "gpt-5-mini",
    ):
        self.client = client
        self.rate = rate
        self.win_marker_selector = win_marker_selector
        self.debug = debug
        self.tested: set[str] = set()
        self.llm_enabled = llm_enabled
        self.llm: PedantixLLM | None = None
        if llm_enabled:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self.llm = PedantixLLM(OpenAI(api_key=api_key), model=llm_model)

    def _sleep(self) -> None:
        dt = self.rate.base_seconds + random.uniform(self.rate.jitter_min, self.rate.jitter_max)
        time.sleep(max(0.0, dt))

    def _is_solved(self, state: GameState) -> bool:
        if self.client.has_win_marker(self.win_marker_selector):
            return True
        low = (state.title_text + " " + state.article_text).lower()
        return ("bravo" in low) or ("gagn" in low)
    
    def _debug_print(self, guess: str, state) -> None:
        top_hints = ", ".join(f"{h.word}:{h.score:.2f}" for h in state.hint_words[:5])
        print(
            f"guess='{guess}' | "
            f"title={state.title_revealed_count}/{state.title_token_count} | "
            f"revealed={len(state.revealed_words)} | "
            f"new_ids={len(state.new_reveal_ids)} | "
            f"hints=[{top_hints}]"
        )


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
            
            if self.debug:
                self._debug_print(w, state)
                print("TITLE:", state.title_text)
                print("ARTICLE (first 2000 chars):", state.article_text[:2000])
                print("-" * 80)
                if self.llm_enabled and self.llm:
                    sugg = self.llm.suggest_words(
                        title_text=state.title_text,
                        article_text=state.article_text,
                        tested_words=sorted(self.tested),
                        revealed_words=list(state.revealed_words),
                    )
                    print("LLM suggestions:", sugg.words)


            if self._is_solved(state):
                return RunResult(guesses_made=guesses, solved=True)

        return RunResult(guesses_made=guesses, solved=False)
