from __future__ import annotations

import inspect
import unittest

from fastapi.params import Depends

from backend.api.chat import chat_endpoint
from backend.workspace.chat.service import ChatService, get_chat_service


class TestChatServiceDependency(unittest.TestCase):
    def test_chat_endpoint_uses_injectable_service_dependency(self) -> None:
        service_param = inspect.signature(chat_endpoint).parameters["service"]

        self.assertIsInstance(service_param.default, Depends)
        self.assertIs(service_param.default.dependency, get_chat_service)

    def test_get_chat_service_is_lazy_singleton(self) -> None:
        self.assertIsInstance(get_chat_service(), ChatService)
        self.assertIs(get_chat_service(), get_chat_service())


if __name__ == "__main__":
    unittest.main()
