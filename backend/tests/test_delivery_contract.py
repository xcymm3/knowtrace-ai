from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_keeps_supabase_external_and_runs_four_local_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ("redis:", "api:", "worker:", "web:"):
        assert service in compose
    assert "postgres:" not in compose
    assert "REDIS_URL: redis://redis:6379" in compose
    assert "SUPABASE_SERVICE_ROLE_KEY" in compose


def test_delivery_files_include_repeatable_demo_and_all_migrations() -> None:
    seed = (ROOT / "supabase" / "seed" / "demo_commercelens.sql").read_text(encoding="utf-8")
    docker_guide = (ROOT / "docs" / "run-with-docker.md").read_text(encoding="utf-8")

    assert "on conflict (id) do update" in seed
    assert "knowledge_chunks" not in seed
    for migration in (
        "20260805000000_initial_commercelens_schema.sql",
        "20260805000001_create_research_assets_bucket.sql",
        "20260805000002_add_hybrid_retrieval.sql",
    ):
        assert migration in docker_guide
