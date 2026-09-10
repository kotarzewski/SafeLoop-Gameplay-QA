from __future__ import annotations

from abc import ABC, abstractmethod


class EngineAdapter(ABC):
    @abstractmethod
    def doctor(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate(self) -> dict:
        raise NotImplementedError
