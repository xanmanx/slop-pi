#!/usr/bin/env python3
"""
Run a SQL migration against Supabase.

Usage:
    python backend/scripts/run_migration.py database/migrations/v2.5.0_grocery_lists.sql
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(Path(__file__).parent.parent / ".env")

import httpx


def run_migration(sql_file: str) -> None:
    """Execute a SQL migration file against Supabase."""

    # Get Supabase credentials from environment
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not service_role_key:
        print("Error: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        print("Make sure your .env file is configured correctly.")
        sys.exit(1)

    # Read the SQL file
    sql_path = Path(sql_file)
    if not sql_path.exists():
        print(f"Error: SQL file not found: {sql_file}")
        sys.exit(1)

    sql_content = sql_path.read_text()
    print(f"Running migration: {sql_file}")
    print(f"SQL length: {len(sql_content)} characters")
    print("-" * 50)

    # Execute via Supabase REST API (using the /rest/v1/rpc endpoint won't work for DDL)
    # Instead, we'll use the Supabase Management API or direct PostgreSQL connection
    # For simplicity, let's use the pg REST endpoint for raw SQL

    # The Supabase PostgREST doesn't support DDL, so we need to use the SQL endpoint
    # This requires the project ref and service role key

    # Extract project ref from URL (e.g., https://xxx.supabase.co -> xxx)
    import re
    match = re.match(r"https://([^.]+)\.supabase\.co", supabase_url)
    if not match:
        print(f"Error: Could not parse project ref from URL: {supabase_url}")
        sys.exit(1)

    project_ref = match.group(1)
    print(f"Project ref: {project_ref}")

    # Use the Supabase SQL API
    sql_url = f"https://{project_ref}.supabase.co/rest/v1/rpc/exec_sql"

    # Actually, Supabase doesn't have a direct SQL execution endpoint via REST
    # The proper way is to use the Supabase CLI or the dashboard
    # Let's try using the pg-meta API instead

    # Alternative: Use psycopg2 to connect directly
    try:
        import psycopg2
    except ImportError:
        print("Installing psycopg2-binary...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "psycopg2-binary"], check=True)
        import psycopg2

    # Get database URL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        # Construct from Supabase URL
        # Format: postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres
        db_password = os.getenv("SUPABASE_DB_PASSWORD") or os.getenv("DB_PASSWORD")
        if not db_password:
            print("Error: Missing DATABASE_URL or SUPABASE_DB_PASSWORD")
            print("Please set one of these in your .env file")
            print("\nAlternatively, you can run this SQL directly in the Supabase dashboard:")
            print("1. Go to your Supabase project")
            print("2. Click 'SQL Editor' in the sidebar")
            print("3. Paste the contents of the migration file")
            print("4. Click 'Run'")
            print(f"\nMigration file: {sql_file}")
            sys.exit(1)

        db_url = f"postgresql://postgres.{project_ref}:{db_password}@aws-0-us-west-1.pooler.supabase.com:6543/postgres"

    print(f"Connecting to database...")

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cursor = conn.cursor()

        print("Executing migration...")
        cursor.execute(sql_content)

        print("-" * 50)
        print("Migration completed successfully!")

        cursor.close()
        conn.close()

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/scripts/run_migration.py <sql_file>")
        print("Example: python backend/scripts/run_migration.py database/migrations/v2.5.0_grocery_lists.sql")
        sys.exit(1)

    run_migration(sys.argv[1])
