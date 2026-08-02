"""Prometheus metrics for LLM usage and provider health.

Centralizes all Prometheus objects so callers update metrics through a
small function API rather than importing prometheus_client directly.
"""
from prometheus_client import Counter, Gauge, start_http_server

LLM_CALLS_TOTAL = Counter(
    "saloonbot_llm_calls_total", "Total LLM API calls", ["purpose", "model", "provider"]
)
LLM_INPUT_TOKENS_TOTAL = Counter(
    "saloonbot_llm_input_tokens_total", "Total LLM input tokens", ["purpose", "model", "provider"]
)
LLM_OUTPUT_TOKENS_TOTAL = Counter(
    "saloonbot_llm_output_tokens_total", "Total LLM output tokens", ["purpose", "model", "provider"]
)
LLM_PROVIDER_UP = Gauge(
    "saloonbot_llm_provider_up", "Whether the LLM provider is currently reachable (1) or not (0)", ["provider"]
)
LLM_PROVIDER_FAILURES_TOTAL = Counter(
    "saloonbot_llm_provider_failures_total", "Total LLM provider probe/creation failures", ["provider"]
)


def record_llm_usage(purpose, model, provider, input_tokens, output_tokens):
    """Record one LLM call's token usage, labeled by purpose/model/provider."""
    LLM_CALLS_TOTAL.labels(purpose=purpose, model=model, provider=provider).inc()
    LLM_INPUT_TOKENS_TOTAL.labels(purpose=purpose, model=model, provider=provider).inc(input_tokens)
    LLM_OUTPUT_TOKENS_TOTAL.labels(purpose=purpose, model=model, provider=provider).inc(output_tokens)


def set_llm_provider_status(provider, up):
    """Set the provider's up/down gauge that LlmProviderDown alerts on."""
    LLM_PROVIDER_UP.labels(provider=provider).set(1 if up else 0)


def record_llm_probe_failure(provider):
    """Count a failed probe/creation attempt, independent of the alert gauge."""
    LLM_PROVIDER_FAILURES_TOTAL.labels(provider=provider).inc()


def start_metrics_server(port):
    """Start the background HTTP server exposing /metrics. Non-blocking."""
    start_http_server(port)
