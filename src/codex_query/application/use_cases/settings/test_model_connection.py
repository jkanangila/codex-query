from codex_query.application.services.test_connection_service import (
    ConnectionTestService,
)
from codex_query.domain.models.connection import ConnectionTestResult
from codex_query.domain.models.settings import ServiceSettings


class TestConnection:
    def __init__(self, connection_test_service: ConnectionTestService) -> None:
        self._service = connection_test_service
        pass

    async def __call__(self, settings: ServiceSettings) -> ConnectionTestResult:
        raise NotImplementedError
