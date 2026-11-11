def catalog_total_pages(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


def pagination_page_window(current: int, total: int, *, size: int = 5) -> list[int]:
    if total <= size:
        return list(range(1, total + 1))
    half = size // 2
    start = max(1, current - half)
    end = min(total, start + size - 1)
    start = max(1, end - size + 1)
    return list(range(start, end + 1))
