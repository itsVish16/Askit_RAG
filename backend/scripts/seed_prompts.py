"""Seed the app's prompts into Opik's prompt library (one versioned commit each).

Code is the source of truth for prompt text (app/core/prompts.py); this script
pushes a new commit to each prompt's Opik history so every wording change is
tracked and diffable in the UI. If the Opik text for a name is unchanged,
create_prompt() records no new commit. Opik prompts use mustache placeholders,
so langchain-style {question}/{context}/{n} variables become {{question}} etc.

Run:  uv run python -m scripts.seed_prompts
(optional --commit to read back the latest stored commit id per prompt)
"""

import argparse

from opik import Opik

from app.core.prompts import PROMPT_SPECS

PROMPT_METADATA = {
    "askit-rag-generation": "Answer generation over retrieved context (chat format).",
    "askit-keyword-extraction": "BM25 keyword/entity extraction for lexical retrieval.",
    "askit-multi-query": "Multi-query expansion for dense retrieval.",
}


def _to_mustache(system: str, human: str) -> str:
    """Convert our chat prompt to a flat mustache template for Opik.

    Keeps the role structure readable so the versioned text mirrors the code.
    """
    def s(t: str) -> str:
        for var in ("context", "question", "n"):
            t = t.replace("{" + var + "}", "{{" + var + "}}")
        return t

    return f"system:\n{s(system)}\n\nuser:\n{s(human)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--commit",
        action="store_true",
        help="print each prompt's latest commit id after seeding",
    )
    args = parser.parse_args()

    client = Opik()
    for name, system_text, human_template in PROMPT_SPECS:
        client.create_prompt(
            name=name,
            prompt=_to_mustache(system_text, human_template),
            metadata={
                "description": PROMPT_METADATA[name],
                "source": "app/core/prompts.py",
            },
        )
        print(f"Seeded prompt '{name}' to Opik.")
        if args.commit:
            stored = client.get_prompt(name)
            print(f"  latest commit: {stored.commit}")
    print("Done. Unchanged text is skipped; changed text becomes a new version.")


if __name__ == "__main__":
    main()
