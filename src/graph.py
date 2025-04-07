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
workflow.add_edge("init_translation", "terminology_unification")
workflow.add_edge("terminology_unification", "chunk_document")
workflow.add_edge("chunk_document", "initial_translation")
workflow.add_edge("initial_translation", "critique_stage") # Updated edge target

# Conditional Edge Function - Decides where to go after critique_stage
def decide_after_critique(state: TranslationState) -> str:
    """Determines next step after critique stage."""
    print(f"--- Condition: Decide after critique ---")
    if state.get("error_info") and "CRITICAL" in state.get("error_info", ""):
        print(f"-> Critical error detected ('{state['error_info']}'), ending.")
        return END

    print("-> Routing to Final Translation")
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
