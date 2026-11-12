import subprocess
import time

class KernelLog:
    def __init__(self, log_file, level="debug"):
        self._file = open(log_file, "w")
        self._proc = subprocess.Popen(
            ["sudo", "-n", "dmesg", "-k", "-W", "-l", level],
            stdin=subprocess.DEVNULL,
            stdout=self._file,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        time.sleep(0.2)
        if self._proc.poll() is not None:
            self._file.close()
            raise RuntimeError("dmesg exited:\n" + self._proc.stderr.read())

    def stop(self):
        if self._proc.poll() is None:
            subprocess.run(["sudo", "-n", "kill", "-INT", str(self._proc.pid)])
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "-n", "kill", "-KILL", str(self._proc.pid)])
                self._proc.wait()
        self._file.close()