from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Selectors:
    # À ajuster après (F12/Inspect)
    guess_input: str = "input"
    text_container: str = "body"
    win_marker: Optional[str] = None  # ex: ".win" si tu trouves un marqueur stable

@dataclass(frozen=True)
class RateLimit:
    base_seconds: float = 1.0
    jitter_min: float = -0.10
    jitter_max: float = 0.20

@dataclass(frozen=True)
class Settings:
    url: str = "https://pedantix.certitudes.org/"
    headless: bool = False
    max_guesses: int = 200
    selectors: Selectors = Selectors()
    rate: RateLimit = RateLimit()
