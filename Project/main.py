from iperf3 import Iperf3
from DB import DB
import configparser
import json
from datetime import datetime, timedelta, timezone


class main:
    TOOLS = [
          "iperf",
          "ss"
    ]

    def __init__(self, config_file='config.ini'):
        self._load_config(config_file)
        self._setup_tools()

    def _load_config(self, config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        self.config_dict = {section: dict(config.items(section)) for section in config.sections()}

    def _setup_tools(self):
        self.tools = self.config_dict["global_test_settings"]["tools"].split(", ")
        for tool in self.tools:
            if tool not in self.TOOLS:
                raise ValueError(f"Unsupported tool: {tool}")
            match tool:
                case "iperf":
                      self._setup_iperf3()
        self.db = DB()

    def _setup_iperf3(self):
        self.iperf3_tool = Iperf3()
        self.iperf3_tool.setParamters(**self.config_dict.get('iperf_client', {}))

    def _run_iperf3_test(self, test_name="example_test"):
        status = self.iperf3_tool.runTest(test_name)
        if status == 0:
            print(json.dumps(self.iperf3_tool.getTestData(test_name), indent=2))
        else:
            print("iperf3 test failed")

    def query_db(self, query, params=None):
        return self.db.query(query, params)

    def save_test_to_db(self, test_name):
        test_data = self.iperf3_tool.getTestData(test_name)
        if not test_data:
            print(f"No data found for test: {test_name}")
            return

        # Each execution is a separate test, even when its configuration is identical.
        test_id = self.query_db(
            """
            INSERT INTO tests (cca, parms)
            VALUES (%s, %s)
            RETURNING id
            """,
            (
                self.config_dict["global_test_settings"]["cca"],
                json.dumps(self.config_dict["iperf_client"]),
            ),
        )[0][0]

        # Insert one result for every interval and stream, not only the final summary.
        timestamp = test_data.get("start", {}).get("timestamp", {}).get("timesecs")
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()
        test_start = datetime.fromtimestamp(timestamp, timezone.utc)

        for interval in test_data.get("intervals", []):
            interval_time = test_start + timedelta(seconds=interval.get("end", 0))
            for result in interval.get("streams", []):
                self.query_db(
                    """
                    INSERT INTO results (test_id, t, throughput, rtt_ms, cwnd, retrans)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        test_id,
                        interval_time,
                        result.get("bits_per_second"),
                        result.get("rtt"),
                        result.get("snd_cwnd"),
                        result.get("retransmits")
                    )
                )

    def run_tests(self, test_name="example_test"):
        if "iperf" in self.tools:
            self._run_iperf3_test(test_name)


test = main()
test.run_tests("test_2")
test.save_test_to_db("test_2")
exit(0)