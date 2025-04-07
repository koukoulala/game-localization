import streamlit as st
import requests
import time as time_module
import json
import re
import os
from datetime import datetime


def clean_markdown(text):
    # Remove ```markdown blocks but keep ```python, ```bash, etc.
    text = re.sub(r"```markdown\n", "", text)
    text = re.sub(r"\n```", "", text)
    # Replace escaped newlines and tabs with actual characters
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text

def is_rtl(lang):
    return lang.lower() in ["arabic", "hebrew", "farsi", "persian"]

st.set_page_config(page_title="Turjuman Translator", layout="wide")
st.title("Turjuman Translator Frontend")

# --- Sidebar Inputs ---
st.sidebar.header("Configuration")

api_url = st.sidebar.text_input("Translation API URL", "http://localhost:8051")
source_lang = st.sidebar.text_input("Source Language", "english")
target_lang = st.sidebar.text_input("Target Language", "arabic")

# Fetch providers/models from backend
@st.cache_data(show_spinner=False)
def fetch_providers(api_url):
    try:
        resp = requests.get(f"{api_url.rstrip('/')}/providers", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # Build dict: provider -> list of models
        prov_dict = {}
        for item in data:
            prov = item.get("provider")
            models = item.get("models", [])
            if not isinstance(models, list):
                models = []
            prov_dict[prov] = models
        return prov_dict
    except Exception as e:
        st.warning(f"Could not fetch providers: {e}")
        # fallback to hardcoded
        return {
            "openai": ["gpt-4o"],
            "anthropic": ["claude-3-opus"],
            "gemini": ["gemini-2.5-pro"],
            "openrouter": ["google/gemini-2.5-pro-preview-03-25"],
            "mistral": ["mistral-large"],
            "deepseek": ["deepseek-chat"],
            "ollama": ["llama3"],
            "localai": ["gpt-3.5-turbo"]
        }

provider_models = fetch_providers(api_url)

provider = st.sidebar.selectbox(
    "Provider",
    list(provider_models.keys()),
    index=0
)

all_models = provider_models.get(provider, [])

model_filter = st.sidebar.text_input("Filter Models", "")

filtered_models = [m for m in all_models if model_filter.lower() in m.lower()] if model_filter else all_models

model = st.sidebar.selectbox(
    "Model",
    filtered_models,
    index=0 if filtered_models else None
)

uploaded_file = st.file_uploader("Upload Markdown File", type=["md", "markdown"])

if 'job_id' not in st.session_state:
    st.session_state['job_id'] = None
if 'original_content' not in st.session_state:
    st.session_state['original_content'] = ""
if 'translated_content' not in st.session_state:
    st.session_state['translated_content'] = ""
if 'response_json' not in st.session_state:
    st.session_state['response_json'] = {}

def count_words_chars(text):
    words = len(text.split())
    chars = len(text)
    return words, chars

def submit_job(content):
    job_id = f"md-file-{int(time_module.time())}"
    payload = {
        "input": {
            "job_id": job_id,
            "original_content": content,
            "config": {
                "source_lang": source_lang,
                "target_lang": target_lang,
                "provider": provider,
                "model": model
            },
            "current_step": None,
            "progress_percent": 0.0,
            "logs": [],
            "chunks": None,
            "glossary": None,
            "terminology": None,
            "contextualized_glossary": None,
            "basic_translation_chunks": None,
            "translated_chunks": None,
            "parallel_worker_results": None,
            "critiques": None,
            "final_document": None,
            "error_info": None,
            "metrics": {
                "start_time": 0.0,
                "end_time": None
            }
        },
        "config": {
            "configurable": {
                "thread_id": job_id
            }
        }
    }
    try:
        response = requests.post(f"{api_url.rstrip('/')}/translate_graph/invoke", json=payload)
        response.raise_for_status()
        st.session_state['job_id'] = job_id
        st.session_state['response_json'] = response.json()

        # Automatically save JSON response to app directory
        save_dir = os.path.dirname(os.path.abspath(__file__))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(save_dir, f"response_{timestamp}.json")

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(st.session_state['response_json'], f, ensure_ascii=False, indent=2)

        st.session_state['last_response_json_path'] = save_path

        # Automatically save JSON response to app directory
        save_dir = os.path.dirname(os.path.abspath(__file__))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(save_dir, f"response_{timestamp}.json")

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(st.session_state['response_json'], f, ensure_ascii=False, indent=2)

        return True
    except Exception as e:
        st.error(f"Failed to submit job: {e}")
        return False

def poll_job(job_id):
    try:
        resp = requests.get(f"{api_url.rstrip('/')}/translate_graph/get_state", params={"thread_id": job_id})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Failed to poll job status: {e}")
        return None

if uploaded_file:
    content = uploaded_file.read().decode("utf-8")
    st.session_state['original_content'] = content

    btn_col1, btn_col2, btn_col3 = st.columns([1,1,1])
    with btn_col1:
        start_clicked = st.button("Start Translation")

    if start_clicked:
        st.session_state['translation_start_time'] = time_module.time()
        success = submit_job(content)
        if success:
            with st.spinner("Translating..."):
                # Since backend is synchronous, just use the initial response
                state = st.session_state['response_json']

                # Calculate translation duration
                end_time = time_module.time()
                duration_seconds = int(end_time - st.session_state.get('translation_start_time', end_time))
                hours = duration_seconds // 3600
                minutes = (duration_seconds % 3600) // 60
                seconds = duration_seconds % 60
                st.session_state['translation_duration'] = f"{hours:02d}h:{minutes:02d}m:{seconds:02d}s"

                progress = state.get("progress_percent", 0.0)
                st.progress(min(max(progress / 100.0, 0.0), 1.0))
                logs = state.get("logs", [])
                with st.expander("Logs", expanded=False):
                    for log in logs:
                        timestamp = log.get("timestamp", "")
                        level = log.get("level", "")
                        message = log.get("message", "")
                        node = log.get("node", "")
                        st.write(f"[{timestamp}] [{level}] [{node}] {message}")
                final_doc = None
                if isinstance(state, dict):
                    output = state.get("output", {})
                    if isinstance(output, dict):
                        final_doc = output.get("final_document")

                if final_doc:
                    st.session_state['translated_content'] = final_doc
                else:
                    json_path = st.session_state.get('last_response_json_path', 'unknown')
                    st.warning(f"No translated document found in response. Full JSON saved at: {json_path}")

if st.session_state.get('translated_content'):
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        cleaned_translated_for_download = clean_markdown(st.session_state.get('translated_content', ''))
        st.download_button(
            label="Download Translated Text",
            data=cleaned_translated_for_download,
            file_name="translated.md",
            mime="text/markdown",
            key="download_translated"
        )
    with btn_col2:
        st.download_button(
            label="Download Full JSON Response",
            data=json.dumps(st.session_state.get('response_json', {}), ensure_ascii=False, indent=2),
            file_name="response.json",
            mime="application/json",
            key="download_json"
        )


if st.session_state['original_content'] and st.session_state['translated_content']:
    orig_words, orig_chars = count_words_chars(st.session_state['original_content'])
    trans_words, trans_chars = count_words_chars(st.session_state['translated_content'])

    # View selector
    view_mode = st.radio("Select View Mode", ["Full Documents", "Chunk Pairs"])

    # Cleaned full texts
    cleaned_original = clean_markdown(st.session_state['original_content'])
    cleaned_translated = clean_markdown(st.session_state['translated_content'])

    rtl_source = is_rtl(source_lang)
    rtl_target = is_rtl(target_lang)

    if view_mode == "Full Documents":
        col1, col2 = st.columns(2)
        with col1:
            title_col, stats_col = st.columns([2,1])
            with title_col:
                st.subheader("Original Document")
            with stats_col:
                st.markdown(f"**Words:** {orig_words}  |  **Characters:** {orig_chars}")

            st.text_area(
                label="Original Document",
                value=cleaned_original,
                height=400,
                key="orig_full",
                label_visibility="collapsed",
                disabled=True
            )
        with col2:
            title_col, stats_col = st.columns([2,1])
            with title_col:
                st.subheader("Translated Document")
            with stats_col:
                duration_str = st.session_state.get('translation_duration', '00h:00m:00s')
                st.markdown(
                    f"<div style='white-space: nowrap;'><b>Words:</b> {trans_words} &nbsp;|&nbsp; <b>Characters:</b> {trans_chars} &nbsp;|&nbsp; <b>Time:</b> {duration_str}</div>",
                    unsafe_allow_html=True
                )

            # RTL-aware translated text box
            st.markdown(
                f"""
                <div style='height:400px; overflow:auto; border:1px solid #ccc; padding:8px; border-radius:4px;' dir='{"rtl" if rtl_target else "ltr"}'>
                <pre style='white-space: pre-wrap;'>{cleaned_translated}</pre>
                </div>
                """,
                unsafe_allow_html=True
            )

    elif view_mode == "Chunk Pairs":
        # Extract chunks from API response
        output = st.session_state['response_json'].get("output", {})
        orig_chunks = output.get("chunks", [])
        trans_chunks = output.get("translated_chunks", [])

        # Fallback: if translated_chunks empty, try parallel_worker_results
        if not trans_chunks:
            pw_results = output.get("parallel_worker_results", [])
            trans_chunks = [r.get("refined_text", "") for r in pw_results]

        for idx, (orig_chunk, trans_chunk) in enumerate(zip(orig_chunks, trans_chunks)):
            cleaned_orig_chunk = clean_markdown(orig_chunk or "")
            cleaned_trans_chunk = clean_markdown(trans_chunk or "")
            st.markdown(f"### Chunk Pair {idx+1}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f'<div dir="{"rtl" if rtl_source else "ltr"}">{cleaned_orig_chunk}</div>', unsafe_allow_html=True)
            with col2:
                st.markdown(f'<div dir="{"rtl" if rtl_target else "ltr"}">{cleaned_trans_chunk}</div>', unsafe_allow_html=True)

    # Token usage stats

elif uploaded_file:
    st.info("Upload a file and click 'Start Translation' to begin.")
else:
    st.info("Please upload a markdown file to start.")
