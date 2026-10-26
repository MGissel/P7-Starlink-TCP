import subprocess
from contextlib import contextmanager
from typing import Iterator


class NetworkNamespace:
    """Create the isolated veth network used by the experiment."""

    def __init__(
        self,
        namespace: str = "tq-client",
        host_interface: str = "tq-host",
        client_interface: str = "tq-peer",
    ):
        self.namespace = namespace
        self.host_interface = host_interface
        self.client_interface = client_interface

    @staticmethod
    def _sudo(*arguments: str) -> None:
        subprocess.run(["sudo", *arguments], check=True)

    def setup(self) -> None:
        """Create and configure the namespace and its veth pair."""
        subprocess.run(
            ["sudo", "ip", "netns", "delete", self.namespace],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            ["sudo", "ip", "link", "delete", self.host_interface],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._sudo("ip", "netns", "add", self.namespace)
        self._sudo(
            "ip",
            "link",
            "add",
            self.host_interface,
            "type",
            "veth",
            "peer",
            "name",
            self.client_interface,
        )
        self._sudo("ip", "link", "set", self.client_interface, "netns", self.namespace)
        self._sudo("ip", "addr", "add", "10.200.0.1/24", "dev", self.host_interface)
        self._sudo(
            "sysctl",
            "-w",
            f"net.ipv6.conf.{self.host_interface}.disable_ipv6=1",
        )
        self._sudo("ip", "link", "set", self.host_interface, "up")
        self._sudo(
            "ip",
            "netns",
            "exec",
            self.namespace,
            "ip",
            "addr",
            "add",
            "10.200.0.2/24",
            "dev",
            self.client_interface,
        )
        self._sudo(
            "ip",
            "netns",
            "exec",
            self.namespace,
            "sysctl",
            "-w",
            f"net.ipv6.conf.{self.client_interface}.disable_ipv6=1",
        )
        self._sudo(
            "ip",
            "netns",
            "exec",
            self.namespace,
            "ip",
            "link",
            "set",
            self.client_interface,
            "up",
        )
        self._sudo("ip", "netns", "exec", self.namespace, "ip", "link", "set", "lo", "up")

        # Resolve the veth neighbor before TheaterQ is armed; otherwise ARP can trigger ARM.
        self._sudo(
            "ip",
            "netns",
            "exec",
            self.namespace,
            "ping",
            "-c",
            "1",
            "-W",
            "1",
            "10.200.0.1",
        )

    @contextmanager
    def iperf_server(self) -> Iterator[subprocess.Popen[str]]:
        """Run an iperf3 server inside the client namespace."""
        server = subprocess.Popen(
            [
                "sudo",
                "ip",
                "netns",
                "exec",
                self.namespace,
                "iperf3",
                "-s",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            yield server
        finally:
            server.terminate()
            try:
                server.wait(timeout=2)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    @staticmethod
    def ensure_process_started(process: subprocess.Popen[str]) -> None:
        """Raise an actionable error if a background process exited immediately."""
        if process.poll() is not None:
            error = process.stderr.read().strip() if process.stderr else ""
            raise RuntimeError(f"iperf3 server failed: {error or 'no error output'}")
