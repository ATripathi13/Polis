"""Container: Heart of the application.

Everything is registered here. Nobody manually creates services.
The container does.

Flow:
.env → Settings → Logger → Database → Repositories → Engines
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from infrastructure.config.dependency_injection import Container
from infrastructure.config.settings import Settings
from infrastructure.logging.logger import ContextLogger, setup_logging


class ApplicationContainer(Container):
    """Central dependency injection container for the Polis application.

    This is the heart of the application. Everything flows through here:
    
    1. Load Settings from .env
    2. Initialize Logger
    3. Create Database connections
    4. Register Repositories
    5. Register Engines
    6. Bootstrap everything
    
    No service is created manually. The container creates everything.
    
    Example:
        # Initialize the container
        container = ApplicationContainer()
        
        # Get a repository
        event_repo = container.get_event_repository()
        
        # Get an engine
        event_engine = container.get_engine("event")
        
        # Start everything
        container.initialize_all()
        
        # Stop everything
        container.shutdown_all()
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the application container.

        Args:
            settings: Application settings (loads from .env if not provided)
        """
        super().__init__(settings)

        # Generate correlation ID for this application instance
        self.correlation_id = f"app-{uuid.uuid4().hex[:12]}"

        # Initialize logging
        setup_logging(
            log_level=self.settings.log_level,
            correlation_id=self.correlation_id,
        )

        # Register core logger
        self.logger = ContextLogger(
            engine="container",
            organization=self.settings.organization_id,
            execution=self.settings.execution_id,
            correlation_id=self.correlation_id,
        )

        self.logger.info(
            "Application container initialized",
            operation="init_container",
            environment=self.settings.environment,
            debug=self.settings.debug,
        )

        # Track initialized engines for lifecycle management
        self._engines: dict[str, Any] = {}

    # =========================================================================
    # SETTINGS & CONFIGURATION
    # =========================================================================

    def get_settings(self) -> Settings:
        """Get application settings.

        Returns:
            Settings instance loaded from .env
        """
        return self.get_singleton("settings")

    def get_correlation_id(self) -> str:
        """Get the application's correlation ID.

        Returns:
            Unique correlation ID for tracing
        """
        return self.correlation_id

    # =========================================================================
    # LOGGING
    # =========================================================================

    def get_logger(
        self,
        engine: str,
        organization: str | None = None,
        execution: str | None = None,
    ) -> ContextLogger:
        """Get a logger for a component.

        Args:
            engine: Component/engine name
            organization: Organization ID (defaults to settings value)
            execution: Execution ID (defaults to settings value)

        Returns:
            ContextLogger configured for the component
        """
        return ContextLogger(
            engine=engine,
            organization=organization or self.settings.organization_id,
            execution=execution or self.settings.execution_id,
            correlation_id=self.correlation_id,
        )

    # =========================================================================
    # DATABASE
    # =========================================================================

    def get_database_url(self) -> str:
        """Get database connection URL.

        Returns:
            PostgreSQL connection URL
        """
        return self.settings.database_url

    def get_database_connection(self) -> Any:
        """Get or create database connection pool.

        This is a placeholder for future database implementation.
        When SQLAlchemy is integrated, this will return the connection pool.

        Returns:
            Database connection pool
        """
        if "db_connection" not in self._singletons:
            self.logger.info(
                "Creating database connection pool",
                operation="db_connect",
                database=self.settings.database_url.split("@")[1],
            )
            # TODO: Initialize SQLAlchemy session pool
            # For now, just store the URL
            self._singletons["db_connection"] = {
                "url": self.settings.database_url,
            }

        return self.get_singleton("db_connection")

    # =========================================================================
    # EXTERNAL SERVICES
    # =========================================================================

    def get_vector_store_url(self) -> str:
        """Get Qdrant vector store URL.

        Returns:
            Qdrant connection URL
        """
        return self.settings.vector_store_url

    def get_vector_store_api_key(self) -> str:
        """Get Qdrant API key.

        Returns:
            API key for authentication
        """
        return self.settings.vector_store_api_key

    def get_minio_endpoint(self) -> str:
        """Get MinIO endpoint URL.

        Returns:
            MinIO API endpoint
        """
        return self.settings.minio_endpoint

    def get_minio_credentials(self) -> dict[str, str]:
        """Get MinIO credentials.

        Returns:
            Dictionary with access_key and secret_key
        """
        return {
            "access_key": self.settings.minio_access_key,
            "secret_key": self.settings.minio_secret_key,
        }

    # =========================================================================
    # REPOSITORIES
    # =========================================================================

    def register_repository(self, name: str, factory: callable) -> None:
        """Register a repository factory.

        Args:
            name: Repository name (e.g., "event", "state", "knowledge")
            factory: Callable that creates the repository
        """
        self.register(f"repository_{name}", factory)

    def get_repository(self, name: str) -> Any:
        """Get a repository instance.

        Args:
            name: Repository name

        Returns:
            Repository instance

        Raises:
            KeyError: If repository not registered
        """
        logger = self.get_logger("container")
        logger.info(
            "Retrieving repository",
            operation="get_repository",
            repository=name,
        )
        return self.get(f"repository_{name}")

    # =========================================================================
    # ENGINES
    # =========================================================================

    def register_engine(self, name: str, factory: callable) -> None:
        """Register an engine factory.

        Args:
            name: Engine name (e.g., "event", "state", "reasoning")
            factory: Callable that creates the engine
        """
        self.register(f"engine_{name}", factory)

    def get_engine(self, name: str) -> Any:
        """Get an engine instance.

        Args:
            name: Engine name

        Returns:
            Engine instance

        Raises:
            KeyError: If engine not registered
        """
        if f"engine_{name}" not in self._singletons:
            self.logger.info(
                "Retrieving engine",
                operation="get_engine",
                engine=name,
            )
            engine = self.get_singleton(f"engine_{name}")
            self._engines[name] = engine
            return engine

        return self.get_singleton(f"engine_{name}")

    # =========================================================================
    # LIFECYCLE MANAGEMENT
    # =========================================================================

    def initialize_all(self) -> None:
        """Initialize all registered engines and services.

        This is called during application startup. It calls initialize()
        on all registered engines in dependency order.
        """
        self.logger.info(
            "Initializing all engines",
            operation="initialize_all",
            engine_count=len(self._engines),
        )

        for engine_name, engine in self._engines.items():
            try:
                self.logger.info(
                    f"Initializing engine: {engine_name}",
                    operation="initialize_engine",
                    engine=engine_name,
                )
                engine.initialize()
            except Exception as e:
                self.logger.error(
                    f"Failed to initialize engine {engine_name}: {str(e)}",
                    operation="initialize_engine",
                    engine=engine_name,
                    error=str(e),
                )
                raise

        self.logger.info(
            "All engines initialized successfully",
            operation="initialize_complete",
            engine_count=len(self._engines),
        )

    def shutdown_all(self) -> None:
        """Shutdown all registered engines and services.

        This is called during application shutdown. It calls shutdown()
        on all registered engines in reverse order.
        """
        self.logger.info(
            "Shutting down all engines",
            operation="shutdown_all",
            engine_count=len(self._engines),
        )

        # Shutdown in reverse order (dependency order)
        for engine_name in reversed(list(self._engines.keys())):
            engine = self._engines[engine_name]
            try:
                self.logger.info(
                    f"Shutting down engine: {engine_name}",
                    operation="shutdown_engine",
                    engine=engine_name,
                )
                engine.shutdown()
            except Exception as e:
                self.logger.error(
                    f"Error shutting down engine {engine_name}: {str(e)}",
                    operation="shutdown_engine",
                    engine=engine_name,
                    error=str(e),
                )

        self.logger.info(
            "All engines shut down",
            operation="shutdown_complete",
            engine_count=len(self._engines),
        )

    # =========================================================================
    # BOOTSTRAP
    # =========================================================================

    @classmethod
    def bootstrap(cls) -> ApplicationContainer:
        """Bootstrap the application with the container.

        This is the primary entry point for creating a fully initialized
        application container with all dependencies registered.

        Returns:
            Fully bootstrapped ApplicationContainer

        Example:
            # In main.py or FastAPI app startup
            container = ApplicationContainer.bootstrap()
            
            # Get dependencies
            event_engine = container.get_engine("event")
            
            # Initialize
            container.initialize_all()
            
            # Use throughout the app
            # ...
            
            # Shutdown
            container.shutdown_all()
        """
        # Create container with settings from .env
        container = cls()

        container.logger.info(
            "Bootstrapping application",
            operation="bootstrap_start",
        )

        # TODO: Register all engines, repositories, and services here
        # Example (when ready):
        #
        # container.register_repository("event", lambda c: EventRepository(c))
        # container.register_engine("event", lambda c: EventEngine(c))
        # container.register_engine("state", lambda c: StateEngine(c))
        # container.register_engine("reasoning", lambda c: ReasoningEngine(c))
        # etc.

        container.logger.info(
            "Application bootstrap complete",
            operation="bootstrap_complete",
            settings_loaded=True,
        )

        return container


def create_container() -> ApplicationContainer:
    """Factory function to create the application container.

    This is used by FastAPI startup handler.

    Returns:
        Bootstrapped ApplicationContainer
    """
    return ApplicationContainer.bootstrap()
