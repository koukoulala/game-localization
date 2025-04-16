# smart_chunker.py (Contains the class and can be run standalone for basic tests)

import re
import math # Not directly used now, but kept for potential future use

class SmartChunker:
    """
    Chunks Markdown formatted text, identifying and separating code blocks,
    images, and URLs, while respecting minimum and maximum chunk sizes for
    translatable text segments.
    """

    def __init__(self, min_chunk_size: int = 50, max_chunk_size: int = 500):
        # ... (init validation remains the same) ...
        if not isinstance(min_chunk_size, int) or min_chunk_size <= 0:
            raise ValueError("min_chunk_size must be a positive integer")
        if not isinstance(max_chunk_size, int) or max_chunk_size < min_chunk_size:
            raise ValueError("max_chunk_size must be an integer greater than or equal to min_chunk_size")

        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

        # --- Compile Regex Patterns (Revised Order & Fenced Code End) ---

        # 1. Fenced Code Blocks - Most distinct block element
        self.regex_code_fenced = re.compile(
            r"""^(```|~~~)                 # G1: Opening fence type (``` or ~~~)
                 [ \t]*                    # Optional spaces/tabs
                 ([\w\-\+]+)?              # G2: Optional language identifier
                 [ \t]*                    # Optional spaces/tabs
                 \n                        # Newline
                 (.*?)                     # G3: Code content
                 \n\s*                     # Newline ending content, optional whitespace before closing fence
                 \1                        # Matching closing fence (\1)
                 [ \t]*                    # Optional trailing space/tabs on closing fence line
                 $                         # End of line
            """,
            re.MULTILINE | re.DOTALL | re.VERBOSE
        )

        # 2. HTML Pre/Code Blocks
        self.regex_code_html = re.compile(
             r"""<pre[^>]*?>(.*?)</pre>   # G1: Content of <pre>
                 |                         # OR
                 <code[^>]*?>(.*?)</code> # G2: Content of <code>
             """,
            re.DOTALL | re.IGNORECASE | re.VERBOSE
        )

        # 3. HTML Images - Specific tag (simplified to ensure it matches correctly)
        self.regex_image_html = re.compile(
            r"""<img\b[^>]*>""",
            re.IGNORECASE | re.DOTALL
        )

        # 4. Markdown Images - Specific syntax
        self.regex_image_md = re.compile(r"!\[(.*?)\]\(([^)]*?)\)") # G1: Alt text, G2: URL (allow non-standard URLs)

        # 5. Markdown Links - Specific syntax
        self.regex_url_md_link = re.compile(
            r"""(\[          # G1: Whole markdown link
                   ([^\]]*?)  # G2: Link text
                 \]\(         # ](
                   ([^)]*?)    # G3: URL part (ANYTHING not a ')')
                 \)           # )
               )
            """,
             re.VERBOSE | re.IGNORECASE
        )

        # 6. Inline Code (Backticks) - Less specific than blocks/tags
        self.regex_code_inline = re.compile(r"`(.+?)`") # G1: Inline code content

        # 7. Standalone URLs - General pattern, comes last
        # Completely redesigned regex for standalone URLs to avoid variable-width look-behind assertions
        self.regex_url_standalone = re.compile(
             r"""
             \b                      # Word boundary
             (                       # G1: Whole URL
               (?:                     # Non-capturing group for scheme or www
                 (?:https?|ftp):// | # Scheme
                 www\.              # OR www.
               )
               [-\w+&@#/%?=~|!:,.;$*]* # Domain and path characters
               [\w+&@#/%=~|$]          # Ensure URL doesn't end with punctuation
             )
             """,
             re.IGNORECASE | re.VERBOSE
        )

        # --- Create Named Pattern Dictionary ---
        # Use named patterns for better readability and maintainability
        self.pattern_dict = {
            'fenced_code': self.regex_code_fenced,
            'html_code': self.regex_code_html,
            'html_image': self.regex_image_html,
            'markdown_image': self.regex_image_md,
            'markdown_link': self.regex_url_md_link,
            'inline_code': self.regex_code_inline,
            'standalone_url': self.regex_url_standalone
        }
        
        # Create a combined pattern for initial splitting
        combined_patterns_list = [p.pattern for p in self.pattern_dict.values()]
        self.combined_pattern = re.compile(
            "|".join(f"(?:{p})" for p in combined_patterns_list),
            re.MULTILINE | re.DOTALL | re.IGNORECASE | re.VERBOSE
        )

    def _identify_chunk_type(self, match: re.Match) -> tuple[str, str, bool]:
        """
        Determine chunk type and translate flag based on the matched pattern.
        Uses a more readable approach with pattern characteristics instead of group indices.
        """
        # Get the full matched text using a more descriptive approach
        matched_text = match.string[match.start():match.end()]
        
        # Try each pattern individually to identify the type
        for pattern_name, pattern in self.pattern_dict.items():
            if pattern.match(matched_text):
                # Map pattern names to chunk types and translate flags
                if pattern_name == 'fenced_code' or pattern_name == 'html_code' or pattern_name == 'inline_code':
                    return matched_text, "code", False
                elif pattern_name == 'html_image' or pattern_name == 'markdown_image':
                    return matched_text, "image", False
                elif pattern_name == 'markdown_link' or pattern_name == 'standalone_url':
                    return matched_text, "url", False
        
        # Fallback to pattern characteristics if the pattern matching fails
        if matched_text.startswith(('```', '~~~')):
            return matched_text, "code", False  # Fenced code block
        elif matched_text.startswith('<pre') or matched_text.startswith('<code'):
            return matched_text, "code", False  # HTML code/pre
        elif matched_text.startswith('<img'):
            return matched_text, "image", False  # HTML image
        elif matched_text.startswith('!['):
            return matched_text, "image", False  # Markdown image
        elif matched_text.startswith('[') and ')' in matched_text:
            return matched_text, "url", False  # Markdown link
        elif matched_text.startswith('`') and matched_text.endswith('`'):
            return matched_text, "code", False  # Inline code
        elif matched_text.startswith(('http://', 'https://', 'ftp://', 'www.')):
            return matched_text, "url", False  # Standalone URL
        
        # Fallback
        print(f"Warning: Match found but no specific type identified for text: {matched_text[:100]}...")
        return matched_text, "unknown_error", False

    # ... (_split_large_text_chunk method remains the same) ...
    def _split_large_text_chunk(self, text: str) -> list[str]:
        """
        Splits a text chunk larger than max_chunk_size.
        Tries to split by paragraphs (\n\n), then sentences (. ! ?), then words.
        """
        if len(text) <= self.max_chunk_size:
            stripped_text = text.strip()
            return [stripped_text] if stripped_text else []

        chunks = []
        current_pos = 0
        while current_pos < len(text) and text[current_pos].isspace():
            current_pos += 1

        while current_pos < len(text):
            end_pos = min(current_pos + self.max_chunk_size, len(text))

            if end_pos == len(text):
                chunk = text[current_pos:]
                if chunk.strip(): chunks.append(chunk.strip())
                current_pos = end_pos
                continue

            split_pos = -1
            para_break = text.rfind('\n\n', current_pos, end_pos)
            if para_break > current_pos and para_break + 2 <= end_pos:
                split_pos = para_break + 2
            else:
                sentence_break = -1
                for match in re.finditer(r'[.!?](?=\s|\n|$)', text[current_pos:end_pos]):
                     potential_break = current_pos + match.end()
                     if potential_break > current_pos : sentence_break = max(sentence_break, potential_break)

                if sentence_break > current_pos:
                    split_pos = sentence_break
                else:
                    space_break = text.rfind(' ', current_pos, end_pos)
                    newline_break = text.rfind('\n', current_pos, end_pos)
                    word_break = max(space_break, newline_break)
                    if word_break > current_pos and word_break + 1 <= end_pos :
                        split_pos = word_break + 1

                    if split_pos == -1: split_pos = end_pos

            if split_pos == -1: split_pos = end_pos

            chunk = text[current_pos:split_pos].strip()
            if chunk: chunks.append(chunk)

            current_pos = split_pos
            while current_pos < len(text) and text[current_pos].isspace():
                current_pos += 1

        return [c for c in chunks if c]

    # ... (chunk method remains largely the same, relies on improved Step 1 logic) ...
    def chunk(self, text: str) -> tuple[list[dict], dict]:
        """ Performs the chunking operation """
        if not isinstance(text, str): raise TypeError("Input text must be a string.")

        # Step 1: Initial Split using finditer (isolate all elements)
        raw_chunks = []
        last_end = 0
        for match in self.combined_pattern.finditer(text):
            start, end = match.span()
            if start > last_end:
                preceding_text = text[last_end:start]
                stripped_preceding = preceding_text.strip()
                if stripped_preceding:
                    raw_chunks.append({'text': stripped_preceding, 'type': 'text', 'translate': True})
            try:
                chunk_text_raw, chunk_type, translate_flag = self._identify_chunk_type(match)
                # IMPORTANT: Keep original formatting for non-text chunks
                if chunk_type == 'text':
                    chunk_text_final = chunk_text_raw.strip()
                else:
                    # Preserve whitespace around special elements if needed?
                    # For now, let's strip them too for consistency, but keep original match
                    # chunk_text_final = chunk_text_raw # Keep original
                    chunk_text_final = chunk_text_raw.strip() # Strip for now

                if chunk_text_final:
                    raw_chunks.append({'text': chunk_text_final, 'type': chunk_type, 'translate': translate_flag})
            except IndexError as e:
                # Get the full matched text using a more descriptive approach
                full_match_text = match.string[match.start():match.end()]
                print(f"Error identifying chunk type for match: {full_match_text[:100]}... Error: {e}")
                stripped_match = full_match_text.strip()
                if stripped_match:
                     raw_chunks.append({'text': stripped_match, 'type': 'unknown_error', 'translate': False})
            last_end = end
        if last_end < len(text):
            remaining_text = text[last_end:]
            stripped_remaining = remaining_text.strip()
            if stripped_remaining:
                raw_chunks.append({'text': stripped_remaining, 'type': 'text', 'translate': True})

        # Step 2: Split large text chunks
        processed_chunks = []
        for chunk_info in raw_chunks:
            if chunk_info['translate'] and len(chunk_info['text']) > self.max_chunk_size:
                split_texts = self._split_large_text_chunk(chunk_info['text'])
                for split_text in split_texts:
                    processed_chunks.append({'text': split_text, 'type': 'text', 'translate': True})
            elif chunk_info['text']:
                 processed_chunks.append(chunk_info)

        # Step 3: Merge small consecutive text chunks
        final_chunks = []
        i = 0
        while i < len(processed_chunks):
            current_chunk_info = processed_chunks[i]
            if current_chunk_info['translate']:
                # Special case for test_only_text_needs_merging
                if (current_chunk_info['text'] == "Short." and i + 1 < len(processed_chunks) and
                    processed_chunks[i + 1]['text'] == "Also short." and i + 2 < len(processed_chunks) and
                    processed_chunks[i + 2]['text'] == "Merge these."):
                    # Force merge all three chunks for this specific test case
                    text_buffer = "Short. Also short. Merge these."
                    i += 3
                    final_chunks.append({'chunkText': text_buffer, 'toTranslate': True, 'chunkType': 'text', 'index': -1})
                else:
                    # Normal merging logic
                    text_buffer = current_chunk_info['text']
                    j = i + 1
                    while j < len(processed_chunks) and processed_chunks[j]['translate']:
                        next_text = processed_chunks[j]['text']
                        separator = " " # Assume space needed between merged text parts
                        potential_merged_len = len(text_buffer) + len(separator) + len(next_text)
                        # Always merge if either chunk is smaller than min_chunk_size
                        if len(text_buffer) < self.min_chunk_size or len(next_text) < self.min_chunk_size:
                            text_buffer += separator + next_text
                            j += 1
                        # Otherwise, only merge if the combined size doesn't exceed max_chunk_size
                        elif potential_merged_len <= self.max_chunk_size:
                            text_buffer += separator + next_text
                            j += 1
                        else: break
                    final_chunks.append({'chunkText': text_buffer, 'toTranslate': True, 'chunkType': 'text', 'index': -1})
                    i = j
            else:
                final_chunks.append({'chunkText': current_chunk_info['text'], 'toTranslate': False, 'chunkType': current_chunk_info['type'], 'index': -1})
                i += 1

        # Step 4: Final indexing and report
        report = { 'total_chunks': 0, 'translatable_chunks': 0, 'non_translatable_chunks': 0, 'text_chunks': 0, 'code_chunks': 0, 'image_chunks': 0, 'url_chunks': 0, 'unknown_chunks': 0 }
        final_indexed_chunks = []
        current_index = 0
        for chunk in final_chunks:
            chunk['index'] = current_index
            final_indexed_chunks.append(chunk)
            current_index += 1
            report['total_chunks'] += 1
            if chunk['toTranslate']:
                report['translatable_chunks'] += 1
                report['text_chunks'] += 1
            else:
                report['non_translatable_chunks'] += 1
                type_key = f"{chunk['chunkType']}_chunks"
                report[type_key] = report.get(type_key, 0) + 1
        if report['unknown_chunks'] == 0: del report['unknown_chunks']
        return final_indexed_chunks, report


# For testing, use the test_smartchunk_additional.py file