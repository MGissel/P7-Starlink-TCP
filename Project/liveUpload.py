"""Upload probe log files to the database while they are still being written."""
import threading
import time
from pathlib import Path

from psycopg import sql

from DB import DB

MAX_BATCH = 64 << 20      # read at most 64 MB of a file per COPY
WRITE_CHUNK = 1 << 20     # send it in 1 MB pieces


class LiveUploader:
    """Every `interval` seconds, send the new complete lines of each log file to the test's partitions.

    The local files stay the master copy: the uploader only remembers how far it has
    got in each file. If the database can't be reached, it simply tries again from
    the same place next round, so nothing is lost or uploaded twice.
    """

    def __init__(self, test_id, files: dict[str, Path], interval: float = 10.0):
        self.test_id = test_id
        self.files = {table: Path(path) for table, path in files.items()}   # {"tcp_samples": path, ...}
        self.interval = interval
        self.state = {table: {"offset": 0, "columns": None, "rows": 0} for table in self.files}
        self.last_error: Exception | None = None
        self._conn = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # --- Public -------------------------------------------------------------

    def stop(self, attempts: int = 5, retry_delay: float = 5.0) -> bool:
        """Stop the background thread and upload whatever is left.

        Call this after SocketReader.stop(), so the files are complete.
        Returns True if every line in the files reached the database.
        """
        self._stop.set()
        self._thread.join()
        for attempt in range(attempts):
            if self._upload_new() and self.caught_up():
                break
            if attempt < attempts - 1:
                time.sleep(retry_delay)
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        return self.caught_up()

    def caught_up(self) -> bool:
        return all(
            not path.exists() or self.state[table]["offset"] >= path.stat().st_size
            for table, path in self.files.items()
        )

    def rows(self) -> dict[str, int]:
        return {table: state["rows"] for table, state in self.state.items()}

    # --- Background thread --------------------------------------------------

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._upload_new()

    def _upload_new(self) -> bool:
        """Upload everything new in all files. Returns False if the database failed."""
        try:
            if self._conn is None or self._conn.closed:
                self._conn = DB._connect()
            for table, path in self.files.items():
                self._upload_file(table, path)
            if self.last_error is not None:
                print("Live upload: database reachable again, catching up")
            self.last_error = None
            return True
        except Exception as error:   # network drop, database restart, ...
            if self.last_error is None:
                print(f"Live upload: {error!r} — will retry, data is safe in the local files")
            self.last_error = error
            try:
                if self._conn is not None:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
            return False

    def _upload_file(self, table: str, path: Path) -> None:
        state = self.state[table]
        if not path.exists():
            return
        partition = DB._partition_name(table, self.test_id)

        with open(path, "rb") as f:
            while True:
                f.seek(state["offset"])
                data = f.read(MAX_BATCH)

                if state["columns"] is None:          # first line is the header
                    newline = data.find(b"\n")
                    if newline < 0:
                        return                        # header not written yet
                    state["columns"] = data[:newline].decode().split()
                    state["offset"] += newline + 1
                    data = data[newline + 1:]

                end = data.rfind(b"\n")               # only send complete lines
                if end < 0:
                    return
                batch = data[:end + 1]

                columns = sql.SQL(", ").join(sql.Identifier(name.lower()) for name in state["columns"])
                with self._conn.cursor() as cur:
                    with cur.copy(sql.SQL("COPY {} ({}) FROM STDIN WITH (DELIMITER ' ')").format(
                            sql.Identifier("public", partition), columns)) as copy:
                        for start in range(0, len(batch), WRITE_CHUNK):
                            copy.write(batch[start:start + WRITE_CHUNK])
                    rows = cur.rowcount
                self._conn.commit()

                # Only move forward once the database has committed the batch
                state["offset"] += len(batch)
                state["rows"] += rows
                if len(data) < MAX_BATCH:
                    return