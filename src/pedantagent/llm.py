from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from openai import OpenAI


# --------- JSON schema for structured outputs ---------

_PEDANTIX_WORDS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "pedantix_word_suggestions",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "words": {
                    "type": "array",
                    "minItems": 10,
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 2},
                }
            },
            "required": ["words"],
        },
    },
}


# --------- Prompt building ---------

def build_pedantix_prompt(
    *,
    title_text: str,
    article_text: str,
    tested_words: Sequence[str],
    max_article_chars: int = 4_000,
) -> str:
    """
    Build a prompt designed for Pedantix word suggestions.

    We intentionally:
    - include a short tested_words list to avoid duplicates
    - keep the output format instruction strict (JSON only)
    """
    tested = ", ".join(tested_words)

    article = article_text
    if len(article) > max_article_chars:
        article = article[:max_article_chars] + "\n…(tronqué)"

    return f"""Tu aides à résoudre un jeu appelé Pedantix.

OBJECTIF
Identifier le TITRE d’un article Wikipédia en proposant des mots pertinents à tester.

RÈGLES
- Le texte correspond au DÉBUT d’un article Wikipédia.
- Mots cachés: ⟦wXX~N⟧ (N = longueur approximative)
- Les mots visibles sont déjà découverts.

ÉTAT ACTUEL

TITRE :
{title_text}

ARTICLE :
{article}

MOTS DÉJÀ TESTÉS (NE PAS PROPOSER) :
{tested}

CONTRAINTES STRICTES
- Ne propose PAS de mots déjà visibles dans le texte.
- Ne propose PAS de mots déjà testés.
- Évite les mots grammaticaux/génériques.
- Noms propres autorisés. Français uniquement. Tous distincts.

TÂCHE
Propose exactement 10 mots pertinents à tester ensuite.

FORMAT DE RÉPONSE (OBLIGATOIRE)
Réponds STRICTEMENT sous forme JSON, avec UNE SEULE clé "words" (liste de 10 chaînes),
et AUCUN autre texte.
"""


# --------- Post-processing / safety filtering ---------

_WORD_RE = re.compile(r"^[a-zA-ZÀ-ÖØ-öø-ÿ'\-]+$")

def normalize_word(w: str) -> str:
    """Normalize a candidate word to what you will actually type in Pedantix."""
    w = w.strip().lower()
    # Keep letters, apostrophes and hyphens; remove surrounding punctuation.
    w = w.strip(" \t\r\n.,;:!?\"()[]{}")
    return w

def filter_words(
    words: Iterable[str],
    *,
    tested: set[str],
    revealed: set[str],
    min_len: int = 3,
) -> List[str]:
    """
    Defensive filter in case the model returns duplicates or invalid tokens.
    """
    out: List[str] = []
    seen: set[str] = set()

    for raw in words:
        w = normalize_word(raw)
        if not w:
            continue
        if len(w) < min_len:
            continue
        if w in tested or w in revealed:
            continue
        if w in seen:
            continue
        if not _WORD_RE.match(w):
            continue

        out.append(w)
        seen.add(w)

    return out


# --------- LLM client ---------

@dataclass(frozen=True)
class PedantixSuggestions:
    words: List[str]
    raw_json: str
    prompt: str


class PedantixLLM:
    def __init__(self, client: OpenAI, model: str = "gpt-5-nano"):
        self.client = client
        self.model = model

    def suggest_words(
        self,
        *,
        title_text: str,
        article_text: str,
        tested_words: Sequence[str],
        revealed_words: Sequence[str],
    ) -> PedantixSuggestions:
        prompt = build_pedantix_prompt(
            title_text=title_text,
            article_text=article_text,
            tested_words=tested_words,
        )

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format=_PEDANTIX_WORDS_SCHEMA,
            max_completion_tokens=200,
        )

        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)

        tested = {normalize_word(w) for w in tested_words}
        revealed = {normalize_word(w) for w in revealed_words}

        filtered = filter_words(
            data.get("words", []),
            tested=tested,
            revealed=revealed,
            min_len=3,
        )

        return PedantixSuggestions(words=filtered, raw_json=raw, prompt=prompt)
