from dotenv import load_dotenv 
load_dotenv()
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

    def _reveal_ratio(self, state: GameState) -> float:
        total_tokens = state.title_token_count + state.article_token_count
        total_revealed = state.title_revealed_count + state.article_revealed_count
        return (total_revealed / total_tokens) if total_tokens else 0.0
    
    def _debug_print(self, guess: str, state: GameState) -> None:
        reveal_ratio = self._reveal_ratio(state)
        top_hints = ", ".join(f"{h.word}:{h.score:.2f}" for h in state.hint_words[:5])
        print(
            f"guess='{guess}' | "
            f"title={state.title_revealed_count}/{state.title_token_count} | "
            f"article={state.article_revealed_count}/{state.article_token_count} | "
            f"reveal_ratio={reveal_ratio:.2%} | "
            f"revealed={len(state.revealed_words)} | "
            f"new_ids={len(state.new_reveal_ids)} | "
            f"hints=[{top_hints}]"
        )


    def run(self, words: Iterable[str], max_guesses: int = 200, reveal_threshold: float = 0.10,llm_batch_size: int = 10,) -> RunResult:
        guesses = 0
        warmup_iter = iter(words)
        mode = "warmup"
        pending_llm_words: list[str] = []

        while True:
            w: Optional[str] = None
            if mode == "warmup":
                try:
                    w = next(warmup_iter)
                except StopIteration:
                    mode = "llm"
                    if self.debug:
                        print("[LLM] Switching to LLM mode (warmup exhausted).")
                    continue
            else:
                print("LLM mode (Test à suppr).")
                if not pending_llm_words:
                    print("Not pending llm words (Test à suppr).")
                    if not (self.llm_enabled and self.llm):
                        return RunResult(guesses_made=guesses, solved=False)
                    state = self.client.read_state()
                    
                    sugg = self.llm.suggest_words(
                        title_text=state.title_text,
                        article_text=state.article_text,
                        tested_words=sorted(self.tested),
                        revealed_words=list(state.revealed_words),
                    )
                    pending_llm_words = list(sugg.words[:llm_batch_size])
                    print(f"PENDING LLM WOOOOOORD : {sugg}  OKOK   (Test à suppr).")
                    if self.debug:
                        print("LLM suggestions:", pending_llm_words)
                    if not pending_llm_words:
                        return RunResult(guesses_made=guesses, solved=False)
                w = pending_llm_words.pop(0)

            if w is None:
                continue
            
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
                print("ARTICLE:", state.article_text)
                print("-" * 80)


            if self._is_solved(state):
                return RunResult(guesses_made=guesses, solved=True)

            if mode == "warmup" and (self._reveal_ratio(state) >= reveal_threshold or w == words[-1]) :
                mode = "llm"
                pending_llm_words = []
