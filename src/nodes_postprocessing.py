import re
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

    # Get translatable chunks and their translations
    original_chunks = state.get("chunks")
    translated_chunks = state.get("translated_chunks")
    
    # Get chunks with metadata for reference
    chunks_with_metadata = state.get("chunks_with_metadata", [])

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
            "job_id": state.get("job_id"),
            "contextualized_glossary": state.get("contextualized_glossary", []) # Add glossary here
        }
        # Get the original index from chunks_with_metadata if available
        original_index = -1
        if chunks_with_metadata:
            for chunk_meta in chunks_with_metadata:
                if chunk_meta["toTranslate"] and chunk_meta["chunkText"] == original_chunks[i]:
                    original_index = chunk_meta["index"]
                    break
        
        worker_inputs.append({
            "state": state_essentials,
            "original_chunk": original_chunks[i],
            "translated_chunk": translated_chunks[i],
            "index": i, # Use worker index
            "original_index": original_index, # Store original index from metadata
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
                    log_to_state(state, f"(Worker Log Chunk {index+1}): {log_entry.get('message', '')}", log_entry.get('level', 'DEBUG'), node=f"{NODE_NAME}/{result.get('node_name', 'critique_worker')}", log_type="LOG_CHUNK_PROCESSING")


                if "error" in result:
                    error_message = f"Critique worker error (Chunk {index + 1}): {result['error']}"
                    log_to_state(state, error_message, "ERROR", node=NODE_NAME)
                    state["critiques"][index] = {"error": error_message} # Store error dict instead of None
                elif "critique" in result:
                    state["critiques"][index] = result["critique"] # Store the parsed critique
                    log_to_state(state, f"Successfully critiqued chunk {index + 1}.", "DEBUG", node=NODE_NAME, log_type="LOG_CHUNK_PROCESSING")
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

def final_translation_node(state: TranslationState) -> TranslationState:
    """
    Performs a final refinement pass on translated chunks, potentially using critiques.
    This acts like `run_parallel_translation` but uses the `_finalize_chunk_worker`.
    """
    NODE_NAME = "final_translation_node"
    update_progress(state, NODE_NAME, 80.0) # Start after critique

    # Get translatable chunks and their translations
    original_chunks = state.get("chunks")
    translated_chunks = state.get("translated_chunks")
    critiques = state.get("critiques")
    
    # Get chunks with metadata for reference
    chunks_with_metadata = state.get("chunks_with_metadata", [])

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
            "job_id": state.get("job_id"),
            "contextualized_glossary": state.get("contextualized_glossary", []) # Add glossary here
        }
        # Get the original index from chunks_with_metadata if available
        original_index = -1
        if chunks_with_metadata:
            for chunk_meta in chunks_with_metadata:
                if chunk_meta["toTranslate"] and chunk_meta["chunkText"] == original_chunks[i]:
                    original_index = chunk_meta["index"]
                    break
        
        worker_inputs.append({
            "state": state_essentials,
            "original_chunk": original_chunks[i],
            "translated_chunk": translated_chunks[i],
            "critique": critiques[i], # Pass the critique data
            "index": i,
            "original_index": original_index,
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
                    # Extract additional info from result for logging
                    prompt_chars = result.get("prompt_char_count", "N/A")
                    term_count = result.get("filtered_term_count", "N/A")
                    log_to_state(state, f"Successfully refined chunk {index + 1} (Terms: {term_count}, Prompt Chars: {prompt_chars}).", "DEBUG", node=NODE_NAME, log_type="LOG_CHUNK_PROCESSING")
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

    # Get all chunks with metadata
    chunks_with_metadata = state.get("chunks_with_metadata", [])
    
    # Get translated chunks
    translated_chunks = state.get("final_chunks")
    if translated_chunks is None:
        translated_chunks = state.get("translated_chunks")
    
    # Get non-translatable chunks
    non_translatable_chunks = state.get("non_translatable_chunks", [])
    
    if not chunks_with_metadata:
        log_to_state(state, "No chunks metadata available for assembly.", "ERROR", node=NODE_NAME)
        current_error = state.get("error_info") or ""
        state["error_info"] = current_error + (" | " if current_error else "") + "Cannot assemble document: Missing chunk metadata."
        state["final_document"] = None
        return state
    
    if not translated_chunks and not non_translatable_chunks:
        log_to_state(state, "No chunks available to assemble.", "ERROR", node=NODE_NAME)
        current_error = state.get("error_info") or ""
        state["error_info"] = current_error + (" | " if current_error else "") + "Cannot assemble document: No chunks available."
        state["final_document"] = None
        return state
    
    # Prepare all chunks for assembly
    all_chunks = []
    translatable_index = 0
    
    for chunk in chunks_with_metadata:
        if chunk["toTranslate"]:
            # Use translated content if available
            if translatable_index < len(translated_chunks) and translated_chunks[translatable_index] is not None:
                chunk_content = translated_chunks[translatable_index]
            else:
                # Fallback to original content if translation failed
                chunk_content = chunk["chunkText"]
                log_to_state(state,
                    f"Warning: Using original content for translatable chunk {chunk['index']} due to missing translation",
                    "WARNING", node=NODE_NAME)
            translatable_index += 1
        else:
            # Use original content for non-translatable chunks
            chunk_content = chunk["chunkText"]
        
        all_chunks.append({"index": chunk["index"], "content": chunk_content})
    
    # Sort by original index and join
    sorted_chunks = sorted(all_chunks, key=lambda x: x["index"])
    
    # Determine the separator based on the original file type
    original_file_type = state.get("original_file_type")
    log_to_state(state, f"File type is:----> {original_file_type}", "INFO", node=NODE_NAME)
    

    if original_file_type == ".srt":
        # SRT files need special handling
        separator = "\n"
        log_to_state(state, "Using newline separator for SRT file assembly.", "INFO", node=NODE_NAME)
    elif original_file_type == ".md":
        separator = "\n\n"
        log_to_state(state, "Using paragraph separator ('\\n\\n') for Markdown file assembly.", "INFO", node=NODE_NAME)
    else: # Default for .txt and others
        separator = "\n"
        log_to_state(state, f"Using newline separator ('\\n') for {original_file_type} file assembly.", "INFO", node=NODE_NAME)
        
    final_document = separator.join([chunk["content"] for chunk in sorted_chunks])
    
    # Post-processing for specific file types
    if original_file_type == ".srt":
        final_document = clean_srt_file(final_document)
        log_to_state(state, "Applied SRT-specific post-processing.", "INFO", node=NODE_NAME)

    state["final_document"] = final_document
    log_to_state(state, f"Final document assembled successfully ({len(final_document)} characters).", "INFO", node=NODE_NAME)

    # Final updates
    log_to_state(state, f"Metrics before setting end_time: {state.get('metrics')}", "DEBUG", node=NODE_NAME) # Keep this log unconditional for now
    if isinstance(state.get("metrics"), dict):
        state["metrics"]["end_time"] = time.time()
    else:
        log_to_state(state, f"Metrics field is not a dict or is None: {type(state.get('metrics'))}. Skipping end_time.", "ERROR", node=NODE_NAME)
        # Optionally initialize metrics here if it should always exist
        if state.get("metrics") is None:
             state["metrics"] = {"start_time": None, "end_time": time.time()} # Initialize with current time
    start_time = state["metrics"].get("start_time")
    if start_time:
         duration = state["metrics"]["end_time"] - start_time
         log_to_state(state, f"Total job duration: {duration:.2f} seconds.", "INFO", node=NODE_NAME)
         state["metrics"]["duration_seconds"] = duration

    update_progress(state, NODE_NAME, 100.0)
    state["current_step"] = "Completed"
    return state

def clean_srt_file(srt_content: str) -> str:
    """
    Clean up SRT file content after translation to fix common issues.
    
    Args:
        srt_content: The SRT file content to clean
        
    Returns:
        Cleaned SRT file content
    """

    cleaned_content = re.sub(r'^\s*```.*?\s*$\n?', '', srt_content, flags=re.MULTILINE)

    return cleaned_content
