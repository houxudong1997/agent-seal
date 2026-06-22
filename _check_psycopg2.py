"""Quick check: is psycopg2 importable? Prints YES/NO and version."""
import importlib.util
spec = importlib.util.find_spec("psycopg2")
if spec is None:
    print("psycopg2: NOT INSTALLED")
else:
    import psycopg2
    print(f"psycopg2: INSTALLED ({psycopg2.__version__})")
