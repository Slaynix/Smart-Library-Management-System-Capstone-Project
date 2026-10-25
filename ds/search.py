def get_val(item, key):
    if isinstance(item, dict):
        return item.get(key, "") or ""
    return getattr(item, key, "") or ""


def linear_search(books, keyword):
    keyword = keyword.strip().lower()
    if not keyword:
        return books
    return [
        book for book in books
        if keyword in str(get_val(book, "title")).lower()
        or keyword in str(get_val(book, "author")).lower()
        or keyword in str(get_val(book, "isbn")).lower()
    ]


def binary_search_by_isbn(sorted_books, isbn):
    target = isbn.strip().lower()
    low, high = 0, len(sorted_books) - 1

    while low <= high:
        mid = (low + high) // 2
        value = str(get_val(sorted_books[mid], "isbn")).lower()
        if value == target:
            return sorted_books[mid]
        if value < target:
            low = mid + 1
        else:
            high = mid - 1
    return None
