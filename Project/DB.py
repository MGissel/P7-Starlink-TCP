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

    def save_iperf_test(self, test_name, test_data, cca, parameters):
        """Persist one iperf3 run and all of its interval stream results."""
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
            INSERT INTO public.tests (name, cca, parms)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (test_name, cca, json.dumps(parameters)),
        )[0][0]

        timestamp = test_data.get("start", {}).get("timestamp", {}).get("timesecs")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        test_start = datetime.fromtimestamp(timestamp, timezone.utc)

        for interval in test_data.get("intervals", []):
            interval_time = test_start + timedelta(seconds=interval.get("end", 0))
            for result in interval.get("streams", []):
                self.query(
                    """
                    INSERT INTO public.results (test_id, t, throughput, rtt_ms, cwnd, retrans)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        test_id,
                        interval_time,
                        result.get("bits_per_second"),
                        result.get("rtt"),
                        result.get("snd_cwnd"),
                        result.get("retransmits"),
                    ),
                )

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