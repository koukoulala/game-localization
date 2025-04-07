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
    termId: str
    sourceTerm: str
    context: Optional[str]
    # Allow multiple proposed, but keep 'default' convention
    proposedTranslations: Dict[str, str]
    status: Literal["pending", "approved", "conflict"]
    # Added field for review feedback
    approvedTranslation: Optional[str]
    # Optional variants field
    variants: Optional[List[str]]

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
    glossary: Optional[List[Dict[str, Any]]]  # Initial extracted terms (before contextualization)
    terminology: Optional[List[TerminologyEntry]]  # Deprecated - will be removed after migration
    contextualized_glossary: Optional[List[Dict[str, Any]]]  # Enhanced terms with context
    basic_translation_chunks: Optional[List[Optional[str]]]  # Initial translation before critique
    translated_chunks: Optional[List[Optional[str]]]  # Final translation chunks (deprecated - will be removed)
    parallel_worker_results: Optional[List[Dict[str, Any]]]  # Intermediate results
    critiques: Optional[List[Dict[str, Any]]]  # Structured feedback from critique stage (plural)

    # Human Review
    human_review_required: bool
    human_feedback_data: Optional[Dict[str, str]] # termId -> approved_translation

    # Output & Errors
    final_document: Optional[str]
    error_info: Optional[str] # Store critical error messages

    # Metrics
    metrics: Metrics
