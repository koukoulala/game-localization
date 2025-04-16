import yaml
import json
import os # Added for environment variables
import time # Added for potential delays (optional)
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Ensure correct import paths if running as part of package 'src'
try:
    from .state import TranslationState, TerminologyEntry
    from .providers import get_llm_client
    from .utils import log_to_state
    from .node_utils import safe_json_parse, filter_and_prioritize_terminology
    # Exceptions might be needed if error handling within workers is desired
    # from .exceptions import AuthenticationError, RateLimitError, APIError
except ImportError: # Fallback for potential direct script execution (less ideal)
    from .state import TranslationState, TerminologyEntry
    from providers import get_llm_client
    from utils import log_to_state
    from node_utils import safe_json_parse
    # from exceptions import AuthenticationError, RateLimitError, APIError

# --- Worker Functions ---

def translate_chunk_worker(worker_input: Dict[str, Any]) -> Dict[str, Any]:
    """Translates a single chunk. Designed to be run in parallel."""
    NODE_NAME = "translate_chunk_worker" # Logged via result dict
    # Safely get inputs
    state_essentials = worker_input.get("state", {}) # Expecting {'config': {}, 'terminology': []}
    chunk_text = worker_input.get("chunk_text", "")
    # Escape curly braces to avoid prompt template errors
    chunk_text_escaped = chunk_text.replace("{", "{{").replace("}", "}}")
    index = worker_input.get("index", -1)
    original_index = worker_input.get("original_index", -1)
    total_chunks = worker_input.get("total_chunks", 0)

    # Basic input validation
    if not chunk_text or index == -1 or not isinstance(state_essentials.get('config'), dict):
         missing = []
         if not chunk_text: missing.append("chunk_text")
         if index == -1: missing.append("index")
         if not isinstance(state_essentials.get('config'), dict): missing.append("state['config']")
         return {"index": index, "error": f"Worker input missing required fields: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    terminology = state_essentials.get("contextualized_glossary", []) # Use the CORRECT key
    worker_log_prefix = f"Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config)

        # --- Terminology Filtering ---
        try:
            terminology_json = json.dumps(terminology, indent=2)
            # log_to_state(state_essentials, f"{worker_log_prefix}: Full 'contextualized_glossary' received ({len(terminology)} items):\n{terminology_json}", "DEBUG", node=NODE_NAME) # Disabled verbose log
        except Exception as json_err:
            log_to_state(state_essentials, f"{worker_log_prefix}: Could not serialize full terminology for logging: {json_err}", "WARNING", node=NODE_NAME)

        # Note: Using the original (non-escaped) chunk_text for filtering
        filtered_terminology = filter_and_prioritize_terminology(chunk_text, terminology)
        # log_to_state(state_essentials, f"{worker_log_prefix}: Filtered terminology contains {len(filtered_terminology)} items.", "DEBUG", node=NODE_NAME)

        # Build terminology guidance string from the filtered list
        term_guidance_list = []
        for t in filtered_terminology:
            translation = t.get('proposedTranslations', {}).get('default') # Use only proposed
            if t.get('sourceTerm') and translation:
                term_guidance_list.append(f"- '{t['sourceTerm']}' -> '{translation}'")

        term_guidance = "Terminology Glossary:\n" + "\n".join(term_guidance_list) if term_guidance_list else "No specific terminology provided for this chunk."

        prompts_path = Path(__file__).parent.parent / "prompts.yaml"
        with open(prompts_path) as f:
            prompts = yaml.safe_load(f)

        # --- Translation ---
        base_content_type = config.get('content_type', 'technical documentation')
        has_code = "```" in chunk_text
        has_images = "![" in chunk_text
        enhanced_content_type = base_content_type
        if has_code and "code" not in enhanced_content_type.lower():
            enhanced_content_type += " with code blocks"
        if has_images and "image" not in enhanced_content_type.lower():
            enhanced_content_type += " with images"

        # --- Accent Guidance ---
        effective_accent = config.get('effective_accent', 'professional') # Get from config (defaulted in init)
        target_accent_guidance = f"using the {effective_accent} accent/dialect"

        translation_system_prompt = prompts["prompts"]["translation"]["system"].format(
            content_type=enhanced_content_type,
            source_language=config.get('source_language', 'english'),
            target_language=config.get('target_language', 'arabic'),
            chunk_text=chunk_text_escaped,
            filtered_term_guidance=term_guidance, # Pass the filtered glossary
            target_accent_guidance=target_accent_guidance # Pass the accent guidance
        )
        # Log the actual prompt being sent (DEBUG level)
        log_to_state(state_essentials, f"{worker_log_prefix}: Sending translation prompt:\n---\n{translation_system_prompt}\n---", "DEBUG", node=NODE_NAME)

        translation_messages = [("system", translation_system_prompt)]
        translation_prompt_template = ChatPromptTemplate.from_messages(translation_messages)
        translation_chain = translation_prompt_template | llm | StrOutputParser()
        

        translation_response = translation_chain.invoke({})
        translated_text = translation_response
        translation_metadata = getattr(translation_response, 'response_metadata', {})

        if not isinstance(translated_text, str) or not translated_text.strip():
            warning_msg = f"{worker_log_prefix}: Received empty or non-string translation."
            log_to_state(state_essentials, warning_msg, "WARNING", node=NODE_NAME)
            return {
                "index": index,
                "translated_text": "",
                "node_name": NODE_NAME,
                "warning": warning_msg
            }

        # Add chunk size, filtered term count, and original index to the result
        return {
            "index": index,
            "original_index": original_index,
            "translated_text": translated_text,
            "node_name": NODE_NAME,
            # "hallucination_warning": None, # Removed
            "chunk_size": len(chunk_text), # Add original chunk size
            "filtered_term_count": len(filtered_terminology), # Add filtered term count
            "prompt_char_count": len(translation_system_prompt) # Add prompt character count
        }

    except FileNotFoundError:
        return {"index": index, "error": f"{worker_log_prefix}: Prompts file not found at {prompts_path}", "node_name": NODE_NAME}
    except KeyError as e:
        prompt_key = str(e)
        if 'prompts' in locals() and prompt_key in prompts.get("prompts", {}):
            location = f"within '{prompt_key}' prompt definition"
        else:
            location = "accessing top-level prompt keys"
        return {"index": index, "error": f"{worker_log_prefix}: Missing key in prompts file ({location}): {e}", "node_name": NODE_NAME}
    except Exception as e:
        error_msg = f"{worker_log_prefix}: Unexpected error setting up worker or during translation: {type(e).__name__}: {e}"
        return {"index": index, "error": error_msg, "node_name": NODE_NAME}



def _critique_chunk_worker(worker_input: Dict[str, Any]) -> Dict[str, Any]:
    """Critiques a single translated chunk. Designed for parallel execution."""
    NODE_NAME = "critique_chunk_worker"
    state_essentials = worker_input.get("state", {})
    original_chunk = worker_input.get("original_chunk", "")
    translated_chunk = worker_input.get("translated_chunk", "")
    index = worker_input.get("index", -1)
    original_index = worker_input.get("original_index", -1)
    total_chunks = worker_input.get("total_chunks", 0)

    if not original_chunk or not translated_chunk or index == -1 or not isinstance(state_essentials.get('config'), dict):
        missing = [f for f, v in {"original_chunk": original_chunk, "translated_chunk": translated_chunk, "index": index, "state['config']": state_essentials.get('config')}.items() if not v or (f == "index" and v == -1) or (f == "state['config']" and not isinstance(v, dict))]
        return {"index": index, "error": f"Critique worker input missing: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    # Fetch glossary (prefer contextualized if available)
    full_glossary = state_essentials.get("contextualized_glossary", []) # Get the full list
    worker_log_prefix = f"Critique Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config, role="critique") # Use critique-specific client/config if needed

        # Load prompts
        prompts_path = Path(__file__).parent.parent / "prompts.yaml"
        with open(prompts_path) as f:
            prompts = yaml.safe_load(f)

        messages = [
            ("system", prompts["prompts"]["critique"]["system"])
        ]
        prompt_template = ChatPromptTemplate.from_messages(messages)
        chain = prompt_template | llm | StrOutputParser() # Expecting JSON string

        # --- Filter glossary based on original chunk ---
        filtered_glossary = filter_and_prioritize_terminology(original_chunk, full_glossary)
        log_to_state(state_essentials, f"{worker_log_prefix}: Filtered critique glossary contains {len(filtered_glossary)} items.", "DEBUG", node=NODE_NAME)

        # Build guidance string for the prompt
        critique_term_list = []
        for t in filtered_glossary:
            translation = t.get('proposedTranslations', {}).get('default') # Use only proposed
            if t.get('sourceTerm') and translation:
                critique_term_list.append(f"- '{t['sourceTerm']}' -> '{translation}'")
        critique_term_guidance = "\n".join(critique_term_list) if critique_term_list else "No specific terminology provided for this chunk."

        # --- Accent Guidance ---
        effective_accent = config.get('effective_accent', 'professional')
        target_accent_guidance = f"using the {effective_accent} accent/dialect"

        critique_context = {
            "filtered_glossary_guidance": critique_term_guidance, # Pass filtered guidance
            "original_text": original_chunk,
            "translated_text": translated_chunk,
            "target_accent_guidance": target_accent_guidance # Pass the accent guidance
        }

        response = chain.invoke(critique_context)

        # Log the formatted prompt AFTER invoking
        try:
            # Format the prompt using the context that was actually sent
            formatted_critique_prompt = prompts["prompts"]["critique"]["system"].format(**critique_context)
            # log_to_state(state_essentials, f"{worker_log_prefix}: Critique prompt sent (using filtered glossary):\n---\n{formatted_critique_prompt}\n---", "DEBUG", node=NODE_NAME)
        except KeyError as fmt_err:
             log_to_state(state_essentials, f"{worker_log_prefix}: Error formatting critique prompt for logging: Missing key {fmt_err}", "WARNING", node=NODE_NAME)
        except Exception as log_err:
             log_to_state(state_essentials, f"{worker_log_prefix}: Error formatting critique prompt for logging: {log_err}", "WARNING", node=NODE_NAME)

        metadata = getattr(response, 'response_metadata', {})

        # Parse the JSON critique (using a temporary state for logging within safe_parse)
        temp_state_for_logging = {"logs": [], "job_id": state_essentials.get("job_id", "unknown")}
        critique_data = safe_json_parse(response, temp_state_for_logging, NODE_NAME) # Use safe parse

        if critique_data is None:
            # safe_json_parse already logged the error
             return {"index": index, "error": f"{worker_log_prefix}: Failed to parse critique JSON.", "node_name": NODE_NAME, "logs": temp_state_for_logging["logs"]}

        # Basic validation of critique structure based on prompt definition
        required_keys = ["accuracyScore", "glossaryAdherence", "suggestedImprovements", "overallAssessment"]
        if not isinstance(critique_data, dict) or not all(key in critique_data for key in required_keys):
             log_message = f"{worker_log_prefix}: Invalid critique structure received. Missing keys or not a dict."
             # Log the received data for debugging
             log_to_state(temp_state_for_logging, f"Received critique data: {critique_data}", "DEBUG", node=NODE_NAME)
             return {"index": index, "error": log_message, "critique_raw": response, "node_name": NODE_NAME, "logs": temp_state_for_logging["logs"]}


        return {
            "index": index,
            "original_index": original_index,
            "critique": critique_data, # Parsed critique
            "node_name": NODE_NAME,
            "logs": temp_state_for_logging["logs"] # Include logs from safe_json_parse
        }

    except FileNotFoundError:
        return {"index": index, "error": f"{worker_log_prefix}: Prompts file not found.", "node_name": NODE_NAME}
    except KeyError as e:
        return {"index": index, "error": f"{worker_log_prefix}: Missing key in prompts file: {e}", "node_name": NODE_NAME}
    # except (AuthenticationError, RateLimitError, APIError) as e:
    #     error_msg = f"{worker_log_prefix}: API Error ({type(e).__name__}) during critique: {e}"
    #     return {"index": index, "error": error_msg, "node_name": NODE_NAME, "token_usage": result_token_usage}
    except Exception as e:
        error_msg = f"{worker_log_prefix}: Unexpected error during critique: {type(e).__name__}: {e}"
        return {"index": index, "error": error_msg, "node_name": NODE_NAME}


def _finalize_chunk_worker(worker_input: Dict[str, Any]) -> Dict[str, Any]:
    """Applies critique feedback to refine a translated chunk."""
    NODE_NAME = "finalize_chunk_worker"
    state_essentials = worker_input.get("state", {})
    original_chunk = worker_input.get("original_chunk", "")
    translated_chunk = worker_input.get("translated_chunk", "")
    critique = worker_input.get("critique", {}) # Expecting parsed critique dict
    index = worker_input.get("index", -1)
    original_index = worker_input.get("original_index", -1)
    total_chunks = worker_input.get("total_chunks", 0)

    # Input validation
    if not original_chunk or not translated_chunk or not critique or index == -1 or not isinstance(state_essentials.get('config'), dict):
        missing = [f for f, v in {"original_chunk": original_chunk, "translated_chunk": translated_chunk, "critique": critique, "index": index, "state['config']": state_essentials.get('config')}.items() if not v or (f == "index" and v == -1) or (f == "state['config']" and not isinstance(v, dict))]
        return {"index": index, "error": f"Finalize worker input missing: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    full_glossary = state_essentials.get("contextualized_glossary", []) # Get full glossary
    worker_log_prefix = f"Finalize Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config, role="refine") # Use refine-specific client/config

        # Load prompts
        prompts_path = Path(__file__).parent.parent / "prompts.yaml"
        with open(prompts_path) as f:
            prompts = yaml.safe_load(f)

        # Use the correct prompt key from prompts.yaml
        messages = [
            ("system", prompts["prompts"]["final_translation"]["system"])
        ]
        prompt_template = ChatPromptTemplate.from_messages(messages)
        chain = prompt_template | llm | StrOutputParser() # Expecting refined text

        # --- Filter glossary based on original chunk ---
        filtered_glossary = filter_and_prioritize_terminology(original_chunk, full_glossary)
        log_to_state(state_essentials, f"{worker_log_prefix}: Filtered finalization glossary contains {len(filtered_glossary)} items.", "DEBUG", node=NODE_NAME)

        # Build guidance string for the prompt
        final_term_list = []
        for t in filtered_glossary:
            translation = t.get('proposedTranslations', {}).get('default') # Use only proposed
            if t.get('sourceTerm') and translation:
                final_term_list.append(f"- '{t['sourceTerm']}' -> '{translation}'")
        final_term_guidance = "\n".join(final_term_list) if final_term_list else "No specific terminology provided for this chunk."

        # --- Accent Guidance ---
        effective_accent = config.get('effective_accent', 'professional')
        target_accent_guidance = f"using the {effective_accent} accent/dialect"

        finalize_context = {
            "source_language": config.get("source_language", "english"),
            "target_language": config.get("target_language", "arabic"),
            "original_text": original_chunk,
            "initial_translation": translated_chunk, # Keep initial translation context
            "critique_feedback": json.dumps(critique, indent=2),
            "basic_translation": translated_chunk, # Keep basic translation context (might be redundant)
            "filtered_glossary_guidance": final_term_guidance, # Pass filtered guidance
            "target_accent_guidance": target_accent_guidance # Pass the accent guidance
        }

        response = chain.invoke(finalize_context)

        # Log the formatted prompt AFTER invoking
        try:
            # Format the prompt using the context that was actually sent
            formatted_finalize_prompt = prompts["prompts"]["final_translation"]["system"].format(**finalize_context)
            # log_to_state(state_essentials, f"{worker_log_prefix}: Finalize prompt sent (using filtered glossary):\n---\n{formatted_finalize_prompt}\n---", "DEBUG", node=NODE_NAME)
        except KeyError as fmt_err:
             log_to_state(state_essentials, f"{worker_log_prefix}: Error formatting finalize prompt for logging: Missing key {fmt_err}", "WARNING", node=NODE_NAME)
        except Exception as log_err:
             log_to_state(state_essentials, f"{worker_log_prefix}: Error formatting finalize prompt for logging: {log_err}", "WARNING", node=NODE_NAME)

        metadata = getattr(response, 'response_metadata', {})

        refined_text = response # Assume StrOutputParser returns string

        if not isinstance(refined_text, str) or not refined_text.strip():
             return {"index": index, "error": f"{worker_log_prefix}: Received empty or non-string refined translation.", "node_name": NODE_NAME}

        # Add relevant counts to the result
        return {
            "index": index,
            "original_index": original_index,
            "refined_text": refined_text,
            "node_name": NODE_NAME,
            "prompt_char_count": len(formatted_finalize_prompt) if 'formatted_finalize_prompt' in locals() else 0, # Add prompt char count
            "filtered_term_count": len(filtered_glossary) # Add filtered term count
        }

    except FileNotFoundError:
        return {"index": index, "error": f"{worker_log_prefix}: Prompts file not found.", "node_name": NODE_NAME}
    except KeyError as e:
        return {"index": index, "error": f"{worker_log_prefix}: Missing key in prompts file: {e}", "node_name": NODE_NAME}
    # except (AuthenticationError, RateLimitError, APIError) as e:
    #     error_msg = f"{worker_log_prefix}: API Error ({type(e).__name__}) during refinement: {e}"
    #     return {"index": index, "error": error_msg, "node_name": NODE_NAME, "token_usage": result_token_usage}
    except Exception as e:
        error_msg = f"{worker_log_prefix}: Unexpected error during refinement: {type(e).__name__}: {e}"
        return {"index": index, "error": error_msg, "node_name": NODE_NAME}
