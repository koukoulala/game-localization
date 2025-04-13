import aiosqlite
import sqlite3
import os
import json
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "translations.db")

async def init_db():
    """Initialize the database and create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    # Check if we need to run migrations
    need_migration = False
    need_filename_migration = False
    need_env_tables = False
    need_llm_tables = False
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Check if the jobs table exists
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
            if await cursor.fetchone():
                # Check if started_at column exists
                try:
                    await db.execute("SELECT started_at FROM jobs LIMIT 1")
                except sqlite3.OperationalError:
                    need_migration = True
                
                # Check if filename column exists
                try:
                    await db.execute("SELECT filename FROM jobs LIMIT 1")
                except sqlite3.OperationalError:
                    need_filename_migration = True
            
            # Check if env_variables table exists
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='env_variables'")
            if not await cursor.fetchone():
                need_env_tables = True
            
            # Check if llm_config table exists
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_config'")
            if not await cursor.fetchone():
                need_llm_tables = True
                
    except Exception as e:
        print(f"Error checking for migrations: {e}")
    
    # Create tables
    async with aiosqlite.connect(DB_PATH) as db:
        # Create jobs table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            original_content TEXT,
            final_document TEXT,
            source_lang TEXT,
            target_lang TEXT,
            provider TEXT,
            model TEXT,
            target_language_accent TEXT,
            status TEXT,
            progress_percent REAL,
            current_step TEXT,
            created_at TIMESTAMP,
            started_at TIMESTAMP,
            updated_at TIMESTAMP,
            completed_at TIMESTAMP,
            error_info TEXT,
            config_json TEXT,
            filename TEXT
        )
        """)
        
        # Create environment variables table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS env_variables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            description TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """)
        
        # Create LLM configuration table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS llm_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            model TEXT,
            source_lang TEXT,
            target_lang TEXT,
            target_language_accent TEXT,
            is_default BOOLEAN DEFAULT 0,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """)
        
        # Create chunks table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS job_chunks (
            chunk_id TEXT PRIMARY KEY,
            job_id TEXT,
            chunk_index INTEGER,
            original_chunk TEXT,
            translated_chunk TEXT,
            refined_chunk TEXT,
            critique_feedback TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
        """)
        
        # Create logs table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS job_logs (
            log_id TEXT PRIMARY KEY,
            job_id TEXT,
            level TEXT,
            message TEXT,
            node TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
        """)
        
        # Create metrics table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS job_metrics (
            metric_id TEXT PRIMARY KEY,
            job_id TEXT,
            start_time REAL,
            end_time REAL,
            duration_seconds REAL,
            total_chunks INTEGER,
            word_count_source INTEGER,
            word_count_target INTEGER,
            additional_metrics_json TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
        """)
        
        # Create glossary table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS job_glossary (
            glossary_id TEXT PRIMARY KEY,
            job_id TEXT,
            source_term TEXT,
            target_term TEXT,
            context TEXT,
            metadata_json TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
        """)
        
        # Create critiques table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS job_critiques (
            critique_id TEXT PRIMARY KEY,
            job_id TEXT,
            chunk_index INTEGER,
            critique_text TEXT,
            critique_category TEXT,
            critique_score REAL,
            critique_metadata_json TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id)
        )
        """)
        await db.commit()
    
    # Run migrations if needed
    if need_migration or need_filename_migration or need_env_tables or need_llm_tables:
        print("Running database migrations...")
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Add started_at column to jobs table if needed
                if need_migration:
                    print("Adding started_at column to jobs table...")
                    await db.execute("ALTER TABLE jobs ADD COLUMN started_at TIMESTAMP")
                    
                    # Set started_at for existing jobs
                    await db.execute("""
                    UPDATE jobs
                    SET started_at = created_at
                    WHERE started_at IS NULL
                    """)
                
                # Add filename column to jobs table if needed
                if need_filename_migration:
                    print("Adding filename column to jobs table...")
                    await db.execute("ALTER TABLE jobs ADD COLUMN filename TEXT")
                
                # Create env_variables table if needed
                if need_env_tables:
                    print("Creating env_variables table...")
                    await db.execute("""
                    CREATE TABLE IF NOT EXISTS env_variables (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT UNIQUE,
                        value TEXT,
                        description TEXT,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """)
                
                # Create llm_config table if needed
                if need_llm_tables:
                    print("Creating llm_config table...")
                    await db.execute("""
                    CREATE TABLE IF NOT EXISTS llm_config (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        provider TEXT,
                        model TEXT,
                        source_lang TEXT,
                        target_lang TEXT,
                        target_language_accent TEXT,
                        api_url TEXT,
                        is_default BOOLEAN DEFAULT 0,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """)
                
                await db.commit()
                print("Migration completed successfully.")
        except Exception as e:
            print(f"Error during migration: {e}")


# Job CRUD operations
async def create_job(job_data: Dict[str, Any]) -> str:
    """Create a new job in the database."""
    job_id = job_data.get("job_id") or str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    config = job_data.get("config", {})
    
    # Generate filename if provided in the original file
    original_filename = job_data.get("original_filename", "")
    source_lang = config.get("source_lang", "")
    target_lang = config.get("target_lang", "")
    
    filename = ""
    if original_filename:
        # Remove file extension if present
        base_name = os.path.splitext(original_filename)[0]
        # Strip spaces and non-allowed characters
        base_name = "".join(c for c in base_name if c.isalnum() or c in "-_.")
        # Create filename with format: [original file name]_[source language]_[target language]
        filename = f"{base_name}_{source_lang}_{target_lang}"
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO jobs (
            job_id, original_content, source_lang, target_lang,
            provider, model, target_language_accent, status, progress_percent,
            current_step, created_at, updated_at, config_json, filename
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            job_data.get("original_content", ""),
            config.get("source_lang", ""),
            config.get("target_lang", ""),
            config.get("provider", ""),
            config.get("model", ""),
            config.get("target_language_accent", ""),
            "pending",
            0.0,
            "queued",
            now,
            now,
            json.dumps(config),
            filename
        ))
        await db.commit()
    
    return job_id

async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a job by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return dict(row)

async def update_job(job_id: str, updates: Dict[str, Any]) -> bool:
    """Update a job with the provided updates."""
    if not updates:
        return False
    
    now = datetime.now().isoformat()
    updates["updated_at"] = now
    
    # Handle completed_at if status is changing to completed or failed
    if "status" in updates and updates["status"] in ["completed", "failed"]:
        updates["completed_at"] = now
    
    # Build the SQL query dynamically
    set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
    values = list(updates.values())
    values.append(job_id)  # For the WHERE clause
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE jobs SET {set_clause} WHERE job_id = ?", values)
        await db.commit()
    
    return True

async def get_next_pending_job() -> Optional[Dict[str, Any]]:
    """Get the next pending job from the queue."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM jobs 
        WHERE status = 'pending' 
        ORDER BY created_at ASC 
        LIMIT 1
        """)
        row = await cursor.fetchone()
        
        if row:
            return dict(row)
        return None

async def list_jobs(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """List jobs with pagination."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT job_id, source_lang, target_lang, provider, model,
               target_language_accent, status, progress_percent,
               created_at, started_at, updated_at, completed_at, error_info, current_step,
               filename
        FROM jobs
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """, (limit, offset))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# Chunk operations
async def add_chunk(job_id: str, chunk_index: int, original_chunk: str) -> str:
    """Add a chunk to a job."""
    chunk_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO job_chunks (
            chunk_id, job_id, chunk_index, original_chunk, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            chunk_id,
            job_id,
            chunk_index,
            original_chunk,
            now,
            now
        ))
        await db.commit()
    
    return chunk_id

async def update_chunk(chunk_id: str, updates: Dict[str, Any]) -> bool:
    """Update a chunk with the provided updates."""
    if not updates:
        return False
    
    now = datetime.now().isoformat()
    updates["updated_at"] = now
    
    # Build the SQL query dynamically
    set_clause = ", ".join([f"{key} = ?" for key in updates.keys()])
    values = list(updates.values())
    values.append(chunk_id)  # For the WHERE clause
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE job_chunks SET {set_clause} WHERE chunk_id = ?", values)
        await db.commit()
    
    return True

async def get_chunks(job_id: str) -> List[Dict[str, Any]]:
    """Get all chunks for a job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM job_chunks
        WHERE job_id = ?
        ORDER BY chunk_index
        """, (job_id,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_job(job_id: str) -> bool:
    """Delete a job and all related data."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Start a transaction
        await db.execute("BEGIN TRANSACTION")
        
        try:
            # Delete related data first (foreign key constraints)
            await db.execute("DELETE FROM job_logs WHERE job_id = ?", (job_id,))
            await db.execute("DELETE FROM job_chunks WHERE job_id = ?", (job_id,))
            await db.execute("DELETE FROM job_glossary WHERE job_id = ?", (job_id,))
            await db.execute("DELETE FROM job_critiques WHERE job_id = ?", (job_id,))
            await db.execute("DELETE FROM job_metrics WHERE job_id = ?", (job_id,))
            
            # Delete the job itself
            await db.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            
            # Commit the transaction
            await db.commit()
            return True
        except Exception as e:
            # Rollback in case of error
            await db.execute("ROLLBACK")
            print(f"Error deleting job {job_id}: {e}")
            return False

# Log operations
async def add_log(job_id: str, level: str, message: str, node: str = None) -> str:
    """Add a log entry for a job."""
    log_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO job_logs (
            log_id, job_id, level, message, node, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            log_id,
            job_id,
            level,
            message,
            node,
            now
        ))
        await db.commit()
    
    return log_id

async def get_logs(job_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Get logs for a job with pagination."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM job_logs
        WHERE job_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """, (job_id, limit, offset))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# Glossary operations
async def add_glossary_entry(job_id: str, source_term: str, target_term: str, 
                            context: str = None, metadata: Dict[str, Any] = None) -> str:
    """Add a glossary entry for a job."""
    glossary_id = str(uuid.uuid4())
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO job_glossary (
            glossary_id, job_id, source_term, target_term, context, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            glossary_id,
            job_id,
            source_term,
            target_term,
            context,
            json.dumps(metadata) if metadata else None
        ))
        await db.commit()
    
    return glossary_id

async def get_glossary(job_id: str) -> List[Dict[str, Any]]:
    """Get all glossary entries for a job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM job_glossary
        WHERE job_id = ?
        """, (job_id,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# Critique operations
async def add_critique(job_id: str, chunk_index: int, critique_text: str,
                      category: str = None, score: float = None, 
                      metadata: Dict[str, Any] = None) -> str:
    """Add a critique for a job chunk."""
    critique_id = str(uuid.uuid4())
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO job_critiques (
            critique_id, job_id, chunk_index, critique_text, 
            critique_category, critique_score, critique_metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            critique_id,
            job_id,
            chunk_index,
            critique_text,
            category,
            score,
            json.dumps(metadata) if metadata else None
        ))
        await db.commit()
    
    return critique_id

async def get_critiques(job_id: str) -> List[Dict[str, Any]]:
    """Get all critiques for a job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM job_critiques
        WHERE job_id = ?
        ORDER BY chunk_index
        """, (job_id,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# Metrics operations
async def add_metrics(job_id: str, metrics: Dict[str, Any]) -> str:
    """Add metrics for a job."""
    metric_id = str(uuid.uuid4())
    
    # Get job to access started_at and completed_at timestamps
    job = await get_job(job_id)
    
    # Extract known fields
    start_time = metrics.get("start_time")
    end_time = metrics.get("end_time")
    
    # Calculate duration based on job started_at and completed_at if available
    if job and job.get("started_at") and job.get("completed_at"):
        try:
            started_at = datetime.fromisoformat(job["started_at"])
            completed_at = datetime.fromisoformat(job["completed_at"])
            duration_seconds = (completed_at - started_at).total_seconds()
        except Exception as e:
            print(f"Error calculating duration: {e}")
            duration_seconds = end_time - start_time if end_time and start_time else None
    else:
        duration_seconds = end_time - start_time if end_time and start_time else None
    
    total_chunks = metrics.get("total_chunks")
    word_count_source = metrics.get("word_count_source")
    word_count_target = metrics.get("word_count_target")
    
    # Store remaining fields as JSON
    known_keys = ["start_time", "end_time", "total_chunks", "word_count_source", "word_count_target"]
    additional_metrics = {k: v for k, v in metrics.items() if k not in known_keys}
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO job_metrics (
            metric_id, job_id, start_time, end_time, duration_seconds,
            total_chunks, word_count_source, word_count_target, additional_metrics_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metric_id,
            job_id,
            start_time,
            end_time,
            duration_seconds,
            total_chunks,
            word_count_source,
            word_count_target,
            json.dumps(additional_metrics) if additional_metrics else None
        ))
        await db.commit()
    
    return metric_id

async def get_metrics(job_id: str) -> Optional[Dict[str, Any]]:
    """Get metrics for a job."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM job_metrics
        WHERE job_id = ?
        """, (job_id,))
        
        row = await cursor.fetchone()
        if not row:
            return None
        
        result = dict(row)
        
        # Parse additional_metrics_json if present
        if result.get("additional_metrics_json"):
            try:
                additional_metrics = json.loads(result["additional_metrics_json"])
                result.update(additional_metrics)
            except:
                pass
        
        return result

# Environment Variables Management
async def get_env_variables() -> List[Dict[str, Any]]:
    """Get all environment variables from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM env_variables
        ORDER BY key
        """)
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_env_variable(key: str) -> Optional[Dict[str, Any]]:
    """Get a specific environment variable by key."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM env_variables
        WHERE key = ?
        """, (key,))
        
        row = await cursor.fetchone()
        if not row:
            return None
        
        return dict(row)

async def set_env_variable(key: str, value: str, description: str = None) -> bool:
    """Set or update an environment variable."""
    now = datetime.now().isoformat()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if the key already exists
        cursor = await db.execute("SELECT id FROM env_variables WHERE key = ?", (key,))
        existing = await cursor.fetchone()
        
        if existing:
            # Update existing variable
            await db.execute("""
            UPDATE env_variables
            SET value = ?, description = ?, updated_at = ?
            WHERE key = ?
            """, (value, description, now, key))
        else:
            # Insert new variable
            await db.execute("""
            INSERT INTO env_variables (key, value, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """, (key, value, description, now, now))
        
        await db.commit()
    
    return True

async def delete_env_variable(key: str) -> bool:
    """Delete an environment variable."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM env_variables WHERE key = ?", (key,))
        await db.commit()
    
    return True

async def load_env_variables_to_os() -> None:
    """Load environment variables from database to os.environ."""
    env_vars = await get_env_variables()
    for var in env_vars:
        os.environ[var["key"]] = var["value"]

async def sync_env_file_with_db() -> None:
    """Sync .env file variables with the database."""
    # Get current variables from .env file
    from dotenv import dotenv_values
    env_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    
    if os.path.exists(env_file_path):
        env_file_vars = dotenv_values(env_file_path)
        
        # Add or update variables in the database
        for key, value in env_file_vars.items():
            await set_env_variable(key, value, f"Imported from .env file")

async def save_env_variables_to_file() -> bool:
    """Save environment variables from database to .env file."""
    try:
        env_vars = await get_env_variables()
        env_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
        
        # Read existing .env file to preserve comments and structure
        existing_lines = []
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as f:
                existing_lines = f.readlines()
        
        # Create a dictionary of existing variables with their line numbers
        existing_vars = {}
        for i, line in enumerate(existing_lines):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key = line.split('=', 1)[0].strip()
                existing_vars[key] = i
        
        # Update existing lines or prepare new lines to add
        new_vars = []
        for var in env_vars:
            key = var["key"]
            value = var["value"]
            if key in existing_vars:
                # Update existing variable
                line_num = existing_vars[key]
                existing_lines[line_num] = f"{key}={value}\n"
            else:
                # Add as new variable
                new_vars.append(f"{key}={value}\n")
        
        # Append new variables at the end
        if new_vars:
            if existing_lines and not existing_lines[-1].endswith('\n'):
                existing_lines[-1] += '\n'
            existing_lines.extend(new_vars)
        
        # Write back to .env file
        with open(env_file_path, 'w') as f:
            f.writelines(existing_lines)
        
        return True
    except Exception as e:
        print(f"Error saving environment variables to file: {e}")
        return False

# LLM Configuration Management
async def get_llm_configs() -> List[Dict[str, Any]]:
    """Get all LLM configurations."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM llm_config
        ORDER BY created_at DESC
        """)
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_default_llm_config() -> Optional[Dict[str, Any]]:
    """Get the default LLM configuration."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT * FROM llm_config
        WHERE is_default = 1
        LIMIT 1
        """)
        
        row = await cursor.fetchone()
        if not row:
            return None
        
        return dict(row)

async def save_llm_config(config: Dict[str, Any], set_as_default: bool = False) -> int:
    """Save a new LLM configuration."""
    now = datetime.now().isoformat()
    
    # Extract fields from config
    provider = config.get("provider", "")
    model = config.get("model", "")
    source_lang = config.get("source_lang", "")
    target_lang = config.get("target_lang", "")
    target_language_accent = config.get("target_language_accent", "")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # If setting as default, clear existing default
        if set_as_default:
            await db.execute("UPDATE llm_config SET is_default = 0")
        
        # Insert new config
        cursor = await db.execute("""
        INSERT INTO llm_config (
            provider, model, source_lang, target_lang, target_language_accent,
            is_default, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            provider, model, source_lang, target_lang, target_language_accent,
            1 if set_as_default else 0, now, now
        ))
        
        config_id = cursor.lastrowid
        await db.commit()
    
    return config_id

async def update_llm_config(config_id: int, config: Dict[str, Any], set_as_default: bool = False) -> bool:
    """Update an existing LLM configuration."""
    now = datetime.now().isoformat()
    
    # Extract fields from config
    provider = config.get("provider", "")
    model = config.get("model", "")
    source_lang = config.get("source_lang", "")
    target_lang = config.get("target_lang", "")
    target_language_accent = config.get("target_language_accent", "")
    
    async with aiosqlite.connect(DB_PATH) as db:
        # If setting as default, clear existing default
        if set_as_default:
            await db.execute("UPDATE llm_config SET is_default = 0")
        
        # Update config
        await db.execute("""
        UPDATE llm_config
        SET provider = ?, model = ?, source_lang = ?, target_lang = ?,
            target_language_accent = ?, is_default = ?, updated_at = ?
        WHERE id = ?
        """, (
            provider, model, source_lang, target_lang, target_language_accent,
            1 if set_as_default else 0, now, config_id
        ))
        
        await db.commit()
    
    return True

async def delete_llm_config(config_id: int) -> bool:
    """Delete an LLM configuration."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if this is the default config
        cursor = await db.execute("SELECT is_default FROM llm_config WHERE id = ?", (config_id,))
        row = await cursor.fetchone()
        
        if row and row[0]:
            # This is the default config, find another to set as default
            cursor = await db.execute("""
            SELECT id FROM llm_config
            WHERE id != ?
            ORDER BY created_at DESC
            LIMIT 1
            """, (config_id,))
            
            new_default = await cursor.fetchone()
            if new_default:
                await db.execute("UPDATE llm_config SET is_default = 1 WHERE id = ?", (new_default[0],))
        
        # Delete the config
        await db.execute("DELETE FROM llm_config WHERE id = ?", (config_id,))
        await db.commit()
    
    return True