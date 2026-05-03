import os
from abc import ABC, abstractmethod


class LLMError(Exception):
    pass


def _read_key(env_var):
    """Return value of env_var, falling back to reading the file named by env_var_FILE."""
    value = os.environ.get(env_var)
    if value:
        return value
    file_path = os.environ.get(f"{env_var}_FILE")
    if file_path and os.path.isfile(file_path):
        with open(file_path) as f:
            return f.read().strip() or None
    return None


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, timeout: float) -> str:
        pass


class ClaudeClient(LLMClient):
    def __init__(self):
        import anthropic
        self._model = os.environ.get("LLM_MODEL", "claude-haiku-4-5")
        self._client = anthropic.Anthropic(api_key=_read_key("ANTHROPIC_API_KEY"))

    def complete(self, system: str, user: str, timeout: float) -> str:
        import anthropic
        try:
            response = self._client.with_options(timeout=timeout).messages.create(
                model=self._model,
                max_tokens=256,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e


class OpenAIClient(LLMClient):
    def __init__(self):
        import openai
        self._model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._client = openai.OpenAI(api_key=_read_key("OPENAI_API_KEY"))

    def complete(self, system: str, user: str, timeout: float) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=256,
                timeout=timeout,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise LLMError(str(e)) from e


def create_llm_client() -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "claude").lower()
    if provider == "claude":
        return ClaudeClient()
    elif provider == "openai":
        return OpenAIClient()
    else:
        raise LLMError(f"Unknown LLM_PROVIDER: {provider!r}. Expected 'claude' or 'openai'.")
