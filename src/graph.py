import os
from langgraph.graph import StateGraph, END
# Ensure imports work when run within the 'src' package structure
try:
    from .state import TranslationState
    # Import node functions from their refactored locations
    from .nodes_preprocessing import (
        init_translation,
        terminology_unification,
        chunk_document
    )
    from .nodes_translation import run_parallel_translation
    from .nodes_postprocessing import (
        critique_node,
        final_translation_node,
        assemble_document # Import the assembly function
        # Note: verify_consistency was also moved but is not used in this graph definition
    )
except ImportError: # Fallback if run directly? Less ideal.
     from .state import TranslationState
     # Import node functions from their refactored locations (fallback)
     from .nodes_preprocessing import (
         init_translation,
         terminology_unification,
         chunk_document
     )
     from .nodes_translation import run_parallel_translation
     from .nodes_postprocessing import (
         critique_node,
         final_translation_node,
         assemble_document # Import the assembly function (fallback)
     )


# Use simple in-memory checkpointer for now
memory = None
print("Using in-memory checkpointer (no persistence)")


# Define the workflow
workflow = StateGraph(TranslationState)

# Add nodes using the enhanced functions
# Use unique names matching the function names for clarity
workflow.add_node("init_translation", init_translation)
workflow.add_node("terminology_unification", terminology_unification)
workflow.add_node("chunk_document", chunk_document)
workflow.add_node("initial_translation", run_parallel_translation)
workflow.add_node("critique_stage", critique_node)
workflow.add_node("final_translation", final_translation_node)
workflow.add_node("assemble_document", assemble_document)

# Define Edges and Entry Point
workflow.set_entry_point("init_translation")

# Define conditional edge function that handles both translation mode and glossary checks
def decide_next_step_after_init(state: TranslationState) -> str:
    """Determines next step after initialization based on translation mode and glossary."""
    # First check translation mode
    translation_mode = state.get("config", {}).get("translation_mode", "deep_mode")
    
    if translation_mode == "quick_mode":
        # Quick mode: Skip terminology extraction and go directly to chunking
        return "chunk_document"
    
    # Deep mode: Check if user provided a glossary
    if "contextualized_glossary" in state and state["contextualized_glossary"]:
        # Skip terminology extraction if user provided a glossary
        return "chunk_document"
    
    # Deep mode with no glossary: Do terminology extraction
    return "terminology_unification"

# Add conditional edges after init_translation node
workflow.add_conditional_edges(
    "init_translation",
    decide_next_step_after_init,
    {
        "terminology_unification": "terminology_unification",
        "chunk_document": "chunk_document"
    }
)

workflow.add_edge("terminology_unification", "chunk_document")
workflow.add_edge("chunk_document", "initial_translation")

# Define conditional edge function to decide path after initial translation
def decide_after_initial_translation(state: TranslationState) -> str:
    """Determines next step after initial translation based on translation mode."""
    translation_mode = state.get("config", {}).get("translation_mode", "deep_mode")
    if translation_mode == "quick_mode":
        # Quick mode: Skip critique and final translation, go directly to assembly
        return "assemble_document"
    # Deep mode: Continue with critique stage
    return "critique_stage"

# Add conditional edges after initial_translation
workflow.add_conditional_edges(
    "initial_translation",
    decide_after_initial_translation,
    {
        "critique_stage": "critique_stage",
        "assemble_document": "assemble_document"
    }
)

# Conditional Edge Function - Decides where to go after critique_stage
def decide_after_critique(state: TranslationState) -> str:
    """Determines next step after critique stage."""
    if state.get("error_info") and "CRITICAL" in state.get("error_info", ""):
        print(f"-> Critical error detected ('{state['error_info']}'), ending.")
        return END

    return "final_translation"

# Add Conditional Edges after critique_stage node
workflow.add_conditional_edges(
    "critique_stage", # Updated source node
    decide_after_critique,
    {
        "final_translation": "final_translation",
        END: END
    }
)

# --- Final Translation Path ---
workflow.add_edge("final_translation", "assemble_document") # Route to assembly
workflow.add_edge("assemble_document", END) # End after assembly

# Compile the basic workflow
compiled_graph = workflow.compile()
print("Graph compiled successfully")


# Make the app available for serving via Langserve CLI or direct import
# This variable 'app' will be imported by server.py or used like:
# langgraph server -m src.graph:app
app = compiled_graph
