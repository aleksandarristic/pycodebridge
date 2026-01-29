"""Chunking helpers for Discord output limits."""


def chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks that respect a maximum length."""
    if max_len <= 0:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf_len
        if buf:
            chunks.append("\n".join(buf))
            buf.clear()
            buf_len = 0

    for line in text.split("\n"):
        line_len = len(line)
        # Account for newline if buffer not empty
        extra = 1 if buf else 0
        if buf and buf_len + extra + line_len > max_len:
            flush()
        if line_len <= max_len:
            buf.append(line)
            buf_len += line_len + (1 if buf_len > 0 else 0)
            continue
        # Line longer than max; hard break
        start = 0
        while start < line_len:
            end = min(start + max_len, line_len)
            if buf:
                flush()
            buf.append(line[start:end])
            buf_len = end - start
            flush()
            start = end
    flush()
    return chunks
