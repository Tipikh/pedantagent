import argparse

from playwright.sync_api import sync_playwright
from rich import print

from .agent import PedantAgent
from .config import Settings, Selectors
from .web_client import PedantixWebClient
from .words import warmup_words

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pedantagent", description="Polite Pedantix agent (rate-limited).")
    p.add_argument("--headless", action="store_true", help="Run browser headless.")
    p.add_argument("--max", type=int, default=200, help="Max guesses.")
    p.add_argument("--rate", type=float, default=1.0, help="Base seconds between guesses.")
    p.add_argument("--input", dest="guess_input", default=Selectors().guess_input, help="CSS selector for guess input.")
    p.add_argument("--title", dest="title_container", default=Selectors().title_container, help="CSS selector for title container.")
    p.add_argument("--article", dest="article_container", default=Selectors().article_container, help="CSS selector for article container.")
    p.add_argument("--win", dest="win_marker", default="", help="Optional CSS selector for win marker.")
    p.add_argument("--debug", action="store_true", help="Print game state info after each guess.")
    p.add_argument("--llm", action="store_true", help="Use an LLM to propose new guesses (dry-run unless wired).")
    p.add_argument("--llm-model", default="gpt-5-mini", help="Model name for LLM suggestions.")


    return p

def main() -> int:
    args = build_parser().parse_args()

    settings = Settings(
        headless=bool(args.headless),
        max_guesses=int(args.max),
        selectors=Selectors(
            guess_input=args.guess_input,
            title_container=args.title_container,
            article_container=args.article_container,
            win_marker=(args.win_marker or None),
        ),
        rate=Settings().rate.__class__(base_seconds=float(args.rate)),
    )

    words = warmup_words()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.headless)
        page = browser.new_page()

        client = PedantixWebClient(
            page=page,
            guess_input=settings.selectors.guess_input,
            title_container=settings.selectors.title_container,
            article_container=settings.selectors.article_container,
        )
        client.open(settings.url)

        agent = PedantAgent(
            client=client,
            rate=settings.rate,
            win_marker_selector=settings.selectors.win_marker,
            debug=args.debug,
            llm_enabled=args.llm,
            llm_model=args.llm_model,
        )

        print(f"[bold]pedantagent[/bold] — headless={settings.headless}, max={settings.max_guesses}, rate~{settings.rate.base_seconds}s")
        res = agent.run(words=words, max_guesses=settings.max_guesses)

        print(f"Done. guesses={res.guesses_made} solved={res.solved}")
        browser.close()

    return 0
