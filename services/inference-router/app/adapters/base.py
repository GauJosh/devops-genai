"""
Inference Adapter Base Class Module

Defines the abstract base class for LLM inference providers. All adapter implementations
(OpenAI, Ollama, mock) inherit from this interface.
"""
from abc import ABC, abstractmethod
from ..schemas import GenerateRequest, GenerateResponse


class BaseAdapter(ABC):
    @abstractmethod
    def generate(self, req: GenerateRequest) -> GenerateResponse:
        raise NotImplementedError