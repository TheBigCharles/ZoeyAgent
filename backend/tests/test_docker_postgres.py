import os

import psycopg
import pytest


def test_docker_postgres_accepts_connections_and_has_pgvector() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set RUN_DOCKER_TESTS=1 to verify Docker Postgres communication.")

    postgres_url = os.getenv(
        "POSTGRES_URL",
        "postgresql://zoey:zoey@127.0.0.1:5432/zoey_agent",
    )

    with psycopg.connect(postgres_url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("select 1")
            assert cursor.fetchone() == (1,)

            cursor.execute("select extname from pg_extension where extname = 'vector'")
            assert cursor.fetchone() == ("vector",)
