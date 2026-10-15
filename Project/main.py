import inspect

from iperf3 import Iperf3
from TQ import TQ
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
        from DB import DB

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

import subprocess
import time
from TQ import TQ


def sudo(*arguments):
    subprocess.run(["sudo", *arguments], check=True)


namespace = "tq-client"
host_interface = "tq-host"
client_interface = "tq-peer"

subprocess.run(
    ["sudo", "ip", "netns", "delete", namespace],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    check=False,
)
sudo("ip", "netns", "add", namespace)

sudo("ip", "link", "add", host_interface,
        "type", "veth", "peer", "name", client_interface)

sudo("ip", "link", "set", client_interface, "netns", namespace)

sudo("ip", "addr", "add", "10.200.0.1/24", "dev", host_interface)
sudo("sysctl", "-w", f"net.ipv6.conf.{host_interface}.disable_ipv6=1")
sudo("ip", "link", "set", host_interface, "up")

sudo("ip", "netns", "exec", namespace,
        "ip", "addr", "add", "10.200.0.2/24", "dev", client_interface)
sudo("ip", "netns", "exec", namespace,
    "sysctl", "-w", f"net.ipv6.conf.{client_interface}.disable_ipv6=1")
sudo("ip", "netns", "exec", namespace,
        "ip", "link", "set", client_interface, "up")
sudo("ip", "netns", "exec", namespace,
        "ip", "link", "set", "lo", "up")

# Resolve the veth neighbor before TheaterQ is armed; otherwise ARP can trigger ARM.
sudo("ip", "netns", "exec", namespace,
    "ping", "-c", "1", "-W", "1", "10.200.0.1")

import time
#t = "../TheaterQ/Traces/theaterQ_traces/20260319_mixed_losssampling_eval_dl50.trace"
t = "../TheaterQ/Traces/test_trace.csv"
theaterq = TQ()
theaterq.setParamters(
    trace=t,
    interface=host_interface,
    handle="1:",
    format="SIMPLE",
    stage="ARM",
    cont="LOOP",
)

if theaterq.runTest("network_test") != 0:
    raise RuntimeError("TheaterQ setup failed")

print("TheaterQ setup completed successfully. Running main tests...")

server = subprocess.Popen([
    "sudo", "ip", "netns", "exec", namespace, "iperf3", "-s",
], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

try:
    time.sleep(1)
    if server.poll() is not None:
        server_error = server.stderr.read().strip()
        raise RuntimeError(f"iperf3 server failed: {server_error or 'no error output'}")
    """
    result = subprocess.run(
        ["iperf3", "-c", "10.200.0.2", "-t", "5", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"iperf3 failed (exit {result.returncode}): "
            f"{result.stderr.strip() or 'no error output'}"
        )
    print(json.dumps(json.loads(result.stdout), indent=2))"""
    time.sleep(60)
finally:
    server.terminate()
    try:
        server.wait(timeout=2)
    except subprocess.TimeoutExpired:
        server.kill()

exit(0)
test = main()
test.run_tests("test_2")
test.save_test_to_db("test_2")
