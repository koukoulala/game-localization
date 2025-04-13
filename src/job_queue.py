import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from .database import (
    get_next_pending_job, update_job, get_job,
    add_log, get_logs, add_chunk, update_chunk, get_chunks,
    add_glossary_entry, get_glossary, add_critique, get_critiques,
    add_metrics, get_metrics, create_job, list_jobs
)

logger = logging.getLogger("turjuman.job_queue")

class JobQueue:
    def __init__(self):
        self.processing = False
        self.current_job_id = None
    
    async def enqueue_job(self, input_data: Dict[str, Any]) -> str:
        """Add a new job to the queue."""
        job_id = await create_job(input_data)
        logger.info(f"Job {job_id} added to queue")
        return job_id
    
    async def get_next_pending_job(self) -> Optional[Dict[str, Any]]:
        """Get the next pending job from the queue."""
        return await get_next_pending_job()
    
    async def update_job_status(self, job_id: str, status: str, progress: float = None,
                               final_document: str = None, error_info: str = None,
                               current_step: str = None):
        """Update job status and related fields."""
        updates = {"status": status}
        
        # Set started_at timestamp when job status changes to processing
        if status == "processing":
            # Check if this is the first time the job is being processed
            job = await get_job(job_id)
            if job and job.get("status") != "processing" and not job.get("started_at"):
                updates["started_at"] = datetime.now().isoformat()
        
        if progress is not None:
            updates["progress_percent"] = progress
        
        if final_document is not None:
            updates["final_document"] = final_document
        
        if error_info is not None:
            updates["error_info"] = error_info
        
        if current_step is not None:
            updates["current_step"] = current_step
        
        await update_job(job_id, updates)
        logger.debug(f"Updated job {job_id} status to {status}")
    
    async def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """Get comprehensive job details including chunks, logs, etc."""
        job = await get_job(job_id)
        
        if not job:
            return {"error": "Job not found"}
        
        # Get related data
        chunks = await get_chunks(job_id)
        logs = await get_logs(job_id, limit=100)
        metrics = await get_metrics(job_id)
        glossary = await get_glossary(job_id)
        critiques = await get_critiques(job_id)
        
        # Combine into a comprehensive response
        result = dict(job)
        result["chunks"] = chunks
        result["logs"] = logs
        result["metrics"] = metrics
        result["glossary"] = glossary
        result["critiques"] = critiques
        
        # Parse config_json if present
        if result.get("config_json"):
            try:
                result["config"] = json.loads(result["config_json"])
                del result["config_json"]  # Remove the raw JSON
            except:
                result["config"] = {}
        
        return result
    
    async def list_jobs(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List all jobs with pagination."""
        return await list_jobs(limit, offset)