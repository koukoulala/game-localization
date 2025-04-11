import concurrent.futures
import time # Keep for potential future use (e.g., delays)
from typing import Dict, Any, List
import os

# Ensure correct import paths if running as part of package 'src'
try:
    from .state import TranslationState
    from .utils import log_to_state, update_progress
    from .node_workers import translate_chunk_worker
    # from .exceptions import ... # Import if specific exceptions need handling here
except ImportError: # Fallback for potential direct script execution (less ideal)
    from .state import TranslationState
    from utils import log_to_state, update_progress
    from node_workers import translate_chunk_worker
    # from exceptions import ...

# --- Translation Node Implementation ---

def run_parallel_translation(state: TranslationState) -> TranslationState:
    """
    Translates document chunks in parallel using worker nodes.

    This node orchestrates the parallel execution of the `translate_chunk_worker`.
    It prepares inputs for each worker, manages the thread pool, collects results,
    updates the state with translated chunks and aggregated token usage, and logs
    progress and errors.
    """
    NODE_NAME = "run_parallel_translation"
    update_progress(state, NODE_NAME, 20.0) # Example starting progress for this stage

    chunks = state.get("chunks")
    if not chunks:
        log_to_state(state, "No chunks found to translate.", "ERROR", node=NODE_NAME)
        state["error_info"] = "Cannot translate: Document was not chunked."
        # Ensure translated_chunks is empty if chunks are missing
        state["translated_chunks"] = []
        return state

    if not state.get("translated_chunks"):
         # Initialize if chunking happened but this somehow got reset
         state["translated_chunks"] = [None] * len(chunks)
         log_to_state(state, "Initialized empty translated_chunks list.", "DEBUG", node=NODE_NAME)


    config = state.get("config", {})
    terminology = state.get("contextualized_glossary", []) # Use the CORRECT key from state.py
    # Add logging to check terminology right after retrieval
    # log_to_state(state, f"Retrieved 'contextualized_glossary' from state. Type: {type(terminology)}, Length: {len(terminology) if isinstance(terminology, list) else 'N/A'}", "DEBUG", node=NODE_NAME)

    total_chunks = len(chunks)
    state["parallel_worker_results"] = [] # Reset results list for this run

    # Prepare inputs for each worker
    worker_inputs = []
    for i, chunk_text in enumerate(chunks):
        # Only pass essential state parts to workers
        state_essentials = {
            "config": config,
            "contextualized_glossary": terminology, # Pass using the CORRECT key
            "job_id": state.get("job_id") # Pass job_id for potential logging wetithin worker
        }
        term_in_essentials = state_essentials.get("contextualized_glossary", "MISSING") # Check the CORRECT key

        # Add logging to check state_essentials before adding to worker_inputs
        # log_to_state(state, f"Prepared state_essentials for chunk {i}. Terminology type: {type(term_in_essentials)}, Length: {len(term_in_essentials) if isinstance(term_in_essentials, list) else 'N/A'}", "DEBUG", node=NODE_NAME)

        worker_inputs.append({
            "state": state_essentials,
            "chunk_text": chunk_text,
            "index": i,
            "total_chunks": total_chunks
        })

    # Determine max workers (consider API limits and CPU cores)
    # Priority: .env > config > default
    max_workers_env = os.getenv("MAX_PARALLEL_WORKERS")
    if max_workers_env is not None:
        try:
            configured_max_workers = int(max_workers_env)
        except ValueError:
            configured_max_workers = config.get("max_parallel_workers", 5)
    else:
        configured_max_workers = config.get("max_parallel_workers", 5)

    # Ensure we don't use more workers than chunks
    actual_workers = min(configured_max_workers, total_chunks)

    log_to_state(state, f"Starting parallel translation for {total_chunks} chunks using {actual_workers} workers (max configured: {configured_max_workers}).", "INFO", node=NODE_NAME)

    completed_count = 0

    # Use ThreadPoolExecutor for I/O-bound tasks (like API calls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
        # Submit all tasks
        future_to_index = {executor.submit(translate_chunk_worker, inp): inp["index"] for inp in worker_inputs}

        # Process completed futures as they finish
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                state["parallel_worker_results"].append(result) # Store raw result


                if "error" in result:
                    log_to_state(state, f"Worker error (Chunk {index + 1}/{total_chunks}): {result['error']}", "ERROR", node=NODE_NAME)
                    
                elif "translated_text" in result:
                    state["translated_chunks"][index] = result["translated_text"]
                    # Extract additional info from result for logging
                    chunk_size = result.get("chunk_size", "N/A")
                    term_count = result.get("filtered_term_count", "N/A")
                    prompt_chars = result.get("prompt_char_count", "N/A") # Get prompt char count
                    log_to_state(state, f"Successfully translated chunk {index + 1}/{total_chunks} (Size: {chunk_size} chars, Terms: {term_count}, Prompt Chars: {prompt_chars}).", "DEBUG", node=NODE_NAME)
                else:
                    # Should not happen if worker logic is correct, but handle defensively
                    log_to_state(state, f"Worker for chunk {index + 1}/{total_chunks} returned unexpected result: {result}", "WARNING", node=NODE_NAME)

            except Exception as e:
                # Catch exceptions raised *during* future.result() call (e.g., worker raised unhandled exception)
                log_to_state(state, f"Exception processing result for chunk {index + 1}/{total_chunks}: {type(e).__name__}: {e}", "ERROR", node=NODE_NAME)
                state["parallel_worker_results"].append({"index": index, "error": f"Future processing exception: {e}", "node_name": "run_parallel_translation_executor"})
                

            completed_count += 1
            current_progress = 20.0 + (completed_count / total_chunks) * 40.0 # Example: translation is 40% of total progress
            update_progress(state, NODE_NAME, current_progress)


    # Log final aggregated token usage for this node

    # Sanity check: Ensure translated_chunks has the correct length
    if len(state["translated_chunks"]) != total_chunks:
        log_to_state(state, f"Mismatch in translated_chunks length! Expected {total_chunks}, got {len(state['translated_chunks'])}", "ERROR", node=NODE_NAME)
        # Attempt to fix or pad if possible, otherwise flag error
        # This indicates a potential logic error in the parallel processing loop
        state["error_info"] = state.get("error_info", "") + " | Length mismatch in translated chunks."
        # Pad with None to avoid downstream index errors, though data is likely corrupt
        state["translated_chunks"].extend([None] * (total_chunks - len(state["translated_chunks"])))


    # Check if any chunks failed (are still None)
    failed_chunks = [i + 1 for i, chunk in enumerate(state["translated_chunks"]) if chunk is None]
    if failed_chunks:
        log_to_state(state, f"Translation failed for chunks: {failed_chunks}", "WARNING", node=NODE_NAME)
        current_error_info = state.get("error_info") or "" # Default to empty string if None or empty
        state["error_info"] = current_error_info + f" | Failed to translate chunks: {failed_chunks}"

    update_progress(state, NODE_NAME, 60.0) # Mark end of this stage
    return state