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


_PROBE_TIMEOUT = 10.0


class LLMClient(ABC):
    provider: str
    model: str

    @abstractmethod
    def complete(self, system: str, user: str, timeout: float) -> tuple[str, int, int]:
        """Return (text, input_tokens, output_tokens)."""
        pass

    @abstractmethod
    def probe(self) -> None:
        """Make a minimal API call to verify the key and model are valid. Raises LLMError on failure."""
        pass


class ClaudeClient(LLMClient):
    provider = "claude"

    def __init__(self):
        import anthropic
        self.model = os.environ.get("LLM_MODEL", "claude-haiku-4-5")
        self._client = anthropic.Anthropic(api_key=_read_key("ANTHROPIC_API_KEY"))

    def complete(self, system: str, user: str, timeout: float) -> tuple[str, int, int]:
        import anthropic
        try:
            response = self._client.with_options(timeout=timeout).messages.create(
                model=self.model,
                max_tokens=256,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            usage = response.usage
            return response.content[0].text, usage.input_tokens, usage.output_tokens
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e

    def probe(self) -> None:
        import anthropic
        try:
            self._client.with_options(timeout=_PROBE_TIMEOUT).messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self):
        import openai
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self._client = openai.OpenAI(api_key=_read_key("OPENAI_API_KEY"))

    def complete(self, system: str, user: str, timeout: float) -> tuple[str, int, int]:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=256,
                timeout=timeout,
            )
            usage = response.usage
            return response.choices[0].message.content, usage.prompt_tokens, usage.completion_tokens
        except Exception as e:
            raise LLMError(str(e)) from e

    def probe(self) -> None:
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                timeout=_PROBE_TIMEOUT,
            )
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
