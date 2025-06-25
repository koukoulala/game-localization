#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
# Treat unset variables as an error when substituting.
# Pipestatus of the last command with a non-zero exit code is returned.
set -euo pipefail

# --- Default Configuration ---
DEFAULT_SOURCE_LANG="english"
DEFAULT_TARGET_LANG="simplified_chinese"
DEFAULT_PROVIDER="openai" # Default provider
DEFAULT_API_URL="http://localhost:8051" # Default API server URL
DEFAULT_TARGET_ACCENT="professional" # Default accent

# Default models per provider (matching backend defaults)
declare -A DEFAULT_MODELS=(
  ["openai"]="gpt-4o-mini"
  ["anthropic"]="claude-3-haiku-20240307"
  ["gemini"]="gemini-2.5-flash"
  ["openrouter"]="google/gemini-2.5-flash"
  ["mistral"]="mistral-large-2402"
  ["deepseek"]="deepseek-chat"
  ["ollama"]="llama3"
  ["localai"]="gpt-3.5-turbo"
)

# --- Function Definitions ---

CYAN='\033[1;36m'
YELLOW='\033[1;33m'
GREEN='\033[1;32m'
MAGENTA='\033[1;35m'
RESET='\033[0m'
BOLD='\033[1m'

# Display usage information
function show_usage {

  echo -e "${CYAN}${BOLD}Usage:${RESET} $(basename "$0") -i <input_file> [OPTIONS]"
  echo -e ""
  echo -e "${YELLOW}Sends a in-game file to the translation server for processing.${RESET}"
  echo -e ""
  echo -e "${CYAN}${BOLD}Required:${RESET}"
  echo -e "  -i, --input FILE       Path to the input file to translate"
  echo -e ""
  echo -e "${CYAN}${BOLD}Optional:${RESET}"
  echo -e "  -o, --output FILE      Path to save the JSON response (default: ./<input_name_no_ext>_\${JOB_ID}.json)"
  echo -e "  -s, --source LANG      Source language (default: ${DEFAULT_SOURCE_LANG})"
  echo -e "  -t, --target LANG      Target language (default: ${DEFAULT_TARGET_LANG})"
  echo -e "  -p, --provider NAME    LLM provider (default: ${DEFAULT_PROVIDER})"
  echo -e "  -m, --model NAME       LLM model (default depends on provider)"
  echo -e "  -u, --url URL          API server base URL (default: ${DEFAULT_API_URL})"
  echo -e "  -a, --accent ACCENT    Target language style/accent (default: ${DEFAULT_TARGET_ACCENT})"
  echo -e "  -l, --list-models      List all available providers and models from backend"
  echo -e "  -h, --help             Show this help message and exit"
  echo -e ""
  echo -e "${CYAN}${BOLD}Examples:${RESET}"
  echo -e "  $(basename "$0") -i README.md -s english -t french -p openrouter"
  echo -e "  $(basename "$0") --input my_doc.md --output results/my_doc_response.json --provider ollama"
  echo -e "  $(basename "$0") -l"
  echo -e ""
  echo -e "${GREEN}${BOLD}Default Models:${RESET}"
  for prov in "${!DEFAULT_MODELS[@]}"; do
    printf "  %-12s -> %s\n" "$prov" "${DEFAULT_MODELS[$prov]}"
  done
  echo -e ""
  exit 1
}

# Check for required commands
function check_command {
  if ! command -v "$1" &> /dev/null; then
    echo "Error: Required command '$1' not found. Please install it." >&2
    exit 1
  fi
}

# --- Command Checks ---
check_command jq
check_command curl
check_command dirname
check_command basename
check_command date
check_command head
check_command tr
check_command sed

# --- Argument Parsing ---
SOURCE_LANG="${DEFAULT_SOURCE_LANG}"
TARGET_LANG="${DEFAULT_TARGET_LANG}"
PROVIDER="${DEFAULT_PROVIDER}"
MODEL=""
API_URL="${DEFAULT_API_URL}"
INPUT_FILE_PATH=""
OUTPUT_FILE_PATH="" # Optional output path
TARGET_ACCENT="${DEFAULT_TARGET_ACCENT}" # Initialize accent variable
LIST_MODELS_ONLY=0

# Use getopt for robust option parsing
TEMP=$(getopt -o hi:o:s:t:p:m:u:a:l --long help,input:,output:,source:,target:,provider:,model:,url:,accent:,list-models -n "$(basename "$0")" -- "$@")
if [ $? != 0 ] ; then echo "Terminating..." >&2 ; exit 1 ; fi

# Note the quotes around "$TEMP": they are essential!
eval set -- "$TEMP"
unset TEMP

while true; do
  case "$1" in
    '-i'|'--input') INPUT_FILE_PATH="$2"; shift 2 ;;
    '-o'|'--output') OUTPUT_FILE_PATH="$2"; shift 2 ;;
    '-s'|'--source') SOURCE_LANG="$2"; shift 2 ;;
    '-t'|'--target') TARGET_LANG="$2"; shift 2 ;;
    '-p'|'--provider') PROVIDER="$2"; shift 2 ;;
    '-m'|'--model') MODEL="$2"; shift 2 ;;
    '-u'|'--url') API_URL="$2"; shift 2 ;;
    '-a'|'--accent') TARGET_ACCENT="$2"; shift 2 ;;
    '-l'|'--list-models') LIST_MODELS_ONLY=1; shift ;;
    '-h'|'--help') show_usage ;;
    '--') shift; break ;;
    *) echo "Internal error!" ; exit 1 ;;
  esac
done

# Check if any positional arguments remain (should be none)
if [ $# -ne 0 ]; then
  echo "Error: Unexpected positional arguments: $@" >&2
  show_usage
fi

# --- List Models Mode ---
if [ "$LIST_MODELS_ONLY" -eq 1 ]; then
  echo "Fetching available providers and models from ${API_URL}/providers ..."
  PROVIDERS_JSON=$(curl -s "${API_URL%/}/providers")
  if [ -z "$PROVIDERS_JSON" ]; then
    echo "Error: Could not fetch providers list." >&2
    exit 1
  fi
  echo "Available Providers and Models:"
  echo "$PROVIDERS_JSON" | jq -r '.[] | "\(.provider):\n  \(.models[])"'
  exit 0
fi

# --- Input Validation ---
if [ -z "$INPUT_FILE_PATH" ]; then
  echo "Error: Input file path is required (-i or --input)." >&2
  show_usage
fi

if [ ! -f "$INPUT_FILE_PATH" ]; then
  echo "Error: Input file not found: $INPUT_FILE_PATH" >&2
  exit 1
fi

# --- Set default model if missing ---
if [ -z "$MODEL" ]; then
  MODEL="${DEFAULT_MODELS[$PROVIDER]:-}"
  if [ -z "$MODEL" ]; then
    echo "Error: No default model found for provider '$PROVIDER'. Please specify --model." >&2
    exit 1
  fi
fi

echo -e "${CYAN}🔗 Using provider:${RESET} ${BOLD}$PROVIDER${RESET}"
echo -e "${CYAN}🤖 Using model:   ${RESET} ${BOLD}$MODEL${RESET}"

# --- Job Execution ---

# Generate a unique job ID (config key for LangServe)
JOB_ID="md-file-$(date +%s)"
echo -e "${GREEN}🆔 Generated Job ID:${RESET} ${BOLD}$JOB_ID${RESET}"
echo -e "${YELLOW}🔎 DEBUG: Full JOB_ID for API:${RESET} $JOB_ID"

# Determine the output file path
if [ -z "$OUTPUT_FILE_PATH" ]; then
  INPUT_BASENAME=$(basename "$INPUT_FILE_PATH")
  INPUT_NAME_NO_EXT="${INPUT_BASENAME%.*}"
  RESPONSE_FILE="./${INPUT_NAME_NO_EXT}_${JOB_ID}.json"
else
  RESPONSE_FILE="$OUTPUT_FILE_PATH"
  OUTPUT_DIR=$(dirname "$RESPONSE_FILE")
  if [[ "$OUTPUT_DIR" != "." ]] && [ ! -d "$OUTPUT_DIR" ]; then
    echo -e "${YELLOW}📁 Creating output directory:${RESET} $OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
  fi
fi
echo -e "${CYAN}💾 Response will be saved to:${RESET} ${BOLD}$RESPONSE_FILE${RESET}"


# Construct the FULL JSON payload using jq, mirroring the original script's structure
echo -e "${MAGENTA}🛠️  Preparing request payload...${RESET}"
JSON_PAYLOAD=$(jq -n \
  --arg job_id "$JOB_ID" \
  --arg src_lang "$SOURCE_LANG" \
  --arg tgt_lang "$TARGET_LANG" \
  --arg provider "$PROVIDER" \
  --arg model "$MODEL" \
  --arg accent "$TARGET_ACCENT" \
'{
  "input": {
    "job_id": $job_id,
    "original_content": '"$(jq -Rs . "$INPUT_FILE_PATH")"', # Embed file content as JSON string
    "config": {
      "source_lang": $src_lang,
      "target_lang": $tgt_lang,
      "provider": $provider,
      "model": $model,
      "target_language_accent": $accent
    },
    "current_step": null,
    "progress_percent": 0.0,
    "logs": [],
    "chunks": null,
    "contextualized_glossary": null,
    "translated_chunks": null,
    "parallel_worker_results": null,
    "critiques": null,
    "final_document": null,
    "error_info": null,
    "metrics": {
      "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
      "start_time": 0.0,
      "end_time": null
    }
  },
  "config": {
    "configurable": {
       "thread_id": $job_id
     }
  }
}')

# Send the request using curl, piping the JSON payload
INVOKE_URL="${API_URL%/}/translate_graph/invoke" # Ensure no double slash

echo -e "${GREEN}🚀 Sending translation request to:${RESET} ${BOLD}$INVOKE_URL${RESET}"
echo -e "${YELLOW}(Input: ${INPUT_FILE_PATH}, Provider: ${PROVIDER}, ${SOURCE_LANG} -> ${TARGET_LANG})${RESET}"

STATE_URL="${API_URL%/}/translate_graph/get_state"
echo -e "${CYAN}🔄 To check progress, run:${RESET}"
echo -e "${BOLD}curl -X GET \"${STATE_URL}?thread_id=${JOB_ID}\"${RESET}"
  
# Get HTTP status code from curl
HTTP_STATUS=$(echo "$JSON_PAYLOAD" | curl -s -w "%{http_code}" -X POST "$INVOKE_URL" \
  -H "Content-Type: application/json" \
  -o "$RESPONSE_FILE" \
  --data-binary @-)

# --- Output and Cleanup ---
echo ""
if [ "$HTTP_STATUS" -ge 200 ] && [ "$HTTP_STATUS" -lt 300 ]; then
  echo "✅ Translation job successfully submitted."
  echo "   Job ID (thread_id): $JOB_ID"
  echo "   Provider specified: $PROVIDER"
  echo "   Response saved to: $RESPONSE_FILE (contains initial state or result if synchronous)"
  echo ""
else
  echo "❌ Error: Request failed with HTTP status $HTTP_STATUS." >&2
  echo "   Check the response file '$RESPONSE_FILE' for details:" >&2
  cat "$RESPONSE_FILE" >&2 # Print error response to stderr
  exit 1
fi

exit 0
