import json
from typing import Any, Optional

# Ensure correct import paths if running as part of package 'src'
try:
    from .state import TranslationState
    from .utils import log_to_state
except ImportError: # Fallback for potential direct script execution (less ideal)
    # This might be problematic if state/utils rely on other relative imports
    from state import TranslationState
    from utils import log_to_state


def safe_json_parse(json_string: str, state: TranslationState, node_name: str) -> Optional[Any]:
    """
    Tries to parse JSON, handling common LLM artifacts (like markdown fences)
    and logging errors to the state object.

    Args:
        json_string: The string potentially containing JSON.
        state: The current TranslationState object for logging.
        node_name: The name of the node calling this function (for logging context).

    Returns:
        The parsed JSON object (list or dict) or None if parsing fails.
    """
    if not isinstance(json_string, str):
        log_to_state(state, "Input to safe_json_parse was not a string.", "ERROR", node=node_name)
        return None
    try:
        # Remove potential markdown code fences and leading/trailing whitespace
        cleaned_string = json_string.strip()
        if cleaned_string.startswith("```json"):
            cleaned_string = cleaned_string[len("```json"):].strip()
        if cleaned_string.startswith("```"):
             cleaned_string = cleaned_string[len("```"):].strip()
        if cleaned_string.endswith("```"):
            cleaned_string = cleaned_string[:-len("```")].strip()

        # Handle potential leading non-JSON text before the actual JSON list/object
        # Try finding the start of a list '[' or object '{'
        list_start = cleaned_string.find('[')
        obj_start = cleaned_string.find('{')

        json_start = -1
        if list_start != -1 and obj_start != -1:
            json_start = min(list_start, obj_start)
        elif list_start != -1:
            json_start = list_start
        elif obj_start != -1:
            json_start = obj_start

        if json_start != -1:
            cleaned_string = cleaned_string[json_start:]
            # Find the corresponding closing bracket for validation (simple check)
            # This is basic, complex nested structures might need more robust parsing
            last_brace = cleaned_string.rfind('}')
            last_bracket = cleaned_string.rfind(']')
            json_end = max(last_brace, last_bracket)
            if json_end != -1:
                 cleaned_string = cleaned_string[:json_end+1]
            # else: maybe log a warning if no closing bracket found?

        else:
             # If no '[' or '{' found, assume it's not valid JSON we can easily parse
             raise json.JSONDecodeError("JSON start marker '[' or '{' not found", cleaned_string, 0)


        return json.loads(cleaned_string)
    except json.JSONDecodeError as e:
        log_to_state(state, f"JSON parsing failed: {e}. Raw response start: '{json_string[:200]}...'", "ERROR", node=node_name)
        # Add fallback logic here if needed (e.g., regex extraction)
        return None
    except Exception as e: # Catch other potential errors during cleaning/parsing
         log_to_state(state, f"Unexpected error during JSON processing: {e}", "ERROR", node=node_name)
         return None