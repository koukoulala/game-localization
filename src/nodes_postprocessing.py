import concurrent.futures
import time
import json # Needed for apply_review_feedback
from typing import Dict, Any, List

# Ensure correct import paths if running as part of package 'src'
try:
    from .state import TranslationState
    from .utils import log_to_state, update_progress
    from .node_workers import _critique_chunk_worker, _finalize_chunk_worker
    # from .exceptions import ... # Import if specific exceptions need handling here
    # from .node_utils import ... # Import if needed
except ImportError: # Fallback for potential direct script execution (less ideal)
    from .state import TranslationState
    from utils import log_to_state, update_progress
    from node_workers import _critique_chunk_worker, _finalize_chunk_worker
    # from exceptions import ...
    # from node_utils import ...


# --- Postprocessing, Review, and Finalization Node Implementations ---

def critique_node(state: TranslationState) -> TranslationState:
    """
    Critiques each translated chunk in parallel using worker nodes.

    Orchestrates the parallel execution of `_critique_chunk_worker`.
    Collects critique results, logs errors, and updates the state.
    """
    NODE_NAME = "critique_node"
    update_progress(state, NODE_NAME, 65.0) # Example progress

    original_chunks = state.get("chunks")
    translated_chunks = state.get("translated_chunks")

    if not original_chunks or not translated_chunks or len(original_chunks) != len(translated_chunks):
        log_to_state(state, "Mismatch or missing chunks/translations for critique.", "ERROR", node=NODE_NAME)
        # Ensure error_info is treated as a string
        current_error = state.get("error_info") or ""
        state["error_info"] = current_error + (" | " if current_error else "") + "Cannot critique: Chunk data inconsistent."
        state["critiques"] = [] # Ensure critiques list is empty/reset
        return state

    # Filter out chunks that failed translation (are None)
    valid_indices = [i for i, t in enumerate(translated_chunks) if t is not None]
    if len(valid_indices) < len(original_chunks):
        log_to_state(state, f"Skipping critique for {len(original_chunks) - len(valid_indices)} chunks that failed translation.", "WARNING", node=NODE_NAME)

    if not valid_indices:
        log_to_state(state, "No valid translated chunks to critique.", "WARNING", node=NODE_NAME)
        # Initialize critiques with error dicts for skipped chunks
        state["critiques"] = [{"error": "Critique skipped due to failed translation"}] * len(original_chunks)
        return state

    config = state.get("config", {})
    total_valid_chunks = len(valid_indices)
    # Initialize critiques list: put error dict for failed chunks, None for valid ones to be processed
    state["critiques"] = [
        {"error": "Critique skipped due to failed translation"} if i not in valid_indices else None
        for i in range(len(original_chunks))
    ]
    state["parallel_worker_results"] = [] # Reset results list

    # Prepare inputs only for valid chunks
    worker_inputs = []
    for i in valid_indices:
        state_essentials = {
            "config": config,
            "job_id": state.get("job_id")
        }
        worker_inputs.append({
            "state": state_essentials,
            "original_chunk": original_chunks[i],
            "translated_chunk": translated_chunks[i],
            "index": i, # Use original index
            "total_chunks": len(original_chunks) # Report total original chunks
        })

    max_workers = config.get("max_parallel_workers", 5)
    log_to_state(state, f"Starting parallel critique for {total_valid_chunks} translated chunks.", "INFO", node=NODE_NAME)

    completed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(_critique_chunk_worker, inp): inp["index"] for inp in worker_inputs}

        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                state["parallel_worker_results"].append(result) # Store raw result


                # Log any logs returned from the worker (e.g., from safe_json_parse)
                worker_logs = result.get("logs", [])
                for log_entry in worker_logs:
                    # Re-log under the main critique_node context if needed, or just store
                    log_to_state(state, f"(Worker Log Chunk {index+1}): {log_entry.get('message', '')}", log_entry.get('level', 'DEBUG'), node=f"{NODE_NAME}/{result.get('node_name', 'critique_worker')}")


                if "error" in result:
                    error_message = f"Critique worker error (Chunk {index + 1}): {result['error']}"
                    log_to_state(state, error_message, "ERROR", node=NODE_NAME)
                    state["critiques"][index] = {"error": error_message} # Store error dict instead of None
                elif "critique" in result:
                    state["critiques"][index] = result["critique"] # Store the parsed critique
                    log_to_state(state, f"Successfully critiqued chunk {index + 1}.", "DEBUG", node=NODE_NAME)
                else:
                    log_to_state(state, f"Critique worker for chunk {index + 1} returned unexpected result: {result}", "WARNING", node=NODE_NAME)
                    state["critiques"][index] = {"error": "Unexpected critique worker result"} # Store error dict

            except Exception as e:
                log_to_state(state, f"Exception processing critique result for chunk {index + 1}: {type(e).__name__}: {e}", "ERROR", node=NODE_NAME)
                error_message = f"Future processing exception: {e}"
                state["parallel_worker_results"].append({"index": index, "error": error_message, "node_name": "critique_node_executor"})
                state["critiques"][index] = {"error": error_message} # Store error dict instead of None

            completed_count += 1
            # Update progress based on valid chunks processed
            current_progress = 65.0 + (completed_count / total_valid_chunks) * 15.0 # Example: critique is 15%
            update_progress(state, NODE_NAME, current_progress)



    update_progress(state, NODE_NAME, 80.0) # Mark end of critique stage
    return state


def verify_consistency(state: TranslationState) -> TranslationState:
    """Checks for consistency across translated chunks (placeholder)."""
    NODE_NAME = "verify_consistency"
    update_progress(state, NODE_NAME, 82.0)
    log_to_state(state, "Running consistency verification (Placeholder)...", "INFO", node=NODE_NAME)

    # Placeholder logic:
    # - Could compare terminology usage across chunks.
    # - Could check for consistent formatting or style.
    # - Could use another LLM call to evaluate overall consistency.
    # For now, just logs and moves on.

    translated_chunks = state.get("translated_chunks", [])
    critiques = state.get("critiques", [])

    if not translated_chunks or not critiques or len(translated_chunks) != len(critiques):
         log_to_state(state, "Inconsistent data for consistency check.", "WARNING", node=NODE_NAME)
         return state

    # Example: Check if any critiques flagged major consistency issues (if critique format supports this)
    consistency_issues_found = False
    for i, critique in enumerate(critiques):
        if critique and isinstance(critique, dict):
            # Assuming critique['issues'] is a list of dicts with a 'type' field
            issues = critique.get("issues", [])
            if any(issue.get("type") == "consistency" for issue in issues if isinstance(issue, dict)):
                 log_to_state(state, f"Potential consistency issue flagged by critique in chunk {i+1}.", "WARNING", node=NODE_NAME)
                 consistency_issues_found = True
                 # Could add more detail here

    if consistency_issues_found:
        # TODO: add logic for handling consistency_issues_found
        pass

    log_to_state(state, "Consistency verification step complete.", "INFO", node=NODE_NAME)
    update_progress(state, NODE_NAME, 85.0)
    return state




def final_translation_node(state: TranslationState) -> TranslationState:
    """
    Performs a final refinement pass on translated chunks, potentially using critiques.
    This acts like `run_parallel_translation` but uses the `_finalize_chunk_worker`.
    """
    NODE_NAME = "final_translation_node"
    update_progress(state, NODE_NAME, 80.0) # Start after critique

    original_chunks = state.get("chunks")
    translated_chunks = state.get("translated_chunks")
    critiques = state.get("critiques")

    # Check if refinement is needed/possible

    if not original_chunks or not translated_chunks or not critiques or \
       len(original_chunks) != len(translated_chunks) or len(original_chunks) != len(critiques):
        log_to_state(state, "Mismatch or missing data for final refinement.", "ERROR", node=NODE_NAME)
        # Ensure error_info is treated as a string, even if it's None initially
        current_error = state.get("error_info") or ""
        state["error_info"] = current_error + (" | " if current_error else "") + "Cannot refine: Data inconsistent."
        state["final_chunks"] = translated_chunks # Pass through existing translations on error
        return state

    # Identify chunks to refine (e.g., those with critiques indicating issues or below a score threshold)
    # Or refine all chunks that have a critique.
    indices_to_refine = [i for i, c in enumerate(critiques) if c is not None and translated_chunks[i] is not None]

    if not indices_to_refine:
        log_to_state(state, "No chunks require final refinement based on critiques.", "INFO", node=NODE_NAME)
        state["final_chunks"] = list(translated_chunks) # Copy to final_chunks
        update_progress(state, NODE_NAME, 95.0)
        return state

    config = state.get("config", {})
    total_to_refine = len(indices_to_refine)
    state["final_chunks"] = list(translated_chunks) # Initialize final_chunks with current translations
    state["parallel_worker_results"] = [] # Reset results list

    # Prepare inputs for refinement workers
    worker_inputs = []
    for i in indices_to_refine:
        state_essentials = {
            "config": config,
            "job_id": state.get("job_id")
        }
        worker_inputs.append({
            "state": state_essentials,
            "original_chunk": original_chunks[i],
            "translated_chunk": translated_chunks[i],
            "critique": critiques[i], # Pass the critique data
            "index": i,
            "total_chunks": len(original_chunks)
        })

    max_workers = config.get("max_parallel_workers", 5)
    log_to_state(state, f"Starting parallel final refinement for {total_to_refine} chunks.", "INFO", node=NODE_NAME)

    completed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(_finalize_chunk_worker, inp): inp["index"] for inp in worker_inputs}

        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                state["parallel_worker_results"].append(result)


                if "error" in result:
                    log_to_state(state, f"Refinement worker error (Chunk {index + 1}): {result['error']}", "ERROR", node=NODE_NAME)
                    # Keep the original translation in final_chunks[index]
                elif "refined_text" in result:
                    state["final_chunks"][index] = result["refined_text"] # Update with refined text
                    log_to_state(state, f"Successfully refined chunk {index + 1}.", "DEBUG", node=NODE_NAME)
                else:
                    log_to_state(state, f"Refinement worker for chunk {index + 1} returned unexpected result: {result}", "WARNING", node=NODE_NAME)

            except Exception as e:
                log_to_state(state, f"Exception processing refinement result for chunk {index + 1}: {type(e).__name__}: {e}", "ERROR", node=NODE_NAME)
                state["parallel_worker_results"].append({"index": index, "error": f"Future processing exception: {e}", "node_name": "final_translation_node_executor"})
                # Keep original translation

            completed_count += 1
            current_progress = 80.0 + (completed_count / total_to_refine) * 15.0 # Example: refinement is 15%
            update_progress(state, NODE_NAME, current_progress)


    update_progress(state, NODE_NAME, 95.0) # Mark end of refinement stage
    return state


def assemble_document(state: TranslationState) -> TranslationState:
    """Assembles the final translated document from chunks."""
    NODE_NAME = "assemble_document"
    update_progress(state, NODE_NAME, 98.0)

    # Use 'final_chunks' if final_translation_node ran, otherwise fallback to 'translated_chunks'
    chunks_to_assemble = state.get("final_chunks")
    if chunks_to_assemble is None:
        chunks_to_assemble = state.get("translated_chunks")

    if not chunks_to_assemble:
        log_to_state(state, "No translated chunks available to assemble.", "ERROR", node=NODE_NAME)
        # Ensure error_info is treated as a string
        current_error = state.get("error_info") or ""
        state["error_info"] = current_error + (" | " if current_error else "") + "Cannot assemble document: No translated chunks."
        state["final_document"] = None
        return state

    # Check for None values (failed translations/refinements)
    failed_indices = [i + 1 for i, chunk in enumerate(chunks_to_assemble) if chunk is None]
    if failed_indices:
        log_to_state(state, f"Assembling document with missing translations for chunks: {failed_indices}. Placeholder text might be used or chunks skipped.", "WARNING", node=NODE_NAME)
        # Option 1: Join with placeholders
        # final_content_list = [chunk if chunk is not None else f"[--- TRANSLATION FAILED FOR CHUNK {i+1} ---]" for i, chunk in enumerate(chunks_to_assemble)]
        # Option 2: Filter out None values (might create disjointed text)
        final_content_list = [chunk for chunk in chunks_to_assemble if chunk is not None]
    else:
        final_content_list = chunks_to_assemble

    # Join the chunks back together.
    # The separator used during chunking merge (`\n\n`) is a good candidate.
    separator = "\n\n"
    final_document = separator.join(final_content_list)

    state["final_document"] = final_document
    log_to_state(state, f"Final document assembled successfully ({len(final_document)} characters).", "INFO", node=NODE_NAME)

    # Final updates
    state["metrics"]["end_time"] = time.time()
    start_time = state["metrics"].get("start_time")
    if start_time:
         duration = state["metrics"]["end_time"] - start_time
         log_to_state(state, f"Total job duration: {duration:.2f} seconds.", "INFO", node=NODE_NAME)
         state["metrics"]["duration_seconds"] = duration

    update_progress(state, NODE_NAME, 100.0)
    state["current_step"] = "Completed"
    return state