"""
Data Structures & Algorithms (DSA) — Queue Abstract Data Type (ADT)
===================================================================

Academic Definition:
--------------------
A Queue is a linear data structure that operates according to the
First-In, First-Out (FIFO) principle. Elements are added at the rear
(enqueue) and removed or serviced from the front (dequeue).

Why Database Persistence is Required over pure In-Memory Queue:
--------------------------------------------------------------
In production web servers (e.g., multi-worker WSGI/Gunicorn), each process
has isolated memory. A Python `collections.deque` exists only in the RAM
of a single worker process. If the server restarts or worker processes cycle,
all in-memory requests are permanently lost.

Therefore, SmartLib's `PersistentBookQueue` uses the database as the persistent
source of truth, maintaining strict FIFO ordering:
    ORDER BY created_at ASC, reservation_id ASC
"""

from collections import deque
from typing import Any, Optional, List


class WaitingQueue:
    """In-memory Queue ADT implementation using a doubly-linked ring buffer (collections.deque).

    Time Complexities:
    - Enqueue: O(1)
    - Dequeue: O(1)
    - Peek: O(1)
    - Length: O(1)
    """

    def __init__(self):
        self._queue = deque()

    def enqueue(self, item: Any) -> None:
        """Appends an element to the rear of the queue (FIFO enqueue)."""
        self._queue.append(item)

    def dequeue(self) -> Optional[Any]:
        """Removes and returns the front element of the queue (FIFO dequeue)."""
        return self._queue.popleft() if self._queue else None

    def peek(self) -> Optional[Any]:
        """Returns the front element of the queue without removing it (FIFO peek)."""
        return self._queue[0] if self._queue else None

    def display(self) -> List[Any]:
        """Returns a list representation of the queue from front to rear."""
        return list(self._queue)

    def is_empty(self) -> bool:
        """Checks whether the queue contains zero elements."""
        return len(self._queue) == 0

    def __len__(self) -> int:
        return len(self._queue)


class PersistentBookQueue:
    """Database-backed FIFO Queue ADT for book reservations.
    Delegates queue mutations to the persistent database layer, guaranteeing:
    1. Durability across server restarts.
    2. Multi-worker process synchronization.
    3. Transactional consistency.
    """

    def __init__(self, book_id: int):
        self.book_id = book_id

    def enqueue(self, student_id: int):
        import reservation_service
        return reservation_service.enqueue_reservation_sql(self.book_id, student_id)

    def peek(self):
        import reservation_service
        return reservation_service.peek_next_reservation_sql(self.book_id)

    def dequeue(self, hold_hours: Optional[int] = None):
        import reservation_service
        return reservation_service.dequeue_next_reservation_sql(self.book_id, hold_hours)

    def get_position(self, reservation_id: int) -> int:
        import reservation_service
        from models import Reservation
        from database import db
        res = db.session.get(Reservation, reservation_id)
        if not res:
            return 0
        return reservation_service.get_queue_position_sql(res)

    def size(self) -> int:
        import reservation_service
        return reservation_service.get_waiting_count_sql(self.book_id)
