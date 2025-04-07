from typing import List
from markdown_it import MarkdownIt
from markdown_it.token import Token

# Note: This chunking logic is complex and might need further refinement
# based on specific markdown variations encountered.

def create_semantic_chunks(markdown_content: str, max_chunk_size: int = 2000) -> List[str]:
    """
    Splits markdown content into semantic chunks based on headings and max length.
    Tries to keep paragraphs and code blocks intact. Uses markdown-it-py.
    """
    if not markdown_content:
        return []

    md = MarkdownIt()
    try:
        tokens = md.parse(markdown_content)
    except Exception as e:
        print(f"Error parsing markdown content with markdown-it-py: {e}")
        # Fallback to simple splitting if parser fails
        return [chunk for chunk in markdown_content.split('\n\n') if chunk.strip()]


    chunks: List[str] = []
    current_chunk_tokens: List[Token] = []
    current_length = 0

    def render_tokens_to_text(token_list: List[Token]) -> str:
        """Renders a list of markdown-it tokens back to markdown text."""
        # This is a simplified renderer. For full fidelity, consider integrating
        # with markdown-it's renderer or tracking raw text slices.
        text = ""
        for t in token_list:
            markup = getattr(t, 'markup', '')
            content = getattr(t, 'content', '')
            info = getattr(t, 'info', '') # For fence language
            tag = getattr(t, 'tag', '') # HTML tag if relevant

            # Handle different token types for reconstruction
            if t.type == 'heading_open':
                text += markup + " "
            elif t.type == 'paragraph_open':
                # Add newline before new paragraph only if text exists
                if text.strip() and not text.endswith('\n'): text += "\n"
            elif t.type == 'inline':
                text += content # Inline content is already formatted text
            elif t.type == 'text':
                 text += content
            elif t.type == 'softbreak':
                 text += "\n" # Render softbreaks as newlines
            elif t.type == 'hardbreak':
                 text += "\n" # Render hardbreaks as newlines too
            elif t.type == 'code_inline':
                 text += f"`{content}`"
            elif t.type == 'fence':
                 # Add newline before code block if needed
                 if text.strip() and not text.endswith('\n\n'): text += "\n\n"
                 text += f"{markup}{info}\n{content}{markup}\n"
            elif t.type == 'bullet_list_open' or t.type == 'ordered_list_open':
                # Add newline before list if needed
                if text.strip() and not text.endswith('\n\n'): text += "\n\n"
            elif t.type == 'list_item_open':
                # Ensure list item starts on a new line relative to previous content/item
                if not text.endswith('\n'): text += "\n"
                text += markup + " "
            elif t.type == 'hr':
                 if text.strip() and not text.endswith('\n\n'): text += "\n\n"
                 text += "---\n"
            elif t.type == 'blockquote_open':
                 if text.strip() and not text.endswith('\n\n'): text += "\n\n"
                 text += markup + " " # Add "> "
            # Add more rules for tables, html_block, etc. if needed

            # Handle closing tags - mostly for adding vertical space
            elif t.nesting == -1: # Closing tags
                 if t.type == 'paragraph_close':
                     if not text.endswith('\n'): text += "\n" # Ensure paragraphs end with newline
                 elif t.type == 'blockquote_close':
                      if not text.endswith('\n'): text += "\n"
                 # Other closing tags usually don't need explicit text unless managing indentation

            # Fallback for simple content not covered above
            # elif content and not getattr(t, 'children', None):
            #      text += content

        # Final cleanup of potentially excessive newlines
        import re
        text = re.sub(r'\n{3,}', '\n\n', text.strip()) # Replace 3+ newlines with 2
        return text

    # Track code blocks and image references to ensure they're not split
    in_code_block = False
    code_block_tokens = []
    image_tokens = []
    
    for i, token in enumerate(tokens):
        # Special handling for code blocks - keep them intact
        if token.type == 'fence' and token.nesting == 0:
            in_code_block = not in_code_block
            if in_code_block:  # Start of code block
                code_block_tokens = [token]
                continue
            else:  # End of code block - add the closing fence to the block
                code_block_tokens.append(token)
                # Render the entire code block as one unit
                code_block = render_tokens_to_text(code_block_tokens)
                
                # If adding this code block would exceed max size and we have content,
                # finalize current chunk first
                if current_length > 0 and (current_length + len(code_block)) > max_chunk_size:
                    rendered_chunk = render_tokens_to_text(current_chunk_tokens)
                    if rendered_chunk:
                        chunks.append(rendered_chunk)
                    current_chunk_tokens = []
                    current_length = 0
                
                # Add the entire code block to the current chunk
                current_chunk_tokens.extend(code_block_tokens)
                current_length += len(code_block)
                code_block_tokens = []
                continue
        
        # If we're inside a code block, collect tokens but don't process them yet
        if in_code_block:
            code_block_tokens.append(token)
            continue
            
        # Special handling for image references - keep them with surrounding text
        if token.type == 'image' or (token.type == 'inline' and '![' in token.content):
            image_tokens.append(token)
            # Don't split here, continue collecting tokens
            
        # Estimate token text for length check (approximation)
        token_text_estimate = ""
        if token.content: token_text_estimate += token.content
        if token.markup: token_text_estimate += token.markup
        # Add potential extra newline chars
        if token.type in ['paragraph_close', 'fence', 'hr', 'list_item_open', 'heading_open']:
            token_text_estimate += "\n"
        token_len_estimate = len(token_text_estimate)

        # --- Logic for Splitting ---

        # 1. Check if adding the current token *might* exceed max size
        # Use a buffer (e.g., 10%) to account for rendering inaccuracies
        potential_new_length = current_length + token_len_estimate
        if potential_new_length > max_chunk_size and current_length > 0:
             # Finalize the current chunk *before* adding the potentially oversized token
             rendered_chunk = render_tokens_to_text(current_chunk_tokens)
             if rendered_chunk:
                 chunks.append(rendered_chunk)
             current_chunk_tokens = []
             current_length = 0

             # If the current token *itself* likely exceeds max size
             if token_len_estimate > max_chunk_size:
                 print(f"Warning: Token of type {token.type} content/markup length ({token_len_estimate}) exceeds max_chunk_size ({max_chunk_size}). Adding as potentially oversized chunk.")
                 # Render just this token as its own chunk (may still be > max_size)
                 oversized_chunk = render_tokens_to_text([token])
                 if oversized_chunk:
                     chunks.append(oversized_chunk)
                 # Skip adding this token to current_chunk_tokens and continue to next token
                 continue


        # 2. Check for semantic split points (e.g., new heading) BEFORE adding token
        # Split if we encounter a major heading (h1, h2, h3) and the current chunk is not empty
        if token.type == 'heading_open' and token.tag in ['h1', 'h2', 'h3'] and current_length > 0:
             # Don't split in the middle of a code block or right after an image
             if not in_code_block and not image_tokens:
                 rendered_chunk = render_tokens_to_text(current_chunk_tokens)
                 if rendered_chunk:
                     chunks.append(rendered_chunk)
                 # Start new chunk with the heading token
                 current_chunk_tokens = [token]
                 current_length = token_len_estimate # Reset length to current token's estimate
                 continue # Skip the general add step below

        # --- Add Token to Current Chunk ---
        current_chunk_tokens.append(token)
        current_length += token_len_estimate # Accumulate estimated length

    # Add the final chunk if any tokens remain
    if current_chunk_tokens:
        rendered_chunk = render_tokens_to_text(current_chunk_tokens)
        if rendered_chunk:
            chunks.append(rendered_chunk)

    # Filter out any empty chunks that might have resulted
    return [chunk for chunk in chunks if chunk]
