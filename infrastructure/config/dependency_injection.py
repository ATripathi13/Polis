from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from infrastructure.config.settings import Settings
from infrastructure.logging.logger import ContextLogger

T = TypeVar("T")


class Container:
    """Simple dependency injection container.
    
    All dependencies flow through the container:
    .env → Settings() → DI Container → Engine
    
    Nothing reads environment variables directly.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize dependency container.
        
        Args:
            settings: Application settings (loads from .env if not provided)
        """
        self.settings = settings or Settings.from_env_file()
        self._dependencies: dict[str, Any] = {}
        self._singletons: dict[str, Any] = {}

        # Register settings as a singleton
        self.register_singleton("settings", self.settings)

    def register(self, key: str, factory: callable) -> None:
        """Register a dependency factory.
        
        Args:
            key: Dependency key
            factory: Callable that creates the dependency
        """
        self._dependencies[key] = factory

    def register_singleton(self, key: str, instance: Any) -> None:
        """Register a singleton dependency.
        
        Args:
            key: Dependency key
            instance: The singleton instance
        """
        self._singletons[key] = instance

    def get(self, key: str) -> Any:
        """Get a dependency.
        
        Args:
            key: Dependency key
            
        Returns:
            The dependency instance.
            
        Raises:
            KeyError: If dependency not found.
        """
        # Check singletons first
        if key in self._singletons:
            return self._singletons[key]

        # Get from factory
        if key not in self._dependencies:
            msg = f"Dependency '{key}' not registered"
            raise KeyError(msg)

        instance = self._dependencies[key](self)
        return instance

    def get_singleton(self, key: str) -> Any:
        """Get or create a singleton dependency.
        
        Args:
            key: Dependency key
            
        Returns:
            The singleton instance.
        """
        if key not in self._singletons:
            instance = self.get(key)
            self._singletons[key] = instance
        return self._singletons[key]

    def reset(self) -> None:
        """Reset all singletons (mainly for testing)."""
        self._singletons.clear()
        self.register_singleton("settings", self.settings)


class Engine(ABC):
    """Base class for all engines.
    
    Characteristics:
    - Receives all dependencies via constructor (DI)
    - No global state
    - Fully typed
    - Logs in JSON format
    - Max line length 100 characters
    """

    def __init__(
        self,
        name: str,
        container: Container,
        organization: str | None = None,
        execution: str | None = None,
    ) -> None:
        """Initialize engine.
        
        Args:
            name: Engine name (e.g., "event", "reasoning")
            container: Dependency injection container
            organization: Organization context
            execution: Execution/request ID
        """
        self.name = name
        self.container = container
        self.settings: Settings = container.get("settings")
        self.logger = ContextLogger(
            engine=name,
            settings=self.settings,
            organization=organization,
            execution=execution,
        )
        self.organization = organization
        self.execution = execution

    @abstractmethod
    def initialize(self) -> None:
        """Initialize the engine.
        
        Called after dependency injection to set up resources.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown the engine.
        
        Clean up resources, close connections, etc.
        """
        pass


class Service:
    """Base class for domain services.
    
    Characteristics:
    - Receives all dependencies via constructor (DI)
    - No global state
    - Fully typed
    - No Any type hints unless necessary
    """

    def __init__(self, container: Container) -> None:
        """Initialize service.
        
        Args:
            container: Dependency injection container
        """
        self.container = container
        self.settings: Settings = container.get("settings")
