import sys, os
print("Python:", sys.executable, sys.version)
try:
    import psycopg2
    print("psycopg2 OK:", psycopg2.__version__)
except ImportError as e:
    print("psycopg2 FAIL:", e)
# Check env
dsn = os.getenv("AGENT_SEAL_DB_URL", "NOT SET")
print("AGENT_SEAL_DB_URL:", dsn[:50] + "..." if len(dsn) > 50 else dsn)
