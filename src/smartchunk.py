import re
import math # Not directly used now, but kept for potential future use

class SmartChunker:
    """
    Chunks Markdown formatted text, identifying and separating code blocks,
    images, and URLs, while respecting minimum and maximum chunk sizes for
    translatable text segments.
    """

    def __init__(self, min_chunk_size: int = 50, max_chunk_size: int = 500, mode: str = "smart", separators: list = None):
        # Validate mode
        valid_modes = ["smart", "line", "symbol", "subtitle_srt"]
        if mode not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}")
        
        self.mode = mode
        
        # Validate separators for symbol mode
        if mode == "symbol":
            if separators is not None:
                if not separators:
                    raise ValueError("separators list cannot be empty")
                self.separators = separators
            else:
                # Default separators for symbol mode
                self.separators = [".", ",", " ", "\n", "\n\n"]
        else:
            # Default separators for other modes (not used but kept for consistency)
            self.separators = separators or [
                "\n\n", "\n", " ", ".", ",", "\u200b",  # Zero-width space
                "\uff0c",  # Fullwidth comma
                "\u3001",  # Ideographic comma
                "\uff0e",  # Fullwidth full stop
                "\u3002",  # Ideographic full stop
                ""
            ]
        
        # Validate min_chunk_size and max_chunk_size
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
        # Note: We'll handle inline code specially in the chunking process
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
        
        # 8. Footnote references - Should not be translated
        self.regex_footnote_ref = re.compile(
            r"""
            ^\s*\[(\^[0-9]+)\]:      # G1: Footnote reference marker with optional leading whitespace (e.g., [^1]:)
            """,
            re.MULTILINE | re.VERBOSE
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
            'standalone_url': self.regex_url_standalone,
            'footnote_ref': self.regex_footnote_ref
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
                elif pattern_name == 'footnote_ref':
                    return matched_text, "footnote", False
        
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
        elif re.match(r'^\s*\[\^[0-9]+\]:', matched_text):
            return matched_text, "footnote", False  # Footnote reference
        
        # Fallback
        print(f"Warning: Match found but no specific type identified for text: {matched_text[:100]}...")
        return matched_text, "unknown_error", False

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

    def chunk(self, text: str) -> tuple[list[dict], dict]:
        """Performs the chunking operation based on the selected mode."""
        if not isinstance(text, str):
            raise TypeError("Input text must be a string.")
        
        if self.mode == "smart":
            return self._chunk_smart(text)
        elif self.mode == "line":
            return self._chunk_line(text)
        elif self.mode == "symbol":
            return self._chunk_symbol(text)
        elif self.mode == "subtitle_srt":
            return self._chunk_subtitle_srt(text)
    
    def _chunk_smart(self, text: str) -> tuple[list[dict], dict]:
        """Original smart chunking algorithm."""
        if not isinstance(text, str): raise TypeError("Input text must be a string.")

        # Step 1: Initial Split using finditer (isolate all elements)
        raw_chunks = []
        last_end = 0
        
        # First pass: Identify all potential chunks
        potential_chunks = []
        for match in self.combined_pattern.finditer(text):
            start, end = match.span()
            if start > last_end:
                preceding_text = text[last_end:start]
                stripped_preceding = preceding_text.strip()
                if stripped_preceding:
                    # New rule: If chunk has less than 2 chars, it's considered non-translatable
                    is_translatable = len(stripped_preceding) >= 2
                    potential_chunks.append({
                        'text': stripped_preceding,
                        'type': 'text',
                        'translate': is_translatable,
                        'start': last_end,
                        'end': start
                    })
            
            try:
                chunk_text_raw, chunk_type, translate_flag = self._identify_chunk_type(match)
                chunk_text_final = chunk_text_raw.strip()
                
                if chunk_text_final:
                    potential_chunks.append({
                        'text': chunk_text_final, 
                        'type': chunk_type, 
                        'translate': translate_flag,
                        'start': start,
                        'end': end,
                        'raw': chunk_text_raw
                    })
            except IndexError as e:
                full_match_text = match.string[match.start():match.end()]
                print(f"Error identifying chunk type for match: {full_match_text[:100]}... Error: {e}")
                stripped_match = full_match_text.strip()
                if stripped_match:
                    potential_chunks.append({
                        'text': stripped_match, 
                        'type': 'unknown_error', 
                        'translate': False,
                        'start': start,
                        'end': end
                    })
            
            last_end = end
        
        if last_end < len(text):
            remaining_text = text[last_end:]
            stripped_remaining = remaining_text.strip()
            if stripped_remaining:
                # New rule: If chunk has less than 2 chars, it's considered non-translatable
                is_translatable = len(stripped_remaining) >= 2
                potential_chunks.append({
                    'text': stripped_remaining,
                    'type': 'text',
                    'translate': is_translatable,
                    'start': last_end,
                    'end': len(text)
                })
        
        # Second pass: Process special cases
        
        # First, identify bullet points or lists with multiple inline code segments or links
        bullet_points = []
        i = 0
        while i < len(potential_chunks):
            # Look for text chunks that might be the start of a bullet point or list item
            if (potential_chunks[i]['type'] == 'text' and
                (('-' in potential_chunks[i]['text'] and potential_chunks[i]['text'].strip().startswith('-')) or
                 ('*' in potential_chunks[i]['text'] and potential_chunks[i]['text'].strip().startswith('*')))):
                
                # Special case: Check if this is a bullet point followed by a link
                if (i + 1 < len(potential_chunks) and
                    potential_chunks[i+1]['type'] == 'url' and
                    potential_chunks[i]['text'].strip() in ['-', '*']):
                    # This is a bullet point with a link, merge them and ensure it's translatable
                    bullet_points.append((i, i+1))
                    i += 2
                    continue
                
                # Check if this is followed by inline code and more text
                bullet_start = i
                bullet_end = i
                has_inline_code = False
                
                # Look ahead to find all related chunks
                j = i + 1
                while j < len(potential_chunks):
                    # If we find inline code, mark it
                    if potential_chunks[j]['type'] == 'code' and '`' in potential_chunks[j]['text'] and len(potential_chunks[j]['text']) < 50:
                        has_inline_code = True
                        bullet_end = j
                    # If we find text that might be part of the same bullet point
                    elif potential_chunks[j]['type'] == 'text' and (
                        ',' in potential_chunks[j]['text'] or
                        ' and ' in potential_chunks[j]['text'] or
                        potential_chunks[j]['text'].strip().startswith('for') or
                        potential_chunks[j]['text'].strip().startswith('to') or
                        potential_chunks[j]['text'].strip().startswith('of')):
                        bullet_end = j
                    # If we find a new paragraph or another bullet point, stop
                    elif potential_chunks[j]['type'] == 'text' and (
                        '\n\n' in potential_chunks[j]['text'] or
                        potential_chunks[j]['text'].strip().startswith('-') or
                        potential_chunks[j]['text'].strip().startswith('*')):
                        break
                    else:
                        # If it's not related to the bullet point, stop
                        if j > bullet_end + 1:
                            break
                        bullet_end = j
                    j += 1
                
                # If we found a bullet point with inline code, add it to our list
                if has_inline_code and bullet_end > bullet_start:
                    # Make sure this is actually a bullet point and not just text with a dash
                    if potential_chunks[bullet_start]['text'].strip().startswith('-') or potential_chunks[bullet_start]['text'].strip().startswith('*'):
                        bullet_points.append((bullet_start, bullet_end))
                        i = bullet_end + 1
                        continue
            
            i += 1
        
        # Now merge the identified bullet points
        for start, end in sorted(bullet_points, reverse=True):  # Process in reverse to avoid index issues
            # Merge all chunks in the bullet point into a single chunk
            merged_text = ""
            for i in range(start, end + 1):
                if i > start:
                    merged_text += " "
                merged_text += potential_chunks[i]['text']
            
            # Update the first chunk with the merged text and ensure it's translatable
            potential_chunks[start]['text'] = merged_text
            potential_chunks[start]['end'] = potential_chunks[end]['end']
            potential_chunks[start]['translate'] = True  # Always make bullet points with links translatable
            
            # Remove the merged chunks
            for i in range(end, start, -1):
                potential_chunks.pop(i)
        
        # Process remaining special cases
        i = 0
        while i < len(potential_chunks):
            current = potential_chunks[i]
            
            # Special case: Inline code within bullet points or paragraphs (for any we missed)
            if current['type'] == 'code' and '`' in current['text'] and len(current['text']) < 50:
                # Check if this is part of a bullet point or list
                is_in_bullet = False
                is_in_list = False
                
                # Look at previous chunk
                if i > 0 and potential_chunks[i-1]['type'] == 'text':
                    prev_text = potential_chunks[i-1]['text']
                    if prev_text.strip().endswith('-') or prev_text.strip().endswith('*'):
                        is_in_bullet = True
                    # Check if we're in a list (contains bullet points)
                    if '-' in prev_text or '*' in prev_text:
                        is_in_list = True
                
                # Look at next chunk
                if i < len(potential_chunks) - 1 and potential_chunks[i+1]['type'] == 'text':
                    next_text = potential_chunks[i+1]['text']
                    if next_text.strip().startswith('for') or next_text.strip().startswith('to') or next_text.strip().startswith('of'):
                        is_in_bullet = True
                    # Check if we're in a list (contains commas, 'and', etc.)
                    if ',' in next_text or ' and ' in next_text:
                        is_in_list = True
                
                if is_in_bullet or is_in_list:
                    # Merge with surrounding text
                    if i > 0 and i < len(potential_chunks) - 1 and potential_chunks[i-1]['type'] == 'text' and potential_chunks[i+1]['type'] == 'text':
                        # Merge previous, current, and next chunks
                        merged_text = potential_chunks[i-1]['text'] + ' ' + current['text'] + ' ' + potential_chunks[i+1]['text']
                        potential_chunks[i-1]['text'] = merged_text
                        potential_chunks[i-1]['end'] = potential_chunks[i+1]['end']
                        # Remove current and next chunks
                        potential_chunks.pop(i)
                        potential_chunks.pop(i)
                        i -= 1  # Adjust index
                    elif i > 0 and potential_chunks[i-1]['type'] == 'text':
                        # Merge with previous chunk
                        potential_chunks[i-1]['text'] += ' ' + current['text']
                        potential_chunks[i-1]['end'] = current['end']
                        potential_chunks.pop(i)
                        i -= 1  # Adjust index
                    elif i < len(potential_chunks) - 1 and potential_chunks[i+1]['type'] == 'text':
                        # Merge with next chunk
                        potential_chunks[i+1]['text'] = current['text'] + ' ' + potential_chunks[i+1]['text']
                        potential_chunks[i+1]['start'] = current['start']
                        potential_chunks.pop(i)
                        i -= 1  # Adjust index
            
            i += 1
        
        # Convert potential_chunks to raw_chunks
        for chunk in potential_chunks:
            raw_chunks.append({
                'text': chunk['text'],
                'type': chunk['type'],
                'translate': chunk['translate']
            })

        # Step 2: Split large text chunks
        processed_chunks = []
        for chunk_info in raw_chunks:
            if chunk_info['translate'] and len(chunk_info['text']) > self.max_chunk_size:
                split_texts = self._split_large_text_chunk(chunk_info['text'])
                for split_text in split_texts:
                    processed_chunks.append({'text': split_text, 'type': 'text', 'translate': True})
            elif chunk_info['text']:
                 processed_chunks.append(chunk_info)

        # Step 3: Merge consecutive chunks of the same type if they're small
        final_chunks = []
        i = 0
        while i < len(processed_chunks):
            current_chunk_info = processed_chunks[i]
            
            if current_chunk_info['translate']:
                # Merging logic for translatable text chunks
                text_buffer = current_chunk_info['text']
                j = i + 1
                
                # Continue merging until we reach a non-translatable chunk or exceed max_chunk_size
                while j < len(processed_chunks) and processed_chunks[j]['translate']:
                    next_text = processed_chunks[j]['text']
                    next_text_len = len(next_text)
                    separator = " " # Assume space needed between merged text parts
                    potential_merged_len = len(text_buffer) + len(separator) + next_text_len
                    
                    # Case 1: Always merge if either current buffer or next chunk is smaller than min_chunk_size
                    # This ensures we try to merge small chunks together regardless of their position
                    if len(text_buffer) < self.min_chunk_size or next_text_len < self.min_chunk_size:
                        # Only stop merging if we would exceed max_chunk_size by a significant margin
                        if potential_merged_len > self.max_chunk_size * 1.2:  # Allow some flexibility
                            break
                        text_buffer += separator + next_text
                        j += 1
                    # Case 2: If both chunks are large enough, only merge if it doesn't exceed max_chunk_size
                    elif potential_merged_len <= self.max_chunk_size:
                        text_buffer += separator + next_text
                        j += 1
                    # Case 3: We've reached max_chunk_size, stop merging
                    else:
                        break
                
                final_chunks.append({'chunkText': text_buffer, 'toTranslate': True, 'chunkType': 'text', 'index': -1})
                i = j
            else:
                # For non-translatable chunks, we'll be more conservative with merging
                # Only merge if they're consecutive, of the same type, and both are very small
                current_type = current_chunk_info['type']
                
                # Special handling for URL, image, and code chunks - don't merge these
                # as they often need to be preserved separately
                if current_type in ['url', 'image', 'code', 'footnote']:
                    final_chunks.append({'chunkText': current_chunk_info['text'], 'toTranslate': False, 'chunkType': current_type, 'index': -1})
                    i += 1
                else:
                    # For other non-translatable chunks, apply merging logic
                    content_buffer = current_chunk_info['text']
                    j = i + 1
                    
                    # Continue merging until we reach a different type chunk
                    while j < len(processed_chunks) and not processed_chunks[j]['translate'] and processed_chunks[j]['type'] == current_type:
                        next_content = processed_chunks[j]['text']
                        next_content_len = len(next_content)
                        separator = " " # Assume space needed between merged parts
                        potential_merged_len = len(content_buffer) + len(separator) + next_content_len
                        
                        # Only merge if both chunks are very small (less than half the min_chunk_size)
                        if len(content_buffer) < self.min_chunk_size / 2 and next_content_len < self.min_chunk_size / 2:
                            content_buffer += separator + next_content
                            j += 1
                        else:
                            break
                    
                    final_chunks.append({'chunkText': content_buffer, 'toTranslate': False, 'chunkType': current_type, 'index': -1})
                    i = j

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
    
    def _chunk_line(self, text: str) -> tuple[list[dict], dict]:
        """
        Chunks text by lines, ignoring empty lines.
        Each line becomes a separate chunk regardless of length.
        All chunks are considered translatable.
        """
        lines = text.split("\n")
        chunks = []
        report = {
            'total_chunks': 0,
            'translatable_chunks': 0,
            'non_translatable_chunks': 0,
            'text_chunks': 0
        }
        
        for line in lines:
            line = line.strip()
            if line:  # Skip empty lines
                chunk = {
                    'chunkText': line,
                    'toTranslate': True,
                    'chunkType': 'text',
                    'index': len(chunks)
                }
                chunks.append(chunk)
                report['total_chunks'] += 1
                report['translatable_chunks'] += 1
                report['text_chunks'] += 1
        
        return chunks, report
    
    def _chunk_symbol(self, text: str) -> tuple[list[dict], dict]:
        """
        Chunks text based on a list of separator symbols.
        All chunks are considered translatable.
        """
        chunks = []
        report = {
            'total_chunks': 0,
            'translatable_chunks': 0,
            'non_translatable_chunks': 0,
            'text_chunks': 0
        }
        
        # Separators list is guaranteed non-empty by __init__ validation.
        
        # Start with the whole text
        current_chunks = [text]
        
        # Iterate through separators and split chunks
        for separator in self.separators:
            if not separator:  # Skip empty separator
                continue
            
            new_chunks = []
            for chunk in current_chunks:
                if separator in chunk:
                    # Split by this separator and keep the order
                    parts = chunk.split(separator)
                    for part in parts:
                        new_chunks.append(part)
                else:
                    new_chunks.append(chunk)
            
            # Update current_chunks for the next separator
            current_chunks = new_chunks
        
        # Create final chunks
        for i, chunk_text in enumerate(current_chunks):
            chunk_text = chunk_text.strip()
            if chunk_text:  # Skip empty chunks
                chunk = {
                    'chunkText': chunk_text,
                    'toTranslate': True,
                    'chunkType': 'text',
                    'index': i
                }
                chunks.append(chunk)
                report['total_chunks'] += 1
                report['translatable_chunks'] += 1
                report['text_chunks'] += 1
        
        return chunks, report
    
    def _chunk_subtitle_srt(self, text: str) -> tuple[list[dict], dict]:
        """
        Chunks .srt subtitle files into timing sections (non-translatable) and content sections (translatable).
        Preserves original formatting.
        """
        chunks = []
        report = {
            'total_chunks': 0,
            'translatable_chunks': 0,
            'non_translatable_chunks': 0,
            'text_chunks': 0,
            'timing_chunks': 0
        }
        
        # Regular expression to match SRT format:
        # 1. Line number
        # 2. Timestamp line (00:00:00,000 --> 00:00:00,000)
        # 3. Content (one or more lines)
        # 4. Blank line
        
        import re
        pattern = re.compile(r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}(?:[ \t]+X1:\d+ X2:\d+ Y1:\d+ Y2:\d+)?)\s*\n((?:.+(?:\n|$))+?)(?:\n\s*\n|$)', re.MULTILINE)
        
        matches = list(pattern.finditer(text))
        
        # If no matches found, treat the entire text as a single chunk
        if not matches:
            chunks.append({
                'chunkText': text.strip(),
                'toTranslate': True,
                'chunkType': 'text',
                'index': 0
            })
            report['total_chunks'] = 1
            report['translatable_chunks'] = 1
            report['text_chunks'] = 1
            return chunks, report
        
        for match in matches:
            # Timing section (non-translatable)
            line_num = match.group(1)
            timestamp = match.group(2)
            timing_text = f"{line_num}\n{timestamp}"
            
            timing_chunk = {
                'chunkText': timing_text,
                'toTranslate': False,
                'chunkType': 'timing',
                'index': len(chunks)
            }
            chunks.append(timing_chunk)
            report['total_chunks'] += 1
            report['non_translatable_chunks'] += 1
            report['timing_chunks'] = report.get('timing_chunks', 0) + 1
            
            # Content section (translatable)
            content = match.group(3).strip()
            if content:
                content_chunk = {
                    'chunkText': content,
                    'toTranslate': True,
                    'chunkType': 'text',
                    'index': len(chunks)
                }
                chunks.append(content_chunk)
                report['total_chunks'] += 1
                report['translatable_chunks'] += 1
                report['text_chunks'] += 1
        
        return chunks, report