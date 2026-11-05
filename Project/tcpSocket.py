import subprocess
import threading

CUBIC_HDR = "t_ns w_max K epoch_start cnt delay_min\n"

class SocketReader:
    def __init__(self, script="tcp_sock_probe.bt",
                 tcp_file="tcp.log", cubic_file="cubic.log"):
        self._tcp = open(tcp_file, "w")
        self._cubic = open(cubic_file, "w")
        self._cubic.write(CUBIC_HDR)
        self._attached = threading.Event()

        self._proc = subprocess.Popen(
            ["sudo", "-n", "bpftrace", "-q", "-B", "line", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self._thread = threading.Thread(target=self._split_output, daemon=True)
        self._thread.start()

        if not self._attached.wait(timeout=60):
            self.stop()
            raise TimeoutError("bpftrace did not attach in time")
        if self._proc.poll() is not None:
            raise RuntimeError("bpftrace exited:\n" + self._proc.stderr.read())

    def _split_output(self):
        for line in self._proc.stdout:
            cols = line.split()
            if not cols:
                continue
            if cols[0] == "t_ns":                     # header = probes attached
                self._tcp.write(line)
                self._attached.set()
            elif cols[0] == "CUBIC":                  # CUBIC 123 w_max=26 K=...
                values = [c.split("=", 1)[1] for c in cols[2:]]
                self._cubic.write(cols[1] + " " + " ".join(values) + "\n")
            elif cols[0].isdigit():                   # TCP state line
                self._tcp.write(line)
        self._attached.set()                          # bpftrace exited: stop waiting

    def stop(self):
        """Stop the probe with SIGINT so bpftrace flushes its output."""
        if self._proc.poll() is None:
            subprocess.run(["sudo", "kill", "-INT", str(self._proc.pid)])
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "kill", "-KILL", str(self._proc.pid)])
                self._proc.wait()
        self._thread.join(timeout=5)
        self._tcp.close()
        self._cubic.close()