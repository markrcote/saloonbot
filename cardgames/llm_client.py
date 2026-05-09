import os
from abc import ABC, abstractmethod


class LLMError(Exception):
    pass


def _read_key(env_var):
    """Direct env var → _FILE path → default /run/secrets/ path → None."""
    value = os.environ.get(env_var)
    if value:
        return value
    file_path = os.environ.get(f"{env_var}_FILE") or f"/run/secrets/{env_var.lower()}"
    if os.path.isfile(file_path):
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
    explicit = os.environ.get("LLM_PROVIDER", "").lower()
    if explicit == "claude":
        return ClaudeClient()
    elif explicit == "openai":
        return OpenAIClient()
    elif explicit:
        raise LLMError(f"Unknown LLM_PROVIDER: {explicit!r}. Expected 'claude' or 'openai'.")

    has_anthropic = bool(_read_key("ANTHROPIC_API_KEY"))
    has_openai = bool(_read_key("OPENAI_API_KEY"))
    if has_anthropic and not has_openai:
        return ClaudeClient()
    elif has_openai and not has_anthropic:
        return OpenAIClient()
    elif has_anthropic and has_openai:
        return ClaudeClient()
    else:
        raise LLMError("No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.")
