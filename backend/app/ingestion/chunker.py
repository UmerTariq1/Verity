"""Factory that returns the LangChain text splitter configured by CHUNKING_STRATEGY.

Tradeoff documentation (referenced in README "Retrieval Design Decisions"):

  fixed (CharacterTextSplitter)
    Splits on a single separator ("\n") at a fixed character count.
    Predictable token budget , useful as a reproducible baseline.
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


def get_splitter(
    *,
    strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> CharacterTextSplitter | RecursiveCharacterTextSplitter:
    """Return the configured text splitter instance.

    Reads CHUNKING_STRATEGY, CHUNK_SIZE, and CHUNK_OVERLAP from settings.
    """
    _strategy = (strategy or settings.chunking_strategy).strip().lower()
    _chunk_size = int(chunk_size if chunk_size is not None else settings.chunk_size)
    _chunk_overlap = int(chunk_overlap if chunk_overlap is not None else settings.chunk_overlap)

    if _chunk_size < 64 or _chunk_size > 4096:
        raise ValueError("chunk_size must be between 64 and 4096")
    if _chunk_overlap < 0 or _chunk_overlap > 512:
        raise ValueError("chunk_overlap must be between 0 and 512")
    if _chunk_overlap >= _chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    if _strategy == "fixed":
        return CharacterTextSplitter(
            separator="\n",
            chunk_size=_chunk_size,
            chunk_overlap=_chunk_overlap,
            length_function=len,
            is_separator_regex=False,
        )

    return RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", ". ", " "],
        chunk_size=_chunk_size,
        chunk_overlap=_chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )
