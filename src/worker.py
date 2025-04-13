import asyncio
import logging
import time
import json
import uuid
from typing import Dict, List, Any, Optional
import copy
import threading
import queue

from .job_queue import JobQueue
from . import graph
from .state import TranslationState
from langchain_core.callbacks import BaseCallbackHandler
from .database import (
    add_log, add_chunk, update_chunk, get_chunks,
    add_glossary_entry, add_critique, add_metrics, get_job
)

logger = logging.getLogger("turjuman.worker")

class TranslationWorker:
    def __init__(self):
        self.job_queue = JobQueue()
        self.running = False
        self.current_job = None
    
    async def start(self):
        """Start the worker process."""
        self.running = True
        logger.info("Translation worker started")
        
        while self.running:
            try:
                # Get the next pending job
                job = await self.job_queue.get_next_pending_job()
                
                if job:
                    # Process the job
                    logger.info(f"Processing job {job['job_id']}")
                    self.current_job = job
                    await self.job_queue.update_job_status(
                        job['job_id'], 
                        "processing",
                        current_step="initializing"
                    )
                    
                    try:
                        # Prepare input state
                        config = json.loads(job['config_json']) if job['config_json'] else {}
                        input_state = {
                            "job_id": job['job_id'],
                            "original_content": job['original_content'],
                            "config": config,
                            "current_step": None,
                            "progress_percent": 0.0,
                            "logs": []
                        }
                        
                        # Process with state updates
                        await self.process_job(job['job_id'], input_state)
                        
                    except Exception as e:
                        logger.exception(f"Error processing job {job['job_id']}")
                        await self.job_queue.update_job_status(
                            job['job_id'], 
                            "failed", 
                            error_info=f"Worker error: {str(e)}"
                        )
                    
                    self.current_job = None
                else:
                    # No pending jobs, wait before checking again
                    await asyncio.sleep(5)
            
            except Exception as e:
                logger.exception("Error in worker loop")
                await asyncio.sleep(10)  # Wait longer on error
    
    async def process_job(self, job_id: str, input_state: Dict[str, Any]):
        """Process a translation job and update the database."""
        # Create a state handler to capture updates
        state_queue = queue.Queue()
        
        # Run the translation graph in a separate thread
        def run_workflow():
            try:
                # Create a callback to capture state updates
                class ProgressHandler(BaseCallbackHandler):
                    def on_chain_end(self, outputs, **kwargs):
                        # outputs is the current state after node execution
                        state_queue.put(copy.deepcopy(outputs))
                
                # Run the graph with callbacks
                final_state = graph.app.invoke(
                    input_state,
                    config={"callbacks": [ProgressHandler()]}
                )
                
                # Put the final state in the queue
                state_queue.put(copy.deepcopy(final_state))
                
            except Exception as e:
                logger.exception(f"Error in workflow thread for job {job_id}")
                state_queue.put({"error": str(e)})
        
        # Start the workflow in a thread
        thread = threading.Thread(target=run_workflow)
        thread.start()
        
        # Process state updates as they come in
        last_progress = 0
        last_step = None
        
        while thread.is_alive() or not state_queue.empty():
            # Process any state updates
            while not state_queue.empty():
                try:
                    state = state_queue.get_nowait()
                    
                    # Ensure state is a dictionary
                    if isinstance(state, str):
                        logger.warning(f"Received string state: {state}")
                        continue
                    
                    # Check for error
                    if "error" in state:
                        await self.job_queue.update_job_status(
                            job_id,
                            "failed",
                            error_info=state["error"]
                        )
                        continue
                    
                    # Update job status
                    progress = state.get("progress_percent", last_progress)
                    step = state.get("current_step", last_step)
                    
                    if progress != last_progress or step != last_step:
                        await self.job_queue.update_job_status(
                            job_id,
                            "processing",
                            progress=progress,
                            current_step=step
                        )
                        last_progress = progress
                        last_step = step
                    
                    # Store logs
                    if state.get("logs"):
                        for log in state.get("logs", []):
                            await add_log(
                                job_id,
                                log.get("level", "INFO"),
                                log.get("message", ""),
                                log.get("node")
                            )
                    
                    # Store chunks if available
                    if state.get("chunks"):
                        chunks = state.get("chunks", [])
                        translated_chunks = state.get("translated_chunks", [None] * len(chunks))
                        
                        for i, (orig, trans) in enumerate(zip(chunks, translated_chunks)):
                            # Check if chunk already exists
                            existing_chunks = await get_chunks(job_id)
                            chunk_exists = any(c["chunk_index"] == i for c in existing_chunks)
                            
                            if chunk_exists:
                                # Update existing chunk
                                for chunk in existing_chunks:
                                    if chunk["chunk_index"] == i:
                                        updates = {}
                                        if trans:
                                            updates["translated_chunk"] = trans
                                        
                                        if updates:
                                            await update_chunk(chunk["chunk_id"], updates)
                            else:
                                # Add new chunk
                                await add_chunk(job_id, i, orig)
                    
                    # Store glossary if available
                    if state.get("contextualized_glossary"):
                        for entry in state.get("contextualized_glossary", []):
                            source_term = entry.get("sourceTerm", "")
                            target_terms = entry.get("proposedTranslations", {})
                            
                            for lang, term in target_terms.items():
                                await add_glossary_entry(
                                    job_id,
                                    source_term,
                                    term,
                                    context=entry.get("context"),
                                    metadata={"language": lang}
                                )
                    
                    # Store critiques if available
                    if state.get("critiques"):
                        for i, critique in enumerate(state.get("critiques", [])):
                            await add_critique(
                                job_id,
                                i,
                                critique.get("text", ""),
                                category=critique.get("category"),
                                score=critique.get("score"),
                                metadata=critique
                            )
                    
                    # Check for final document
                    if state.get("final_document"):
                        await self.job_queue.update_job_status(
                            job_id,
                            "completed",
                            progress=100.0,
                            final_document=state.get("final_document")
                        )
                    
                    # Store metrics if available
                    if state.get("metrics"):
                        metrics = state.get("metrics", {})
                        
                        # Add word counts
                        metrics["word_count_source"] = len(input_state.get("original_content", "").split())
                        if state.get("final_document"):
                            metrics["word_count_target"] = len(state.get("final_document", "").split())
                        
                        # Add total chunks
                        if state.get("chunks"):
                            metrics["total_chunks"] = len(state.get("chunks", []))
                        
                        await add_metrics(job_id, metrics)
                    
                except queue.Empty:
                    break
                except Exception as e:
                    logger.exception(f"Error processing state update for job {job_id}")
            
            # Wait a bit before checking again
            if thread.is_alive():
                await asyncio.sleep(0.5)
        
        # Thread is done, check if job was completed
        job = await get_job(job_id)
        
        if job and job["status"] not in ["completed", "failed"]:
            # Job wasn't marked as completed or failed, mark as failed
            await self.job_queue.update_job_status(
                job_id,
                "failed",
                error_info="Job processing did not complete properly"
            )
    
    async def stop(self):
        """Stop the worker process."""
        self.running = False
        logger.info("Translation worker stopping")