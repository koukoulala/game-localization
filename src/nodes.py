import os
import json
import uuid
import time
import yaml
from pathlib import Path
import concurrent.futures
import requests
from typing import Dict, Any, List, Optional
from langchain_core.exceptions import OutputParserException

# Custom exceptions and utils moved to src/exceptions.py and src/node_utils.py
# Node functions moved to src/nodes_preprocessing.py, src/nodes_translation.py, src/nodes_postprocessing.py
# Worker functions moved to src/node_workers.py

# Imports potentially needed by the graph definition or other parts (review if necessary)
# These were originally present and might be needed depending on how src/graph.py imports things.
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
try:
    from .state import TranslationState, TerminologyEntry
    from .providers import get_llm_client
    from .chunking import create_semantic_chunks
    from .utils import log_to_state, update_progress, estimate_prompt_tokens
    # Note: The actual node functions are now imported directly in src/graph.py from their new locations.
except ImportError: # Fallback for running script directly? (Less ideal)
     # This fallback might need adjustment depending on how the project is run
    from .state import TranslationState, TerminologyEntry
    from providers import get_llm_client
    from chunking import create_semantic_chunks
    from utils import log_to_state, update_progress, estimate_prompt_tokens

# --- This file is now significantly smaller after refactoring. ---
# --- Node definitions are located in: ---
# --- src/exceptions.py ---
# --- src/node_utils.py ---
# --- src/node_workers.py ---
# --- src/nodes_preprocessing.py ---
# --- src/nodes_translation.py ---
# --- src/nodes_postprocessing.py ---
