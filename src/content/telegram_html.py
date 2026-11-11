from html import escape

OPS_ORDER_TG_PARSE_MODE = "HTML"


def _escape_lines(lines: list[str]) -> str:
    return "\n".join(escape(line) for line in lines)


# Алерт ops: заголовок + тело в blockquote (аналог msg-header + msg-body).
def build_ops_alert_message(header: str, body_lines: list[str]) -> str:
    parts = [f"<b>{escape(header)}</b>", ""]
    if body_lines:
        parts.append(f"<blockquote>{_escape_lines(body_lines)}</blockquote>")
    return "\n".join(parts)


# Секционное ops-сообщение (новый заказ): заголовок + секции с blockquote.
def build_ops_section_message(
    header: str,
    sections: list[tuple[str, list[str]]],
) -> str:
    parts = [f"<b>{escape(header)}</b>", ""]
    for title, lines in sections:
        if not lines:
            continue
        parts.append(f"<b>{escape(title)}</b>")
        parts.append(f"<blockquote>{_escape_lines(lines)}</blockquote>")
        parts.append("")
    if parts and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)
