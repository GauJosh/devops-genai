from abc import ABC, abstractmethod
from ..schemas import GenerateRequest, GenerateResponse


class BaseAdapter(ABC):
    @abstractmethod
    def generate(self, req: GenerateRequest) -> GenerateResponse:
        raise NotImplementedError