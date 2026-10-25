from collections import deque

class WaitingQueue:
    """FIFO queue for waiting-list operations."""
    def __init__(self):
        self.queue = deque()

    def enqueue(self, item):
        self.queue.append(item)

    def dequeue(self):
        return self.queue.popleft() if self.queue else None

    def peek(self):
        return self.queue[0] if self.queue else None

    def display(self):
        return list(self.queue)

    def __len__(self):
        return len(self.queue)
