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
    from .node_utils import safe_json_parse
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
    index = worker_input.get("index", -1)
    total_chunks = worker_input.get("total_chunks", 0)

    # Basic input validation
    if not chunk_text or index == -1 or not isinstance(state_essentials.get('config'), dict):
         missing = []
         if not chunk_text: missing.append("chunk_text")
         if index == -1: missing.append("index")
         if not isinstance(state_essentials.get('config'), dict): missing.append("state['config']")
         return {"index": index, "error": f"Worker input missing required fields: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    terminology = state_essentials.get("terminology", [])
    worker_log_prefix = f"Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config)

        # Build terminology guidance
        term_guidance_list = []
        for t in terminology:
            translation = t.get('approvedTranslation') or t.get('proposedTranslations', {}).get('default')
            if t.get('sourceTerm') and translation:
                term_guidance_list.append(f"- '{t['sourceTerm']}' -> '{translation}'")

        term_guidance = "Terminology Glossary:\n" + "\n".join(term_guidance_list) if term_guidance_list else "No specific terminology provided."

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

        translation_system_prompt = prompts["prompts"]["translation"]["system"].format(
            content_type=enhanced_content_type,
            source_language=config.get('source_language', 'english'),
            target_language=config.get('target_language', 'arabic')
        )
        translation_human_prompt = prompts["prompts"]["translation"]["human"].format(
            term_guidance=term_guidance,
            source_language=config.get('source_language', 'english'),
            target_language=config.get('target_language', 'arabic'),
            chunk_text=chunk_text
        )
        if has_images or has_code:
            reminder = f"\n⚠️ CRITICAL REMINDER: This chunk contains {'BOTH IMAGES AND CODE BLOCKS' if has_images and has_code else ('IMAGES' if has_images else 'CODE BLOCKS')}. You MUST translate ALL text to {config.get('target_language','arabic')} EXCEPT image references and code blocks.\n\n"
            translation_human_prompt = reminder + translation_human_prompt

        translation_messages = [("system", translation_system_prompt), ("human", translation_human_prompt)]
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

        # --- Verification ---
        verification_context = {
            "source_language": config.get('source_language', 'english'),
            "target_language": config.get('target_language', 'arabic'),
            "translated_text": translated_text
        }
        raw_verification_system_prompt = prompts["prompts"]["translation_verification"]["system"]
        raw_verification_human_prompt = prompts["prompts"]["translation_verification"]["human"]

        verification_messages = [("system", raw_verification_system_prompt), ("human", raw_verification_human_prompt)]
        verification_prompt_template = ChatPromptTemplate.from_messages(verification_messages)
        verification_chain = verification_prompt_template | llm | StrOutputParser()

        verification_response_str = verification_chain.invoke(verification_context)
        verification_metadata = getattr(verification_response_str, 'response_metadata', {})

        hallucination_warning = None
        try:
            # Strip Markdown code block formatting if present
            cleaned_verification_str = verification_response_str.strip()
            if cleaned_verification_str.startswith("```"):
                # Remove leading ``` and optional language tag
                first_newline = cleaned_verification_str.find('\n')
                if first_newline != -1:
                    cleaned_verification_str = cleaned_verification_str[first_newline+1:]
                # Remove trailing ```
                if cleaned_verification_str.endswith("```"):
                    cleaned_verification_str = cleaned_verification_str[:-3].rstrip()
            else:
                cleaned_verification_str = verification_response_str

            verification_data = json.loads(cleaned_verification_str)
            is_valid = verification_data.get("isValid", False)
            reason = verification_data.get("reason", "")

            if not is_valid:
                hallucination_warning = f"{worker_log_prefix}: Potential hallucination detected during verification. Reason: '{reason}'. Raw: '{verification_response_str[:100]}...'"
                log_to_state(state_essentials, hallucination_warning, "WARNING", node=NODE_NAME)

        except json.JSONDecodeError:
            hallucination_warning = f"{worker_log_prefix}: Failed to parse verification JSON response. Raw: '{verification_response_str[:100]}...'"
            log_to_state(state_essentials, hallucination_warning, "WARNING", node=NODE_NAME)

        return {
            "index": index,
            "translated_text": translated_text,
            "node_name": NODE_NAME,
            "hallucination_warning": hallucination_warning
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

    # --- Catch errors outside the retry loop (e.g., LLM init, prompt loading) ---
    except FileNotFoundError:
         return {"index": index, "error": f"{worker_log_prefix}: Prompts file not found at {prompts_path}", "node_name": NODE_NAME} # Use aggregated usage
    except KeyError as e:
         # Check if prompts was loaded before erroring
         prompt_key = str(e)
         if 'prompts' in locals() and prompt_key in prompts.get("prompts", {}):
             location = f"within '{prompt_key}' prompt definition"
         else:
             location = "accessing top-level prompt keys"
         return {"index": index, "error": f"{worker_log_prefix}: Missing key in prompts file ({location}): {e}", "node_name": NODE_NAME}
    except Exception as e:
        error_msg = f"{worker_log_prefix}: Unexpected error setting up worker or during non-retryable phase: {type(e).__name__}: {e}"
        return {"index": index, "error": error_msg, "node_name": NODE_NAME} # Use aggregated usage


def _critique_chunk_worker(worker_input: Dict[str, Any]) -> Dict[str, Any]:
    """Critiques a single translated chunk. Designed for parallel execution."""
    NODE_NAME = "critique_chunk_worker"
    state_essentials = worker_input.get("state", {})
    original_chunk = worker_input.get("original_chunk", "")
    translated_chunk = worker_input.get("translated_chunk", "")
    index = worker_input.get("index", -1)
    total_chunks = worker_input.get("total_chunks", 0)

    if not original_chunk or not translated_chunk or index == -1 or not isinstance(state_essentials.get('config'), dict):
        missing = [f for f, v in {"original_chunk": original_chunk, "translated_chunk": translated_chunk, "index": index, "state['config']": state_essentials.get('config')}.items() if not v or (f == "index" and v == -1) or (f == "state['config']" and not isinstance(v, dict))]
        return {"index": index, "error": f"Critique worker input missing: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    # Fetch glossary (prefer contextualized if available)
    glossary = state_essentials.get("contextualized_glossary", state_essentials.get("glossary", {}))
    worker_log_prefix = f"Critique Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config, role="critique") # Use critique-specific client/config if needed

        # Load prompts
        prompts_path = Path(__file__).parent.parent / "prompts.yaml"
        with open(prompts_path) as f:
            prompts = yaml.safe_load(f)

        messages = [
            ("system", prompts["prompts"]["critique"]["system"]),
            ("human", prompts["prompts"]["critique"]["human"])
        ]
        prompt_template = ChatPromptTemplate.from_messages(messages)
        chain = prompt_template | llm | StrOutputParser() # Expecting JSON string

        response = chain.invoke({
            # Pass the expected variables based on the error log
            "glossary": json.dumps(glossary) if glossary else "No glossary provided.", # Pass glossary as JSON string or placeholder
            "original_text": original_chunk,
            "translated_text": translated_chunk
        })

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
    total_chunks = worker_input.get("total_chunks", 0)

    # Input validation
    if not original_chunk or not translated_chunk or not critique or index == -1 or not isinstance(state_essentials.get('config'), dict):
        missing = [f for f, v in {"original_chunk": original_chunk, "translated_chunk": translated_chunk, "critique": critique, "index": index, "state['config']": state_essentials.get('config')}.items() if not v or (f == "index" and v == -1) or (f == "state['config']" and not isinstance(v, dict))]
        return {"index": index, "error": f"Finalize worker input missing: {', '.join(missing)}", "node_name": NODE_NAME}

    config = state_essentials.get("config", {})
    worker_log_prefix = f"Finalize Chunk {index + 1}/{total_chunks}"

    try:
        llm = get_llm_client(config, role="refine") # Use refine-specific client/config

        # Load prompts
        prompts_path = Path(__file__).parent.parent / "prompts.yaml"
        with open(prompts_path) as f:
            prompts = yaml.safe_load(f)

        # Use the correct prompt key from prompts.yaml
        messages = [
            ("system", prompts["prompts"]["final_translation"]["system"]),
            ("human", prompts["prompts"]["final_translation"]["human"])
        ]
        prompt_template = ChatPromptTemplate.from_messages(messages)
        chain = prompt_template | llm | StrOutputParser() # Expecting refined text

        response = chain.invoke({
            "source_language": config.get("source_language", "english"),
            "target_language": config.get("target_language", "arabic"),
            "original_text": original_chunk,
            "initial_translation": translated_chunk,
            "critique_feedback": json.dumps(critique, indent=2), # Pass critique as JSON string
            # Add missing variable expected by the 'final_translation' prompt
            "basic_translation": translated_chunk,
            "glossary": json.dumps(state_essentials.get("contextualized_glossary", state_essentials.get("glossary", {}))) # Pass glossary
        })

        metadata = getattr(response, 'response_metadata', {})

        refined_text = response # Assume StrOutputParser returns string

        if not isinstance(refined_text, str) or not refined_text.strip():
             return {"index": index, "error": f"{worker_log_prefix}: Received empty or non-string refined translation.", "node_name": NODE_NAME}

        return {
            "index": index,
            "refined_text": refined_text,
            "node_name": NODE_NAME
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
