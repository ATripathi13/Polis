from __future__ import annotations

from infrastructure.config import Container, Engine
from infrastructure.logging import ContextLogger


class ExampleEngine(Engine):
    """Example engine demonstrating coding standards.
    
    This template shows:
    - Proper imports and future annotation
    - Full type hints
    - Dependency injection via Container
    - JSON logging
    - No global state
    - Max line length 100
    """

    def __init__(
        self,
        container: Container,
        organization: str | None = None,
        execution: str | None = None,
    ) -> None:
        """Initialize the example engine.
        
        Args:
            container: Dependency injection container.
            organization: Organization context.
            execution: Execution/request ID.
        """
        super().__init__(
            name="example",
            container=container,
            organization=organization,
            execution=execution,
        )
        self.state: dict[str, int] = {}

    def initialize(self) -> None:
        """Initialize the engine resources.
        
        Called after dependency injection to set up any resources
        like database connections, caches, etc.
        """
        self.logger.info("Engine initializing", operation="initialize")
        self.state = {"initialized": True}
        self.logger.info("Engine initialized", operation="initialize")

    def shutdown(self) -> None:
        """Shutdown the engine and clean up resources.
        
        Called when the engine is being shut down to release
        any resources like database connections, file handles, etc.
        """
        self.logger.info("Engine shutting down", operation="shutdown")
        self.state.clear()
        self.logger.info("Engine shutdown complete", operation="shutdown")

    def process(self, data: dict[str, str]) -> dict[str, int]:
        """Process input data and return result.
        
        Args:
            data: Input data dictionary.
        
        Returns:
            Result dictionary with counts.
        
        Raises:
            ValueError: If data is invalid.
        """
        if not data:
            msg = "Data cannot be empty"
            raise ValueError(msg)

        self.logger.info(
            "Starting data processing",
            operation="process",
            input_size=len(data),
        )

        result: dict[str, int] = {}
        for key, value in data.items():
            result[key] = len(value)

        self.logger.info(
            "Data processing completed",
            operation="process",
            output_size=len(result),
        )

        return result
