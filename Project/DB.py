import json
from datetime import datetime, timedelta, timezone

import psycopg

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
        # One row per line of tcp.log (column order = the bpftrace header)
        """
        CREATE TABLE IF NOT EXISTS public.tcp_samples (
            test_id        UUID NOT NULL REFERENCES public.tests(id) ON DELETE CASCADE,
            t_ns           BIGINT NOT NULL,
            cwnd BIGINT, ssthresh BIGINT, srtt_us BIGINT, rttvar_us BIGINT, minrtt_us BIGINT,
            inflight BIGINT, packets_out BIGINT, sacked_out BIGINT, lost_out BIGINT, retrans_out BIGINT,
            bytes_acked BIGINT, bytes_retrans BIGINT, total_retrans BIGINT, lost BIGINT,
            delivered BIGINT, delivered_ce BIGINT,
            snd_wnd BIGINT, rcv_wnd BIGINT, pacing_bps BIGINT, wmem_queued BIGINT, sndbuf BIGINT,
            ca_state SMALLINT, backoff SMALLINT, rto_j BIGINT, reordering BIGINT,
            busy_j BIGINT, rwnd_lim_j BIGINT, sndbuf_lim_j BIGINT
        )
        """,
        "CREATE INDEX IF NOT EXISTS tcp_samples_test_t_idx ON public.tcp_samples (test_id, t_ns)",
        # One row per line of cubic.log
        """
        CREATE TABLE IF NOT EXISTS public.cubic_samples (
            test_id      UUID NOT NULL REFERENCES public.tests(id) ON DELETE CASCADE,
            t_ns         BIGINT NOT NULL,
            w_max BIGINT, k BIGINT, epoch_start BIGINT, cnt BIGINT, delay_min BIGINT
        )
        """,
        "CREATE INDEX IF NOT EXISTS cubic_samples_test_t_idx ON public.cubic_samples (test_id, t_ns)",
    ]

    def __init__(self):
        # Password is read automatically from ~/.pgpass
        self.conn = psycopg.connect(
            host=self.HOST,
            port=self.PORT,
            dbname=self.DBNAME,
            user=self.USER,
        )
        with self.conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS public")
        self.create_tables()

    def create_tables(self):
        with self.conn.cursor() as cur:
            for sql in self.SCHEMA:
                cur.execute(sql)
        self.conn.commit()

    def query(self, sql, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:  # the query returned rows
                result = cur.fetchall()
            else:
                result = None
        self.conn.commit()
        return result

    def save_iperf_test(self, test_name, test_data, cca, parameters, clock_offset_ns=None):
        """Persist one iperf3 run and all of its interval stream results.

        Returns the new test's id, so probe samples can be attached to it
        with save_probe_samples().
        """
        if not test_data:
            raise ValueError("Cannot save an empty iperf3 result")

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
        return test_id

    def save_probe_samples(self, test_id, tcp_file="tcp.log", cubic_file="cubic.log"):
        """Stream the bpftrace logs into tcp_samples and cubic_samples.

        Each file's first line is a header with the column names; every other
        line starting with a digit is one sample. Returns (tcp_rows, cubic_rows).
        """
        counts = []
        for table, path in (("public.tcp_samples", tcp_file), ("public.cubic_samples", cubic_file)):
            rows = 0
            with self.conn.cursor() as cur, open(path) as f:
                header = f.readline().split()            # t_ns cwnd ssthresh ...
                columns = ", ".join(["test_id"] + [name.lower() for name in header])
                with cur.copy(
                    f"COPY {table} ({columns}) FROM STDIN WITH (DELIMITER ' ')"
                ) as copy:
                    for line in f:
                        if line[:1].isdigit():
                            copy.write(f"{test_id} {line}")
                            rows += 1
            counts.append(rows)
        self.conn.commit()
        return tuple(counts)

    def delete_tests_by_name(self, names: list[str]) -> int:
        """Delete tests and their results by test name."""
        if not names:
            return 0

        deleted = 0
        with self.conn.cursor() as cur:
            cur.execute(
                "DELETE FROM public.tests WHERE name = ANY(%s) RETURNING id",
                (names,),
            )
            deleted = len(cur.fetchall())
        self.conn.commit()
        return deleted

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()