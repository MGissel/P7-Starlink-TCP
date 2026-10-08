import psycopg

class DB:
    HOST = "100.118.40.60"
    PORT = 5432
    DBNAME = "postgres"
    USER = "postgres"

    SCHEMA = [
        """
        CREATE TABLE IF NOT EXISTS cca (
            name        VARCHAR PRIMARY KEY,
            description TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tests (
            id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cca    VARCHAR NOT NULL REFERENCES cca(name),
            parms  JSONB
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS results (
            id          BIGSERIAL PRIMARY KEY,
            test_id     UUID NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
            t           TIMESTAMPTZ NOT NULL,
            throughput  DOUBLE PRECISION,
            rtt_ms      DOUBLE PRECISION,
            cwnd        INTEGER,
            retrans     INTEGER
        )
        """,
        "CREATE INDEX IF NOT EXISTS results_test_t_idx ON results (test_id, t)",
    ]

    def __init__(self):
        # Password is read automatically from ~/.pgpass
        self.conn = psycopg.connect(
            host=self.HOST,
            port=self.PORT,
            dbname=self.DBNAME,
            user=self.USER,
        )
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

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()