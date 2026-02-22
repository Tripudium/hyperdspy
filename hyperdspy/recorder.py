import csv
import io
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from hyperdspy.config import RecordingConfig
from hyperdspy.models import BookSnapshot

logger = logging.getLogger(__name__)


class RecordWriter(Protocol):
    """Protocol for pluggable output writers."""

    def write(self, record: dict) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


class JsonLinesWriter:
    """Writes one JSON object per line to a file."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a")

    def write(self, record: dict) -> None:
        self._file.write(json.dumps(record, default=str) + "\n")

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class CsvWriter:
    """Writes records as CSV rows. Columns are determined from the first record."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._file: Optional[io.TextIOWrapper] = None
        self._writer: Optional[csv.DictWriter] = None
        self._columns: Optional[list[str]] = None

    def write(self, record: dict) -> None:
        if self._writer is None:
            self._columns = list(record.keys())
            file_exists = self._path.exists() and self._path.stat().st_size > 0
            self._file = open(self._path, "a", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=self._columns, extrasaction="ignore")
            if not file_exists:
                self._writer.writeheader()
        self._writer.writerow(record)

    def flush(self) -> None:
        if self._file:
            self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()


class DataRecorder:
    """Records L2, L4, and trade data to disk.

    Creates per-coin, per-data-type files with daily rotation.
    File layout: {output_dir}/{coin}/{type}_{YYYY-MM-DD}.{ext}
    """

    def __init__(self, config: RecordingConfig):
        self._config = config
        self._output_dir = Path(config.output_dir)
        self._writers: dict[str, RecordWriter] = {}  # key -> writer
        self._current_date: Optional[str] = None
        self._flush_counter = 0

    def _date_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _get_writer(self, coin: str, data_type: str) -> RecordWriter:
        """Get or create a writer for the given coin and data type, rotating daily."""
        today = self._date_str()
        key = f"{coin}:{data_type}:{today}"

        if key not in self._writers:
            # Close old writer for same coin:data_type if date changed
            for old_key in list(self._writers):
                if old_key.startswith(f"{coin}:{data_type}:") and old_key != key:
                    self._writers[old_key].close()
                    del self._writers[old_key]

            ext = "csv" if self._config.format == "csv" else "jsonl"
            path = self._output_dir / coin / f"{data_type}_{today}.{ext}"

            if self._config.format == "csv":
                self._writers[key] = CsvWriter(path)
            else:
                self._writers[key] = JsonLinesWriter(path)

        return self._writers[key]

    def record_l2(self, coin: str, snapshot: BookSnapshot) -> None:
        """Record an L2 book snapshot."""
        if not self._config.record_l2:
            return

        record = {
            "recv_ts_ms": int(time.time() * 1000),
            "exch_ts_ms": snapshot.timestamp_ms,
            "coin": snapshot.coin,
            "best_bid": str(snapshot.bids[0].price) if snapshot.bids else None,
            "best_bid_sz": str(snapshot.bids[0].size) if snapshot.bids else None,
            "best_ask": str(snapshot.asks[0].price) if snapshot.asks else None,
            "best_ask_sz": str(snapshot.asks[0].size) if snapshot.asks else None,
            "mid": str(snapshot.mid_price) if snapshot.mid_price else None,
            "spread_bps": str(snapshot.spread_bps) if snapshot.spread_bps else None,
            "bid_levels": len(snapshot.bids),
            "ask_levels": len(snapshot.asks),
            "bids": [{"px": str(lvl.price), "sz": str(lvl.size), "n": lvl.num_orders} for lvl in snapshot.bids],
            "asks": [{"px": str(lvl.price), "sz": str(lvl.size), "n": lvl.num_orders} for lvl in snapshot.asks],
        }

        writer = self._get_writer(coin, "l2")
        writer.write(record)
        self._maybe_flush()

    def record_l4(self, coin: str, raw_msg: dict) -> None:
        """Record a raw L4 message (snapshot or diff) with receive timestamp."""
        if not self._config.record_l4:
            return

        record = {
            "recv_ts_ms": int(time.time() * 1000),
            "coin": coin,
            "data": raw_msg,
        }

        writer = self._get_writer(coin, "l4")
        writer.write(record)
        self._maybe_flush()

    def record_trade(self, coin: str, trade_data: dict) -> None:
        """Record a trade event."""
        if not self._config.record_trades:
            return

        record = {
            "recv_ts_ms": int(time.time() * 1000),
            "coin": coin,
            "side": trade_data.get("side"),
            "px": trade_data.get("px"),
            "sz": trade_data.get("sz"),
            "time": trade_data.get("time"),
            "hash": trade_data.get("hash"),
        }

        writer = self._get_writer(coin, "trades")
        writer.write(record)
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        """Flush writers periodically to avoid data loss."""
        self._flush_counter += 1
        if self._flush_counter >= 100:
            self.flush()
            self._flush_counter = 0

    def flush(self) -> None:
        """Flush all open writers."""
        for writer in self._writers.values():
            try:
                writer.flush()
            except Exception:
                logger.exception("Error flushing writer")

    def close(self) -> None:
        """Close all open writers."""
        for writer in self._writers.values():
            try:
                writer.close()
            except Exception:
                logger.exception("Error closing writer")
        self._writers.clear()
