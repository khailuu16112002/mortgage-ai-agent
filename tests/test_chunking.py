"""Unit tests for the chunking pipeline."""
import pytest
from pipelines.chunking import RecursiveTextSplitter, DocumentChunker, count_tokens, DocumentChunk


class TestRecursiveTextSplitter:
    def setup_method(self):
        self.splitter = RecursiveTextSplitter(chunk_size=200, chunk_overlap=30, min_chunk=10)

    def test_short_text_returns_single_chunk(self):
        text = "This is a short document."
        chunks = self.splitter.split(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_into_multiple(self):
        text = "\n\n".join([f"Paragraph {i}: " + "word " * 30 for i in range(10)])
        chunks = self.splitter.split(text)
        assert len(chunks) > 1

    def test_chunks_respect_max_size(self):
        text = "word " * 1000
        chunks = self.splitter.split(text)
        # With overlap, chunks can be up to 2x chunk_size (overlap prepended)
        max_allowed = self.splitter.chunk_size * 2 + 10
        for chunk in chunks:
            assert len(chunk) <= max_allowed, f"Chunk too long: {len(chunk)}"

    def test_empty_text_returns_empty(self):
        chunks = self.splitter.split("")
        assert chunks == []

    def test_min_chunk_filter(self):
        text = "Hi\n\n" + "word " * 100
        chunks = self.splitter.split(text)
        for chunk in chunks:
            assert len(chunk.strip()) >= self.splitter.min_chunk


class TestCountTokens:
    def test_basic_count(self):
        text = "Hello world this is a test sentence."
        count = count_tokens(text)
        assert count > 0
        assert count < 50

    def test_empty_text(self):
        assert count_tokens("") == 0

    def test_longer_text_more_tokens(self):
        short = "Hello world."
        long = "Hello world. " * 100
        assert count_tokens(long) > count_tokens(short)


class TestDocumentChunker:
    def setup_method(self):
        self.chunker = DocumentChunker()

    def test_chunk_text_basic(self):
        text = "\n\n".join([f"Section {i}: " + "content word " * 50 for i in range(5)])
        chunks = self.chunker.chunk_text(text, "test.txt", domain="test", doc_type="test")
        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, DocumentChunk)
            assert chunk.source_file == "test.txt"
            assert chunk.domain == "test"
            assert chunk.token_count > 0

    def test_chunk_preserves_metadata(self):
        text = "word " * 200
        chunks = self.chunker.chunk_text(text, "sample.pdf", domain="borrower", doc_type="driver_license")
        assert all(c.domain == "borrower" for c in chunks)
        assert all(c.doc_type == "driver_license" for c in chunks)

    def test_chunk_indices_sequential(self):
        text = "sentence number one. " * 200
        chunks = self.chunker.chunk_text(text, "doc.pdf")
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(indices)))

    def test_chunk_ids_unique(self):
        text = "content " * 300
        chunks = self.chunker.chunk_text(text, "doc.pdf")
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))  # all unique

    def test_max_chunks_cap(self):
        # Generate text that would produce many chunks
        text = "word " * 10000
        chunks = self.chunker.chunk_text(text, "large.pdf")
        assert len(chunks) <= self.chunker.max_chunks
