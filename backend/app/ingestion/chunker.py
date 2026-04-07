"""Factory that returns the LangChain text splitter configured by CHUNKING_STRATEGY.

Tradeoff documentation (referenced in README "Retrieval Design Decisions"):

  fixed (CharacterTextSplitter)
    Splits on a single separator ("\n") at a fixed character count.
    Predictable token budget — useful as a reproducible baseline.
    Downside: may split mid-sentence, breaking semantic coherence and
    causing the retriever to surface partial answers.

  recursive (RecursiveCharacterTextSplitter)  ← default
    Tries to split on paragraph boundaries first ("\n\n"), then line
    breaks, then sentence endings, then spaces.  Respects the natural
    section structure of HR policy documents (numbered paragraphs,
    bullet lists) which makes retrieved chunks far more self-contained.
    Slight runtime overhead vs fixed, but meaningfully better precision.
"""
from langchain_text_splitters import (
    CharacterTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import settings


def get_splitter() -> CharacterTextSplitter | RecursiveCharacterTextSplitter:
    """Return the configured text splitter instance.

    Reads CHUNKING_STRATEGY, CHUNK_SIZE, and CHUNK_OVERLAP from settings.
    """
    if settings.chunking_strategy == "fixed":
        return CharacterTextSplitter(
            separator="\n",
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )
