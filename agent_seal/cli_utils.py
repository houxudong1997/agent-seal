"""Terminal formatting utilities."""

# ANSI color codes (cross-platform safe subset)
C = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


def ok(msg="OK"):
    return f"{C['green']}✓ {msg}{C['reset']}"


def fail(msg="FAIL"):
    return f"{C['red']}✗ {msg}{C['reset']}"


def warn(msg=""):
    return f"{C['yellow']}⚠ {msg}{C['reset']}"


def info(msg=""):
    return f"{C['cyan']}{msg}{C['reset']}"


def dim(msg=""):
    return f"{C['dim']}{msg}{C['reset']}"


def bold(msg=""):
    return f"{C['bold']}{msg}{C['reset']}"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple text table."""
    cols = len(headers)
    widths = [
        max(len(h), *(len(str(r[i])) for r in rows if i < len(r))) for i, h in enumerate(headers)
    ]
    sep = "  "
    header_line = sep.join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    divider = sep.join("─" * w for w in widths)
    body = "\n".join(
        sep.join(
            str(r[i]).ljust(widths[i]) if i < len(r) else "".ljust(widths[i]) for i in range(cols)
        )
        for r in rows
    )
    return f"{bold(header_line)}\n{dim(divider)}\n{body}"


def progress_bar(current: int, total: int, width: int = 30) -> str:
    """Render a progress bar."""
    pct = min(current / max(total, 1), 1.0)
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:.0%}"
