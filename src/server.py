# This file sets up the Langserve server for the compiled LangGraph application.

from dotenv import load_dotenv
import os
load_dotenv() # Load environment variables from .env file

from .providers import list_available_providers
list_available_providers()  # Print available providers/models at startup

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from langserve import add_routes
# Ensure imports work relative to src directory
try:
    from .graph import app as langgraph_app # Use relative import
    from .state import TranslationState     # Use relative import
except ImportError:
    from .graph import app as langgraph_app # Use relative import
    from .state import TranslationState     # Use relative import

# --- FastAPI App Setup ---
# Add metadata for API docs
app = FastAPI(
    title="LangGraph Translation Server",
    version="1.0",
    description="API Server for the LangGraph-based Document Translation Workflow. Provides endpoints to manage and track translation jobs.",
)

# --- Add Langserve Routes ---
# This exposes the standard LangGraph endpoints under the specified path prefix.
add_routes(
    app,
    langgraph_app, # The compiled LangGraph application instance
    path="/translate_graph", # The base path for the LangGraph API endpoints
    input_type=TranslationState, # Define the expected input schema (for /invoke, /batch etc.)
    output_type=TranslationState, # Define the expected output schema (for /invoke, /batch etc.)
    # Expose 'thread_id' for configuring checkpointing and resuming runs
    # Expose 'recursion_limit' for safety
    config_keys=["configurable", "thread_id", "recursion_limit"],
    enable_feedback_endpoint=True, # Enables the /feedback endpoint (optional)
    enable_public_trace_link_endpoint=True, # Enables /public_trace_link (optional)
    playground_type="default", # Use default playground since we're not using chat messages
)

# --- Optional: Simple HTML Frontend Route ---
# This is very basic, a real frontend would be separate (e.g., React/Vue/Svelte)
# Mount a static directory if you have CSS/JS files
# Example: os.makedirs("static", exist_ok=True); app.mount("/static", StaticFiles(directory="static"), name="static")
# Setup Jinja2 templates if needed
# Example: templates = Jinja2Templates(directory="templates")
# @app.get("/", response_class=HTMLResponse, tags=["Frontend"])
# async def read_root(request: Request):
#     # Basic HTML form to kick off a job (replace with real frontend logic)
#     return templates.TemplateResponse("index.html", {"request": request})


# --- Optional: Add Custom Routes ---
# Example: A custom endpoint to list active/recent jobs (would require storing job info beyond checkpointer)
# @app.get("/jobs", tags=["Jobs"])
# async def list_jobs():
#     # Placeholder: Needs logic to query active threads from checkpointer or separate DB
#     return {"message": "Job listing endpoint not fully implemented."}

@app.get("/health", tags=["Health"])
async def health():
    """Basic health check endpoint."""
    return {"status": "ok"}

@app.get("/providers", tags=["Providers"])
async def get_providers():
    """
    Returns a list of enabled LLM providers and their models.
    """
    return list_available_providers()

# --- Run with Uvicorn (if running this file directly) ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001)) # Allow port override via environment variable
    host = os.getenv("HOST", "127.0.0.1") # Default to localhost for direct run security
    reload_dev = os.getenv("DEV_RELOAD", "false").lower() == "true" # Enable reload via env var

    print(f"Starting Uvicorn server on {host}:{port} (Reload: {reload_dev})")
    # Use reload=True only for development
    uvicorn.run(
        "server:app", # Point to the FastAPI app instance in this file
        host=host,
        port=port,
        reload=reload_dev, # Enable reload only if DEV_RELOAD=true
        reload_dirs=["src"] if reload_dev else None # Watch src directory for changes if reloading
        )

# To run using the Langserve/LangGraph CLI (often simpler):
# Ensure you are in the project root directory
# Activate your conda environment: conda activate langgraph_translator
# Run: langgraph server -m src.server:app --host 0.0.0.0 --port 8001
# The CLI handles finding the 'app' instance (which points to the compiled graph via add_routes).
