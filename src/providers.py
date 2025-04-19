import os
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models.ollama import ChatOllama
from langchain_mistralai.chat_models import ChatMistralAI
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.exceptions import LangChainException

# --- Custom Exceptions ---
class AuthenticationError(Exception):
    """Custom exception for authentication errors."""
    pass

class RateLimitError(Exception):
    """Custom exception for rate limit errors."""
    pass

class APIError(Exception):
    """Custom exception for general API errors."""
    pass

# --- Configuration ---
API_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "ollama": None, # Ollama often runs locally without a key
    "localai": "LOCALAI_API_KEY",
}

PROVIDER_DEFAULTS = {
    "openai": {"model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
    "anthropic": {"model": "claude-3-haiku-20240307", "base_url": "https://api.anthropic.com"},
    "gemini": {"model": "gemini-2.5-pro-preview-03-25", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"}, # Base URL not applicable
    "openrouter": {"model": "google/gemini-2.5-pro-preview-03-25", "base_url": "https://openrouter.ai/api/v1"},
    "mistral": {"model": "mistral-large-2402", "base_url": "https://api.mistral.ai/v1"}, # Uses internal default endpoint
    "deepseek": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
    "ollama": {"model": "llama3", "base_url": "http://localhost:11434"},
    "localai": {"model": "gpt-3.5-turbo", "base_url": "http://localhost:8083/v1"},
}

# --- Helper Functions ---

def _resolve_model_name(provider: str, config: Dict[str, Any], role_prefix: str = "") -> str:
    """
    Resolves the model name with the following priority:
    1. Role-specific config key
    2. Generic config key
    3. Environment variable (e.g., OPENAI_MODEL_NAME)
    4. Provider default
    """
    # 1. Role-specific config
    model_name = config.get(f"{role_prefix}model")
    if model_name:
        return model_name

    # 2. Generic config
    model_name = config.get("model")
    if model_name:
        return model_name

    # 3. Environment variable
    env_var_name = f"{provider.upper()}_MODEL_NAME"
    model_name = os.getenv(env_var_name)
    if model_name:
        return model_name

    # 4. Provider default
    return PROVIDER_DEFAULTS.get(provider, {}).get("model", "")

def _get_api_key(provider: str, api_key_source: str, config: Dict[str, Any]) -> Optional[str]:
    """Retrieves the API key from environment or config, raising AuthenticationError if missing."""
    api_key: Optional[str] = None
    key_env_var = API_KEY_ENV_VARS.get(provider)

    if api_key_source == "env" and key_env_var:
        api_key = os.getenv(key_env_var)
    elif api_key_source == "direct": # Example for future extension
        api_key = config.get("api_key")

    # Check if key is required and missing
    if not api_key and provider != "ollama": # Ollama doesn't require a key by default
        error_msg = f"API Key for provider '{provider}' not found"
        if api_key_source == "env" and key_env_var:
            error_msg += f" in environment variable '{key_env_var}'"
        elif api_key_source == "direct":
             error_msg += " directly in config"
        else:
             error_msg += " (source not specified or invalid)"
        raise AuthenticationError(error_msg)

    return api_key

def _resolve_base_url(provider: str, config: Dict[str, Any]) -> Optional[str]:
    """Resolves the base URL from config, environment, or provider defaults."""
    # 1. Check config first
    base_url = config.get("model_base_url")
    if base_url:
        return base_url

    # 2. Check environment variable
    env_var_name = f"{provider.upper()}_BASE_URL"
    base_url = os.getenv(env_var_name)
    if base_url:
        return base_url

    # 3. Use hardcoded default if available
    return PROVIDER_DEFAULTS.get(provider, {}).get("base_url")

def _initialize_openai_compatible(
    provider: str,
    model_name: Optional[str],
    api_key: str,
    base_url: Optional[str],
    temperature: float,
    default_model: str,
    default_base_url: Optional[str]
) -> ChatOpenAI:
    """Initializes ChatOpenAI for OpenAI-compatible providers."""
    resolved_model_name = model_name or default_model
    resolved_base_url = base_url or default_base_url

    if not resolved_base_url: # Should only happen if default is None and no override provided
         raise ValueError(f"Base URL is required but not found for provider '{provider}'.")

    # print(f"Using {provider.capitalize()}: model={resolved_model_name}, base_url={resolved_base_url}")
    client_params = {
        "api_key": api_key,
        "model_name": resolved_model_name,
        "temperature": temperature,
        "base_url": resolved_base_url,
    }
    # Add specific headers for OpenRouter if needed (example)
    # if provider == "openrouter":
    #     client_params["default_headers"] = {
    #         "HTTP-Referer": config.get("openrouter_http_referer", "YOUR_SITE_URL"),
    #         "X-Title": config.get("openrouter_x_title", "YOUR_APP_NAME"),
    #     }
    return ChatOpenAI(**client_params)


# --- Main Client Factory Function ---

def get_llm_client(config: Dict[str, Any], role: str = "default") -> BaseChatModel:
    """
    Initializes and returns a Langchain Chat Model client based on config and role.
    Handles multiple providers and basic error checking using a refactored structure.
    
    Args:
        config: Base configuration dictionary
        role: The LLM's role in the workflow (analysis, search, initial_translation,
              critique, final_translation). Determines which config values to use.
    """
    # Get role-specific config with fallback to default
    role_prefix = f"{role.upper()}_" if role != "default" else ""
    provider = config.get(f"{role_prefix}provider") or config.get("provider", "openai")
    provider = provider.lower()
    model_name = _resolve_model_name(provider, config, role_prefix)
    api_key_source = config.get(f"{role_prefix}api_key_source") or config.get("api_key_source", "env")
    temperature = config.get(f"{role_prefix}temperature") or config.get("temperature", 0.2)

    # print(f"[Provider Init] Using provider: {provider}, model: {model_name}")

    if provider not in PROVIDER_DEFAULTS:
        raise ValueError(f"Unsupported LLM provider configured: {provider}")

    try:
        # Get API Key (raises AuthenticationError if required and missing)
        api_key = _get_api_key(provider, api_key_source, config)

        # Resolve Base URL (can be None if not applicable or using internal defaults)
        base_url = _resolve_base_url(provider, config)

        # print(f"Attempting to initialize LLM client for provider: {provider}, model: {model_name or 'default'}, base_url: {base_url or 'provider default'}")

        # Provider-specific initialization
        if provider in ["openai", "openrouter", "deepseek", "localai"]:
            defaults = PROVIDER_DEFAULTS[provider]
            # API key must exist for these providers (checked by _get_api_key)
            return _initialize_openai_compatible(
                provider=provider,
                model_name=model_name,
                api_key=api_key, # type: ignore - We know it's not None here
                base_url=base_url,
                temperature=temperature,
                default_model=defaults["model"],
                default_base_url=defaults["base_url"]
            )

        elif provider == "anthropic":
            defaults = PROVIDER_DEFAULTS[provider]
            resolved_model_name = model_name or defaults["model"]
            resolved_base_url = base_url # Already resolved, includes default
            if not resolved_base_url: raise ValueError("Base URL required for Anthropic.")
            # print(f"Using Anthropic: model={resolved_model_name}, base_url={resolved_base_url}")
            # API key must exist (checked by _get_api_key)
            client_params = {
                "anthropic_api_key": api_key, # type: ignore
                "model_name": resolved_model_name,
                "temperature": temperature,
                "anthropic_api_url": resolved_base_url # Parameter name differs
            }
            return ChatAnthropic(**client_params)

        elif provider == "gemini":
            defaults = PROVIDER_DEFAULTS[provider]
            resolved_model_name = model_name or defaults["model"]
            # print(f"Using Google GenAI: model={resolved_model_name}")
            # API key must exist (checked by _get_api_key)
            return ChatGoogleGenerativeAI(
                model=resolved_model_name,
                google_api_key=api_key, # type: ignore
                temperature=temperature,
            )

        elif provider == "mistral":
            defaults = PROVIDER_DEFAULTS[provider]
            resolved_model_name = model_name or defaults["model"]
            # base_url here corresponds to 'endpoint' parameter
            # print(f"Using Mistral: model={resolved_model_name}, endpoint={base_url or 'default'}")
            # API key must exist (checked by _get_api_key)
            client_params = {
                "api_key": api_key, # type: ignore
                "model": resolved_model_name,
                "temperature": temperature,
            }
            if base_url: client_params["endpoint"] = base_url
            return ChatMistralAI(**client_params)

        elif provider == "ollama":
            defaults = PROVIDER_DEFAULTS[provider]
            resolved_model_name = model_name or defaults["model"]
            resolved_base_url = base_url # Already resolved, includes default
            if not resolved_base_url: raise ValueError("Base URL required for Ollama.")
            # print(f"Using Ollama: model={resolved_model_name}, base_url={resolved_base_url}")
            # No API key needed
            return ChatOllama(
                model=resolved_model_name,
                base_url=resolved_base_url,
                temperature=temperature
            )

        else:
            # This case should not be reached due to the check at the start
            raise ValueError(f"Internal error: Provider '{provider}' passed initial check but has no initialization logic.")

    except AuthenticationError: # Re-raise auth errors clearly
         raise
    except LangChainException as e: # Catch other Langchain specific errors
        # Attempt to provide more specific feedback if possible
        err_str = str(e).lower()
        if "authentication" in err_str or "api key" in err_str or "401" in err_str:
            raise AuthenticationError(f"Authentication failed for '{provider}'. Check your API key/credentials. Original error: {e}") from e
        elif "rate limit" in err_str or "429" in err_str:
             raise RateLimitError(f"Rate limit exceeded for '{provider}'. Original error: {e}") from e
        elif "could not connect" in err_str or "connection error" in err_str:
             # Use the resolved base_url for the error message if possible
             connect_url = base_url or PROVIDER_DEFAULTS.get(provider, {}).get("base_url", "unknown")
             raise ConnectionError(f"Could not connect to provider '{provider}' at base URL '{connect_url}'. Check network or server status. Original error: {e}") from e
        else: # General Langchain error
             raise RuntimeError(f"Failed to initialize LLM client for '{provider}' ({model_name or 'default'}): {e}") from e
    except Exception as e: # Catch unexpected generic errors during init
        raise RuntimeError(f"Unexpected error initializing LLM client for '{provider}': {type(e).__name__}: {e}") from e


import requests

def list_available_providers() -> list[dict]:
    """
    Dynamically queries each enabled provider's /v1/models endpoint to get available models.
    """
    providers = []
    for provider, key_env_var in API_KEY_ENV_VARS.items():
        # Check if API key is set or not required
        api_key = None
        if key_env_var:
            api_key = os.getenv(key_env_var)
            if not api_key:
                continue  # Skip disabled provider

        # Determine base URL
        env_base_url = os.getenv(f"{provider.upper()}_BASE_URL")
        base_url = env_base_url or PROVIDER_DEFAULTS.get(provider, {}).get("base_url")
        if not base_url:
            continue  # Skip if no base URL

        # Build /v1/models URL correctly
        base_url = base_url.rstrip("/")
        if base_url.endswith("/v1") or provider == "gemini":
            models_url = base_url + "/models"
        else:
            models_url = base_url + "/v1/models"

        headers = {}
        if api_key:
            if provider in ["openai", "openrouter", "deepseek", "localai", "mistral", "gemini"]:
                headers["Authorization"] = f"Bearer {api_key}"
            elif provider == "anthropic":
                headers["x-api-key"] = api_key
        try:
            resp = requests.get(models_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            model_ids = []
            # OpenAI-compatible response
            if isinstance(data, dict) and "data" in data:
                model_ids = [m.get("id") for m in data["data"] if "id" in m]
            # Ollama returns list of models differently, skip for now
            # Gemini may not support /v1/models, skip for now
            if not model_ids:
                continue  # Skip provider if no models fetched
            providers.append({
                "provider": provider,
                "models": model_ids
            })
        except Exception as e:
            print(f"[WARN] Could not fetch models for {provider}: {e}")
            continue

    # Pretty print the list
    if providers:
        print("\nAvailable LLM Providers and Models (fetched dynamically):")
        print("=" * 60)
        for p in providers:
            print(f"Provider: {p['provider']}, has total of: {len(p['models'])} models available")
        print("=" * 60 + "\n")
    else:
        print("\nNo LLM providers configured or API keys missing.\n")

    return providers
