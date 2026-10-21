def linear_search(books, keyword):
    keyword = keyword.strip().lower()
    if not keyword:
        return books
    return [
        book for book in books
        if keyword in book.title.lower()
        or keyword in book.author.lower()
        or keyword in (book.isbn or "").lower()
    ]


def binary_search_by_isbn(sorted_books, isbn):
    target = isbn.strip().lower()
    low, high = 0, len(sorted_books) - 1

    while low <= high:
        mid = (low + high) // 2
        value = (sorted_books[mid].isbn or "").lower()
        if value == target:
            return sorted_books[mid]
        if value < target:
            low = mid + 1
        else:
            high = mid - 1
    return None
