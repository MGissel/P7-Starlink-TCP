import subprocess
import platform
from datetime import datetime, timezone
from measurement_tool import MeasurementTool


class SS(MeasurementTool):
    """Collect Linux socket statistics through WSL."""

    def __init__(self):
        self.distro = "Debian"
        self.test_data = {}

    def setParamters(self, **kwargs) -> int:
        """Configure the WSL distribution."""
        self.distro = kwargs.get("distro", self.distro)
        return 0

    def runTest(self, test_name: str) -> int:
        system = platform.system()

        if system == "Windows":
            command = ["wsl.exe", "-d", self.distro, "--", "ss", "-s"]
        elif system in ("Linux"):
            command = ["ss", "-s"]
        else:
            print("Unsupported OS")
            return 1
        try:
            result = subprocess.run(
                [
                    "wsl.exe",
                    "-d", self.distro,
                    " ",
                    "ss", "-s"
                ],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode != 0:
                print(f"SS command failed: {result.stderr.strip()}")
                return 1

            self.test_data[test_name] = {
                "test_name": test_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": "ss -s",
                "statistics": result.stdout.strip()
            }

            return 0

        except FileNotFoundError:
            print("Error: wsl.exe was not found.")
            return 1

        except subprocess.TimeoutExpired:
            print("Error: SS measurement timed out.")
            return 1

        except Exception as e:
            print(f"Unexpected SS error: {e}")
            return 1

    def getTestData(self, test_name: str) -> dict:
        """Return the results for a particular test."""
        return self.test_data.get(test_name, {})
