import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg import sql

# Probe tables: one partition per test, so a test's samples can be dropped instantly.
# Column order doesn't matter for uploads: they use the log file's header line.
PROBE_COLUMNS = {
    "tcp_samples": [
        ("t_ns", "BIGINT NOT NULL"),
        ("cwnd", "BIGINT"), ("ssthresh", "BIGINT"), ("srtt_us", "BIGINT"),
        ("rttvar_us", "BIGINT"), ("minrtt_us", "BIGINT"),
        ("inflight", "BIGINT"), ("packets_out", "BIGINT"), ("sacked_out", "BIGINT"),
        ("lost_out", "BIGINT"), ("retrans_out", "BIGINT"),
        ("bytes_acked", "BIGINT"), ("bytes_retrans", "BIGINT"), ("total_retrans", "BIGINT"),
        ("lost", "BIGINT"), ("delivered", "BIGINT"), ("delivered_ce", "BIGINT"),
        ("snd_wnd", "BIGINT"), ("rcv_wnd", "BIGINT"), ("pacing_bps", "BIGINT"),
        ("wmem_queued", "BIGINT"), ("sndbuf", "BIGINT"),
        ("ca_state", "SMALLINT"), ("backoff", "SMALLINT"), ("rto_j", "BIGINT"),
        ("reordering", "BIGINT"), ("busy_j", "BIGINT"), ("rwnd_lim_j", "BIGINT"),
        ("sndbuf_lim_j", "BIGINT"),
        ("sport", "INTEGER"),   # local port: tells the iperf3 data and control connections apart
        ("ino", "BIGINT"),      # socket inode
        ("rack_rtt_us", "BIGINT"),  # latest RTT sample, not smoothed
    ],
    "cubic_samples": [
        ("t_ns", "BIGINT NOT NULL"),
        ("w_max", "BIGINT"), ("k", "BIGINT"), ("epoch_start", "BIGINT"),
        ("cnt", "BIGINT"), ("delay_min", "BIGINT"),
        ("sport", "INTEGER"),
    ],
    # One row per irtt packet (written by irtt.irtt_to_log)
    "irtt_samples": [
        ("t_ns", "BIGINT NOT NULL"),       # client send time, on the probe's clock
        ("seqno", "INTEGER"),
        ("lost", "SMALLINT"),              # 0 no, 1 on the way to the server, 2 on the way back, 3 unknown
        ("rtt_ns", "BIGINT"),
        ("send_delay_ns", "BIGINT"),       # one-way delay client -> server
        ("receive_delay_ns", "BIGINT"),    # one-way delay server -> client
    ],
}


class DB:
    HOST = "100.118.40.60"
    PORT = 5432
    DBNAME = "postgres"
    USER = "postgres"
    SCHEMA_NAME = "public"

    SCHEMA = [
        """
        CREATE TABLE IF NOT EXISTS public.cca (
            name        VARCHAR PRIMARY KEY,
            description TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS public.tests (
            id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name   VARCHAR NOT NULL,
            cca    VARCHAR NOT NULL REFERENCES public.cca(name),
            parms  JSONB
        )
        """,
        # Wall clock minus CLOCK_MONOTONIC when the test ran.
        # Wall-clock time of a probe sample = to_timestamp((t_ns + clock_offset_ns) / 1e9)
        "ALTER TABLE public.tests ADD COLUMN IF NOT EXISTS clock_offset_ns BIGINT",
        """
        CREATE TABLE IF NOT EXISTS public.results (
            id          BIGSERIAL PRIMARY KEY,
            test_id     UUID NOT NULL REFERENCES public.tests(id) ON DELETE CASCADE,
            t           TIMESTAMPTZ NOT NULL,
            throughput  DOUBLE PRECISION,
            rtt_ms      DOUBLE PRECISION,
            cwnd        INTEGER,
            retrans     INTEGER
        )
        """,
        "CREATE INDEX IF NOT EXISTS results_test_t_idx ON public.results (test_id, t)",
    ]

    def __init__(self):
        # Password is read automatically from ~/.pgpass
        self.conn = self._connect()
        self.needs_migration = False
        with self.conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS public")
        self.create_tables()

    @classmethod
    def _connect(cls):
        return psycopg.connect(host=cls.HOST, port=cls.PORT, dbname=cls.DBNAME, user=cls.USER)

    # --- Schema -------------------------------------------------------------

    def create_tables(self):
        with self.conn.cursor() as cur:
            for statement in self.SCHEMA:
                cur.execute(statement)
            for table, columns in PROBE_COLUMNS.items():
                kind = self._relkind(cur, table)
                if kind is None:
                    self._create_probe_parent(cur, table)
                elif kind == "r":
                    # Old layout (one big table). Still readable; run migrate_probe_tables()
                    self.needs_migration = True
                for name, col_type in columns:
                    if "NOT NULL" not in col_type:
                        cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                            sql.Identifier("public", table), sql.Identifier(name), sql.SQL(col_type)))
        self.conn.commit()
        if self.needs_migration:
            print("Note: the probe tables use the old layout. Run `python DB.py` once to convert them.")

    @staticmethod
    def _relkind(cur, table):
        """'p' = partitioned table, 'r' = plain table, None = doesn't exist."""
        cur.execute(
            """
            SELECT c.relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = %s
            """,
            (table,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def _create_probe_parent(cur, table):
        columns = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(col_type))
            for name, col_type in [("test_id", "UUID NOT NULL")] + PROBE_COLUMNS[table]
        )
        cur.execute(sql.SQL("CREATE TABLE {} ({}) PARTITION BY LIST (test_id)").format(
            sql.Identifier("public", table), columns))
        # Within a partition test_id is constant, so the index only needs the time
        cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (t_ns)").format(
            sql.Identifier(f"{table}_t_idx"), sql.Identifier("public", table)))

    @staticmethod
    def _partition_name(table, test_id):
        return f"{table}_{str(test_id).replace('-', '')}"

    def _create_partition(self, cur, table, test_id):
        """Create (if needed) the partition holding one test's samples; returns its name."""
        name = self._partition_name(table, test_id)
        cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} PARTITION OF {} FOR VALUES IN ({})").format(
            sql.Identifier("public", name), sql.Identifier("public", table), sql.Literal(str(test_id))))
        # Lets COPY leave out test_id, so it isn't sent once per row
        cur.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN test_id SET DEFAULT {}").format(
            sql.Identifier("public", name), sql.Literal(str(test_id))))
        return name

    def migrate_probe_tables(self):
        """One-time conversion of the old single-table layout to one partition per test."""
        with self.conn.cursor() as cur:
            for table, columns in PROBE_COLUMNS.items():
                if self._relkind(cur, table) != "r":
                    continue
                old = f"{table}_old"
                cur.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier("public", table), sql.Identifier(old)))
                self._create_probe_parent(cur, table)

                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    (old,),
                )
                old_columns = {row[0] for row in cur.fetchall()}
                names = sql.SQL(", ").join(
                    sql.Identifier(name) for name, _ in [("test_id", "")] + columns if name in old_columns)

                cur.execute(sql.SQL("SELECT DISTINCT test_id FROM {}").format(sql.Identifier("public", old)))
                test_ids = [row[0] for row in cur.fetchall()]
                for i, test_id in enumerate(test_ids, 1):
                    partition = self._create_partition(cur, table, test_id)
                    cur.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} WHERE test_id = %s").format(
                        sql.Identifier("public", partition), names, names, sql.Identifier("public", old)),
                        (test_id,))
                    print(f"{table}: moved test {i}/{len(test_ids)} ({cur.rowcount} rows)")
                cur.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier("public", old)))
        self.conn.commit()
        self.needs_migration = False

    # --- Queries ------------------------------------------------------------

    def query(self, sql_text, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql_text, params)
            if cur.description:  # the query returned rows
                result = cur.fetchall()
            else:
                result = None
        self.conn.commit()
        return result

    # --- Saving -------------------------------------------------------------

    def create_test(self, test_name, cca, parameters, clock_offset_ns=None):
        """Create a test row (and its probe partitions) and return its id."""
        self.query(
            """
            INSERT INTO public.cca (name)
            VALUES (%s)
            ON CONFLICT (name) DO NOTHING
            """,
            (cca,),
        )
        test_id = self.query(
            """
            INSERT INTO public.tests (name, cca, parms, clock_offset_ns)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (test_name, cca, json.dumps(parameters), clock_offset_ns),
        )[0][0]
        if not self.needs_migration:
            with self.conn.cursor() as cur:
                for table in PROBE_COLUMNS:
                    self._create_partition(cur, table, test_id)
            self.conn.commit()
        return test_id

    def save_iperf_results(self, test_id, test_data):
        """Store the interval results of one iperf3 run for an existing test."""
        if not test_data:
            raise ValueError("Cannot save an empty iperf3 result")

        timestamp = test_data.get("start", {}).get("timestamp", {}).get("timesecs")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()

        test_start = datetime.fromtimestamp(timestamp, timezone.utc)

        with self.conn.cursor() as cur:
            with cur.copy(
                """
                COPY public.results
                    (test_id, t, throughput, rtt_ms, cwnd, retrans)
                FROM STDIN
                """
            ) as copy:
                for interval in test_data.get("intervals", []):
                    interval_time = test_start + timedelta(seconds=interval.get("end", 0))
                    for result in interval.get("streams", []):
                        rtt_us = result.get("rtt")  # iperf3 reports rtt in microseconds
                        copy.write_row(
                            (
                                test_id,
                                interval_time,
                                result.get("bits_per_second"),
                                rtt_us / 1000 if rtt_us is not None else None,
                                result.get("snd_cwnd"),
                                result.get("retransmits"),
                            )
                        )
        self.conn.commit()

    def save_iperf_test(self, test_name, test_data, cca, parameters, clock_offset_ns=None):
        """Create a test and store its iperf3 results in one go. Returns the test id."""
        if not test_data:
            raise ValueError("Cannot save an empty iperf3 result")
        test_id = self.create_test(test_name, cca, parameters, clock_offset_ns)
        self.save_iperf_results(test_id, test_data)
        return test_id

    def rename_test(self, test_id, test_name):
        self.query("UPDATE public.tests SET name = %s WHERE id = %s", (test_name, test_id))

    def save_probe_samples(self, test_id, tcp_file="tcp.log", cubic_file="cubic.log"):
        """Upload the bpftrace logs into the test's partitions. Returns (tcp_rows, cubic_rows)."""
        rows = self.save_samples(test_id, {"tcp_samples": tcp_file, "cubic_samples": cubic_file})
        return rows["tcp_samples"], rows["cubic_samples"]

    def save_samples(self, test_id, files: dict) -> dict:
        """Upload log files into the test's partitions, all at the same time.

        files maps a table name (a key of PROBE_COLUMNS) to a log file whose first
        line is a header with column names. Returns {table: rows uploaded}.
        """
        if self.needs_migration:
            raise RuntimeError("Run `python DB.py` once to convert the probe tables first")

        with self.conn.cursor() as cur:
            partitions = {table: self._create_partition(cur, table, test_id) for table in files}
        self.conn.commit()

        with ThreadPoolExecutor(max_workers=len(files)) as pool:
            futures = {table: pool.submit(self._copy_log, partitions[table], path)
                       for table, path in files.items()}
            return {table: future.result() for table, future in futures.items()}

    @classmethod
    def _copy_log(cls, partition, path):
        """Stream one log file into a partition in 1 MB chunks."""
        with cls._connect() as conn, conn.cursor() as cur, open(path, "rb") as f:
            header = f.readline().decode().split()
            if not header:
                return 0
            columns = sql.SQL(", ").join(sql.Identifier(name.lower()) for name in header)
            with cur.copy(sql.SQL("COPY {} ({}) FROM STDIN WITH (DELIMITER ' ')").format(
                    sql.Identifier("public", partition), columns)) as copy:
                while chunk := f.read(1 << 20):
                    copy.write(chunk)
            rows = cur.rowcount
            conn.commit()
        return rows

    # --- Deleting -----------------------------------------------------------

    def delete_tests_by_name(self, names: list[str]) -> int:
        """Delete tests, their results and their probe samples by test name."""
        if not names:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM public.tests WHERE name = ANY(%s)", (names,))
            test_ids = [row[0] for row in cur.fetchall()]
        return self.delete_tests_by_id(test_ids)

    def delete_tests_by_id(self, test_ids: list) -> int:
        """Delete tests, their results and their probe samples by test id."""
        if not test_ids:
            return 0
        with self.conn.cursor() as cur:
            for test_id in test_ids:
                for table in PROBE_COLUMNS:
                    # Dropping the partition is instant, unlike deleting its rows
                    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(
                        sql.Identifier("public", self._partition_name(table, test_id))))
            if self.needs_migration:  # old layout: rows still live in one big table
                for table in PROBE_COLUMNS:
                    cur.execute(sql.SQL("DELETE FROM {} WHERE test_id = ANY(%s)").format(
                        sql.Identifier("public", table)), (test_ids,))
            cur.execute("DELETE FROM public.tests WHERE id = ANY(%s) RETURNING id", (test_ids,))
            deleted = len(cur.fetchall())
        self.conn.commit()
        return deleted

    def drop_orphan_partitions(self) -> int:
        """Drop probe partitions whose test no longer exists (e.g. deleted by hand in psql)."""
        dropped = 0
        with self.conn.cursor() as cur:
            for table in PROBE_COLUMNS:
                cur.execute(
                    """
                    SELECT c.relname, pg_get_expr(c.relpartbound, c.oid)
                    FROM pg_inherits i
                    JOIN pg_class c ON c.oid = i.inhrelid
                    JOIN pg_class p ON p.oid = i.inhparent
                    WHERE p.relname = %s
                    """,
                    (table,),
                )
                for partition, _ in cur.fetchall():
                    test_hex = partition[len(table) + 1:]
                    cur.execute("SELECT 1 FROM public.tests WHERE replace(id::text, '-', '') = %s", (test_hex,))
                    if cur.fetchone() is None:
                        cur.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier("public", partition)))
                        dropped += 1
        self.conn.commit()
        return dropped

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


if __name__ == "__main__":
    # Run once: `python DB.py` converts old probe tables to one partition per test
    with DB() as db:
        if db.needs_migration:
            db.migrate_probe_tables()
            print("Probe tables converted to one partition per test.")
        else:
            print("Probe tables already use one partition per test.")
        print(f"Dropped {db.drop_orphan_partitions()} orphan partitions.")