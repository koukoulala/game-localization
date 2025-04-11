import time
from typing import List, Dict, Optional, Any, Literal
from typing_extensions import TypedDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

class LogEntry(TypedDict):
    timestamp: str
    level: LogLevel
    message: str
    node: Optional[str] # Track which node generated the log


class Metrics(TypedDict):
    start_time: float
    end_time: Optional[float]
    # Optional stats per chunk if needed later
    # chunk_stats: List[Dict[str, Any]]

class TerminologyEntry(TypedDict):
    sourceTerm: str
    proposedTranslations: Dict[str, str]

# Define the state structure
class TranslationState(TypedDict):
    job_id: str
    original_content: str
    config: Dict[str, Any] # source_lang, target_lang, model_info, api_key_source etc.
    current_step: Optional[str] # Name of the current node/phase
    progress_percent: Optional[float] # Estimated progress (0.0 to 100.0)
    logs: List[LogEntry]

    # Core data flow
    chunks: Optional[List[str]]
    contextualized_glossary: Optional[List[Dict[str, Any]]]  # Enhanced terms with context
    translated_chunks: Optional[List[Optional[str]]]  # Final translation chunks (deprecated - will be removed)
    parallel_worker_results: Optional[List[Dict[str, Any]]]  # Intermediate results
    critiques: Optional[List[Dict[str, Any]]]  # Structured feedback from critique stage (plural)

    # Output & Errors
    final_document: Optional[str]
    error_info: Optional[str] # Store critical error messages

    # Metrics
    metrics: Metrics
