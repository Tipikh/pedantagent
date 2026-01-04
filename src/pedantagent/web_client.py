from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .config import Settings, Selectors
from playwright.sync_api import Page


# --- Style constants observed in Pedantix UI ---
DEFAULT_TEXT_COLOR = "rgb(32, 33, 34)"
HIGHLIGHT_GREEN_BG = "rgb(102, 238, 102)"


@dataclass(frozen=True)
class HintWord:
    """A word shown as a semantic hint (yellow/orange/red)."""
    word: str
    score: float  # higher => "more yellow" (closer), heuristic


@dataclass(frozen=True)
class GameState:
    """Structured state extracted from the DOM."""
    title_text: str
    article_text: str

    revealed_words: Tuple[str, ...]
    hint_words: Tuple[HintWord, ...]

    title_revealed_count: int
    title_token_count: int
    article_revealed_count: int
    article_token_count: int

    # IDs of spans currently highlighted in green (newly revealed during last guess)
    new_reveal_ids: Tuple[int, ...]

    solved: bool
    solution_url: Optional[str]

class PedantixWebClient:
    """
    Thin client for the Pedantix web UI.

    Responsibilities:
    - open the game page
    - submit guesses
    - read a structured state (title + article tokens, revealed words, semantic hints)
    """

    def __init__(self, page: Page,  selectors: Selectors):
        self.page = page
        self.guess_input = selectors.guess_input
        self.title_container = selectors.title_container
        self.article_container = selectors.article_container

    def open(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_selector(self.guess_input, timeout=15_000)
        # Ensure game DOM is present too
        self.page.wait_for_selector(self.title_container, timeout=15_000)
        self.page.wait_for_selector(self.article_container, timeout=15_000)

    def guess(self, word: str) -> None:
        self.page.fill(self.guess_input, word)
        self.page.keyboard.press("Enter")

    def read_state(self) -> GameState:
        """
        Reads and classifies all #wiki h2 span.w and #article span.w tokens.
        Uses one JS evaluation for performance.
        """
        payload = self.page.evaluate(
            """
            ({ titleSel, articleSel }) => {
            function normText(s) {
                if (!s) return "";
                return s.replace(/\\u00A0/g, " ").replace(/\\s+/g, " ").trim();
            }
            
            function countHiddenLen(el) {
                const s = el.textContent || "";
                const nbspCount = (s.match(/\\u00A0/g) || []).length;
                const spaceCount = (s.match(/ /g) || []).length;
                return Math.max(nbspCount, spaceCount);
}

            function readSpan(el, inTitle) {
                const raw = el.textContent || "";
                const text = normText(el.innerText);
                const cs = window.getComputedStyle(el);                
                const isHidden = !text.length;   // après normalisation
                const hiddenLen = isHidden ? countHiddenLen(el) : null;

                return {
                id: el.id ? Number(el.id) : null,
                text: text.length ? text : null,
                inTitle: Boolean(inTitle),
                color: cs.color || "",
                backgroundColor: cs.backgroundColor || "",
                boxShadow: cs.boxShadow || "",
                hiddenLen,
                };
            }

            const titleRoot = document.querySelector(titleSel);
            const articleRoot = document.querySelector(articleSel);

            const titleSpans = titleRoot
                ? Array.from(titleRoot.querySelectorAll("span.w")).map(el => readSpan(el, true))
                : [];

            const articleSpans = articleRoot
                ? Array.from(articleRoot.querySelectorAll("span.w")).map(el => readSpan(el, false))
                : [];

            // solved detection 
            const solutionLink = document.querySelector("#success a#solution a[href]");
            const solutionHref = solutionLink ? solutionLink.getAttribute("href") : null;
            
            return { titleSpans, articleSpans, solutionHref };
            }
            """,
            {
                "titleSel": self.title_container,
                "articleSel": self.article_container,
            },
        )


        title_tokens = payload.get("titleSpans", [])
        article_tokens = payload.get("articleSpans", [])
        solution_url = payload.get("solutionHref") or None
        solved = solution_url is not None

        # Build a readable title/article text with placeholders for hidden words
        title_text, title_revealed_count, title_token_count, title_revealed_words, title_hints, title_new = (
            self._process_tokens(title_tokens)
        )
        (
            article_text,
            article_revealed_count,
            article_token_count,
            article_revealed_words,
            article_hints,
            article_new,
        ) = self._process_tokens(article_tokens)

        # Merge & dedupe revealed words (keep order stable-ish by using dict)
        revealed_words = tuple(dict.fromkeys([*title_revealed_words, *article_revealed_words]).keys())

        # Merge hints (dedupe by word, keep best score)
        hint_map: dict[str, float] = {}
        for hw in [*title_hints, *article_hints]:
            prev = hint_map.get(hw.word)
            if prev is None or hw.score > prev:
                hint_map[hw.word] = hw.score
        hint_words = tuple(sorted((HintWord(w, s) for w, s in hint_map.items()), key=lambda x: x.score, reverse=True))

        new_reveal_ids = tuple(sorted(set([*title_new, *article_new])))

        return GameState(
            title_text=title_text,
            article_text=article_text,
            revealed_words=revealed_words,
            hint_words=hint_words,
            title_revealed_count=title_revealed_count,
            title_token_count=title_token_count,
            article_revealed_count=article_revealed_count,
            article_token_count=article_token_count,
            new_reveal_ids=new_reveal_ids,
            solved=solved,
            solution_url=solution_url         
        )

    # -----------------------
    # Internal helpers
    # -----------------------

    @staticmethod
    def _process_tokens(tokens: Sequence[dict]) -> Tuple[str, int, int, list[str], list[HintWord], list[int]]:
        """
        From raw token dicts, returns:
        - reconstructed text (with '____' placeholders)
        - revealed_count
        - token_count
        - revealed_words (list)
        - hint_words (list with score)
        - new_reveal_ids (green highlight ids)
        """
        words_out: list[str] = []
        revealed_words: list[str] = []
        hint_words: list[HintWord] = []
        new_reveal_ids: list[int] = []

        token_count = 0
        revealed_count = 0

        for t in tokens:
            token_count += 1

            token_id = t.get("id")
            text = t.get("text")          # None si caché
            hidden_len = t.get("hiddenLen")
            color = (t.get("color") or "").strip()
            bg = (t.get("backgroundColor") or "").strip()
            in_title = bool(t.get("inTitle"))

            prefix = "t" if in_title else "w"

            # --- Cas 1 : mot totalement caché ---
            if text is None:
                words_out.append(
                    PedantixWebClient._placeholder(token_id, hidden_len, prefix)
                )
                continue

            # --- Cas 2 : mot visible mais seulement comme hint (orange/rouge) ---
            if PedantixWebClient._looks_like_hint(color):
                words_out.append(
                    PedantixWebClient._placeholder(token_id, hidden_len, prefix)
                )
                hint_words.append(
                    HintWord(
                        word=text.lower(),
                        score=PedantixWebClient._hint_score_from_color(color),
                    )
                )
                continue

            # --- Cas 3 : vrai mot révélé ---
            words_out.append(text)

            # "New reveal" highlight (temporary green)
            if bg == HIGHLIGHT_GREEN_BG and isinstance(token_id, int):
                new_reveal_ids.append(token_id)

            # Decide if it's likely a semantic hint (colored orange/red) vs a normal revealed word
            if PedantixWebClient._looks_like_hint(color):
                hint_words.append(HintWord(word=text.lower(), score=PedantixWebClient._hint_score_from_color(color)))
            else:
                revealed_count += 1
                revealed_words.append(text.lower())

        reconstructed = PedantixWebClient._reconstruct_text(words_out)
        return reconstructed, revealed_count, token_count, revealed_words, hint_words, new_reveal_ids

    @staticmethod
    def _reconstruct_text(words: Sequence[str]) -> str:
        """
        Simple text reconstruction. Keeps it readable; not intended to be a perfect Wikipedia paragraph.
        We avoid complicated punctuation rules for clarity.
        """
        return " ".join(words)
    
    @staticmethod
    def _placeholder(
        token_id: Optional[int],
        hidden_len: Optional[int],
        prefix: str = "w",
    ) -> str:
        """
        Build a stable placeholder for hidden or hinted tokens.

        Example:
          ⟦w29~7⟧  -> word token id 29, approx length 7
          ⟦t3⟧     -> title token id 3, unknown length
        """
        tid = token_id if token_id is not None else -1
        if hidden_len and hidden_len > 0:
            return f"⟦{prefix}{tid}~{hidden_len}⟧"
        return f"⟦{prefix}{tid}⟧"

    @staticmethod
    def _looks_like_hint(color: str) -> bool:
        """
        Heuristic:
        - revealed/default text tends to be rgb(32,33,34)
        - hints are colored (orange/red/yellow) and thus different
        """
        return bool(color) and color != DEFAULT_TEXT_COLOR

    @staticmethod
    def _hint_score_from_color(color: str) -> float:
        """
        Convert an rgb(r,g,b) string to a heuristic "yellow-ness" score in [0, 1].
        You observed: yellow = closer, red = less close.
        Yellow ≈ high R, high G, low B.
        """
        rgb = PedantixWebClient._parse_rgb(color)
        if rgb is None:
            return 0.0
        r, g, b = rgb
        # Normalize to 0..1
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        # "Yellow-ness": reward R and G, penalize B; also penalize very low G (red-ish)
        score = (rf + gf) / 2.0 - 0.5 * bf
        # Clamp
        return max(0.0, min(1.0, score))

    @staticmethod
    def _parse_rgb(s: str) -> Optional[Tuple[int, int, int]]:
        """
        Parse 'rgb(r, g, b)' strings. Returns (r,g,b) or None.
        """
        s = s.strip()
        if not s.startswith("rgb(") or not s.endswith(")"):
            return None
        inner = s[4:-1]
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) < 3:
            return None
        try:
            r = int(float(parts[0]))
            g = int(float(parts[1]))
            b = int(float(parts[2]))
            return (r, g, b)
        except ValueError:
            return None
