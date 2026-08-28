from __future__ import annotations

from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter


@dataclass(slots=True, frozen=True)
class ParentChunk:
    parent_id: str
    text: str
    parent_index: int


@dataclass(slots=True, frozen=True)
class ChildChunk:
    parent_id: str
    parent_text: str
    text: str
    parent_index: int
    child_index: int


@dataclass(slots=True, frozen=True)
class HierarchicalChunkResult:
    parents: list[ParentChunk]
    children: list[ChildChunk]

    @property
    def parent_count(self) -> int:
        return len(self.parents)

    @property
    def child_count(self) -> int:
        return len(self.children)


class HierarchicalChunker:
    """Small-to-big chunker: large parent sections + focused child sub-chunks."""

    def __init__(
        self,
        *,
        parent_chunk_size: int = 900,
        parent_chunk_overlap: int = 100,
        child_chunk_size: int = 200,
        child_chunk_overlap: int = 40,
    ) -> None:
        if parent_chunk_size < child_chunk_size:
            raise ValueError("parent_chunk_size must be >= child_chunk_size")
        self._parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_chunk_size,
            chunk_overlap=parent_chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, content: str, *, document_id: str) -> HierarchicalChunkResult:
        text = (content or "").strip()
        if not text:
            return HierarchicalChunkResult(parents=[], children=[])

        parent_texts = self._parent_splitter.split_text(text)
        parents: list[ParentChunk] = []
        children: list[ChildChunk] = []

        for parent_index, parent_text in enumerate(parent_texts):
            parent_id = f"{document_id}::parent::{parent_index}"
            parents.append(
                ParentChunk(
                    parent_id=parent_id,
                    text=parent_text,
                    parent_index=parent_index,
                )
            )
            child_texts = self._child_splitter.split_text(parent_text)
            if not child_texts:
                child_texts = [parent_text]
            for child_index, child_text in enumerate(child_texts):
                children.append(
                    ChildChunk(
                        parent_id=parent_id,
                        parent_text=parent_text,
                        text=child_text,
                        parent_index=parent_index,
                        child_index=child_index,
                    )
                )

        return HierarchicalChunkResult(parents=parents, children=children)
