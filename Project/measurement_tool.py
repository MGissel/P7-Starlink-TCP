from abc import ABC, abstractmethod

class MeasurementTool(ABC):
    """Common interface for all measurement tools."""

    @abstractmethod
    def setParamters(self, **kwargs) -> int:
        """Set parameters for the measurement tool."""

    @abstractmethod
    def runTest(self, test_name: str) -> int:
        """Run the test with the given name."""

    @abstractmethod
    def getTestData(self, test_name: str) -> dict:
        """Get the test data for the given test name."""