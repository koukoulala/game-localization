# Turjuman API Reference

You can interact with the Turjuman backend directly via its API endpoint, built using LangServe. This is useful for building custom clients or integrating Turjuman into other workflows.

---

## Endpoint

`POST /translate_graph/invoke`

---

## Request Body (JSON)

The request body requires two main keys: `input` and `config`.

### 1. `input` (TranslationState)

- `job_id` (string, **required**): Unique identifier (e.g., `"my-book-translation-123"`). Also used as `thread_id`.
- `original_content` (string, **required**): The full text content to translate.
- `config` (object, **required**):
  - `source_lang` (string, **required**): Source language (e.g., `"english"`).
  - `target_lang` (string, **required**): Target language (e.g., `"arabic"`).
  - `provider` (string, **required**): LLM provider (e.g., `"openai"`, `"ollama"`).
  - `model` (string, **required**): Specific model name (e.g., `"gpt-4o"`, `"llama3"`).
  - `target_language_accent` (string, optional, default: `"professional"`): Specifies the desired accent or dialect for the target language (e.g., `"Egyptian Arabic"`, `"British English"`, `"Standard Arabic"`). Influences translation style and critique.
  - *(Optional)* Other provider/model specific configs.
- `current_step` (string | null, optional)
- `progress_percent` (float | null, optional)
- `logs` (list, optional)
- `chunks` (list[string] | null, optional)
- `contextualized_glossary` (list[dict] | null, optional)
- `translated_chunks` (list[string | null] | null, optional)
- `parallel_worker_results` (list[dict] | null, optional)
- `critiques` (list[dict | null] | null, optional)
- `final_document` (string | null, optional)
- `error_info` (string | null, optional)
- `metrics` (object, optional)

### 2. `config` (LangServe config)

- `configurable` (object, **required**)
  - `thread_id` (string, **required**): **Must be identical to `input.job_id`**.

## Response

The API call to `/invoke` is synchronous in this implementation; it will return the final state of the translation graph once the entire process completes. The translated document will be in the `output.final_document` field of the JSON response saved to the output file. You can also use the `/translate_graph/get_state` endpoint with the `thread_id` to retrieve the final state again later.
