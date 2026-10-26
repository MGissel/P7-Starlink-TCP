
import subprocess
import platform
from datetime import datetime, timezone
from measurement_tool import MeasurementTool


class SS(MeasurementTool):
    """Collect Linux socket statistics."""

    def __init__(self):
        self.distro = "Debian"
        self.test_data = {}

    def setParamters(self, **kwargs) -> int:
        """Configure the WSL distribution if running on Windows."""
        self.distro = kwargs.get("distro", self.distro)
        return 0

    def runTest(self, test_name: str) -> int:
        system = platform.system()

        if system == "Linux":
            command = ["ss", "-s"]
        else:
            print(f"Unsupported OS: {system}")
            return 1

        try:
            result = subprocess.run(
                command,
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
                "command": " ".join(command),
                "statistics": result.stdout.strip()
            }

            return 0

        except FileNotFoundError:
            print(f"Error: command not found: {command[0]}")
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
