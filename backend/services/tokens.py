"""Rough token estimation for context-window warnings (no tokenizer dependency)."""

# ~4 chars/token is a reasonable average for English prose with Qwen/Llama tokenizers.
CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def context_warning(label: str, prompt_text: str, *, num_ctx: int, output_reserve: int) -> str | None:
    """Return a warning if prompt + reserved output likely exceeds the model's context window."""
    needed = estimate_tokens(prompt_text) + output_reserve
    if needed <= num_ctx:
        return None
    return (
        f"{label} needs roughly {needed} tokens but NUM_CTX is {num_ctx}; "
        "the model may silently truncate it. Increase NUM_CTX (if your hardware allows) or shorten the document."
    )
