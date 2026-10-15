from codex_query.application.services.test_connection_service import (
    ConnectionTestService,
)
from codex_query.domain.models.connection import ConnectionTestResult, Endpoint
from codex_query.domain.models.settings import ServiceSettings


class TestConnection:
    def __init__(self, connection_test_service: ConnectionTestService) -> None:
        self._service = connection_test_service
        pass

    async def __call__(
        self, settings: ServiceSettings, endpoint: Endpoint
    ) -> ConnectionTestResult:
        match endpoint:
            case "chat":
                return await self._service.test_chat(settings)
            case "embedding":
                return await self._service.test_embedding(settings)
