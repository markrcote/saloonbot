import json
import os
import re
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


class FakeClient(LLMClient):
    """Deterministic offline provider for testing (LLM_PROVIDER=fake).

    Answers by prompt shape: action prompts get valid hit/stand JSON,
    bet prompts get a minimum bet, everything else a fixed prose line.
    """

    provider = "fake"

    def __init__(self):
        self.model = "fake"

    def complete(self, system: str, user: str, timeout: float) -> tuple[str, int, int]:
        input_tokens = (len(system) + len(user)) // 4
        if "Hit or stand?" in user:
            score_match = re.search(r"score: (\d+)", user)
            score = int(score_match.group(1)) if score_match else 20
            action = "hit" if score < 16 else "stand"
            text = json.dumps({"action": action, "quip": "Cards don't lie, friend."})
        elif "How much do you bet?" in user:
            range_match = re.search(r"range is \$(\d+)", user)
            amount = int(range_match.group(1)) if range_match else 5
            text = json.dumps({"amount": amount, "quip": "Easin' in slow tonight."})
        elif "Write your note on" in user:
            met_match = re.search(r"met (\d+) times? now", user)
            times_met = int(met_match.group(1)) if met_match else 1
            text = f"Met them {times_met} time{'s' if times_met != 1 else ''} now, a steady sort."
        else:
            text = (
                "Played a few hands at the table tonight. "
                "Folks came and went, and the cards mostly behaved."
            )
        return text, input_tokens, len(text) // 4

    def probe(self) -> None:
        pass


_VALID_PROVIDERS = ("openai", "claude", "none", "fake")


def get_configured_provider() -> str:
    """Resolve the single configured LLM provider.

    LLM_PROVIDER is optional and defaults to "openai". "none" explicitly
    disables the LLM client (NPCs always use the built-in simple strategy).
    Any other value is a configuration error, raised immediately rather than
    guessed at from whichever API keys happen to be present.
    """
    value = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if not value:
        return "openai"
    if value not in _VALID_PROVIDERS:
        raise LLMError(f"Invalid LLM_PROVIDER: {value!r}. Expected one of {_VALID_PROVIDERS}.")
    return value


def create_llm_client() -> LLMClient | None:
    """Create the configured LLM client, or None if LLM_PROVIDER=none."""
    provider = get_configured_provider()
    if provider == "none":
        return None
    elif provider == "claude":
        return ClaudeClient()
    elif provider == "openai":
        return OpenAIClient()
    else:
        return FakeClient()
