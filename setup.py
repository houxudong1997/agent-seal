from setuptools import find_packages, setup

setup(
    name="agent-audit",
    version="1.0.0",
    description="Tamper-evident audit trail for AI agents — EU AI Act ready",
    author="Mr.H",
    license={"text": "MIT"},
    packages=find_packages(),
    include_package_data=True,
    package_data={"agent_audit": ["py.typed"]},
    install_requires=[
        "fastapi>=0.100",
        "uvicorn[standard]>=0.20",
        "sse-starlette>=1.0",
        "python-dotenv>=1.0",
        "sqlalchemy>=2.0",
        "cryptography>=43.0",
        "pyyaml>=6.0",
        "pydantic>=2.0",
        "alembic>=1.13",
        "prometheus_client>=0.14",
        "prometheus-fastapi-instrumentator>=6.0",
        "starlette>=1.3.1",
    ],
    extras_require={
        "postgresql": ["psycopg2-binary>=2.9"],
        "all": ["psycopg2-binary>=2.9"],
    },
    entry_points={
        "console_scripts": [
            "agent-audit=agent_audit.cli:main",
        ],
    },
    python_requires=">=3.11",
)
