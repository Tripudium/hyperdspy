import threading
from typing import Optional

from hyperdspy.models import BookSnapshot


class OrderBook:
    """Thread-safe container for L2 order book snapshots.

    Updated from WebSocket callbacks (background thread).
    Read from the strategy loop (main thread).

    Uses lock + immutable snapshot swap: writer constructs a frozen BookSnapshot,
    then swaps the dict reference under lock. Reader grabs the reference under lock
    and uses it freely afterward since BookSnapshot is immutable.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._books: dict[str, BookSnapshot] = {}

    def update(self, data: dict) -> None:
        """Called from WebSocket callback thread with raw SDK L2BookData."""
        snapshot = BookSnapshot.from_sdk(data)
        with self._lock:
            self._books[snapshot.coin] = snapshot

    def get(self, coin: str) -> Optional[BookSnapshot]:
        """Get the latest book snapshot for a coin. Returns None if no data yet."""
        with self._lock:
            return self._books.get(coin)

    def get_all(self) -> dict[str, BookSnapshot]:
        """Get all current book snapshots."""
        with self._lock:
            return dict(self._books)
