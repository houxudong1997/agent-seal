"""Quick PG connectivity test + pre-benchmark cleanup."""
import os, sys

os.environ["AGENT_SEAL_DB_URL"] = "postgresql://audit:audit_dev@127.0.0.1:5432/agent_seal"

try:
    import psycopg2
    conn = psycopg2.connect("postgresql://audit:audit_dev@127.0.0.1:5432/agent_seal")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    count = cur.fetchone()[0]
    print(f"PG connected. events table has {count} rows.")
    
    # Check if schema exists
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'events' 
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    for name, dtype in cols:
        print(f"  {name}: {dtype}")
    
    # Clean up old benchmark data
    if count > 0:
        print(f"Cleaning {count} old benchmark rows...")
        cur.execute("DELETE FROM events")
        conn.commit()
        print("Cleaned.")
    
    conn.close()
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
