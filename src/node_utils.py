import json
import re
from typing import Any, Optional, List, Dict

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


# --- Terminology Filtering ---

def filter_and_prioritize_terminology(
    chunk_text: str,
    full_terminology: List[Dict[str, Any]],
    max_terms: int = 20
) -> List[Dict[str, Any]]:
    """
    Filters a terminology list to include only terms present in the chunk_text,
    prioritizing by frequency if the list exceeds max_terms.

    Args:
        chunk_text: The text content of the current chunk.
        full_terminology: The complete list of terminology entries (dicts).
                          Each dict is expected to have at least a 'sourceTerm' key.
        max_terms: The maximum number of terminology entries to return.

    Returns:
        A list of terminology entries found in the chunk, sorted by frequency
        (descending) if truncated, otherwise in the order they were found.
    """
    term_counts = {}
    found_terms_list = [] # Keep order for cases <= max_terms

    if not chunk_text or not full_terminology:
        return []

    for term_entry in full_terminology:
        source_term = term_entry.get("sourceTerm")
        if not source_term or not isinstance(source_term, str):
            # Log or handle missing/invalid sourceTerm if necessary
            continue

        # Use regex for case-insensitive, whole-word matching
        # Escape special regex characters in the source term
        escaped_term = re.escape(source_term)
        try:
            # Find all non-overlapping matches
            matches = re.findall(r'\b' + escaped_term + r'\b', chunk_text, re.IGNORECASE)
            count = len(matches)

            if count > 0:
                # Store the original entry and its count
                term_counts[source_term] = {"entry": term_entry, "count": count}
                found_terms_list.append(term_entry) # Add to ordered list

        except re.error as e:
            # Log regex compilation errors if needed
            # print(f"Regex error for term '{source_term}': {e}") # Example logging
            continue # Skip term if regex is invalid

    if len(term_counts) <= max_terms:
        # Return in the order they were found in the original list
        # Filter found_terms_list to ensure it only contains terms actually counted
        return [entry for entry in found_terms_list if entry.get("sourceTerm") in term_counts]

    else:
        # Sort by count (descending) and then alphabetically by term for stable sorting
        sorted_terms = sorted(
            term_counts.values(),
            key=lambda item: (-item["count"], item["entry"].get("sourceTerm", "").lower())
        )
        # Return only the entries from the top max_terms
        return [item["entry"] for item in sorted_terms[:max_terms]]