from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_keeps_supabase_external_and_runs_four_local_services() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ("redis:", "api:", "worker:", "web:"):
        assert service in compose
    assert "postgres:" not in compose
    assert "REDIS_URL: redis://redis:6379" in compose
    assert "SUPABASE_SERVICE_ROLE_KEY" in compose


def test_delivery_files_describe_current_knowtrace_bootstrap() -> None:
    core_migration = (
        ROOT / "supabase" / "migrations" / "20260807000000_create_knowtrace_core.sql"
    ).read_text(encoding="utf-8")
    docker_guide = (ROOT / "docs" / "run-with-docker.md").read_text(encoding="utf-8")
    supabase_guide = (ROOT / "docs" / "supabase-setup.md").read_text(encoding="utf-8")

    assert "create extension if not exists vector" in core_migration
    assert "create or replace function public.set_updated_at" in core_migration
    for migration in (
        "20260807000000_create_knowtrace_core.sql",
        "20260807001000_add_parsed_document_status.sql",
        "20260808000000_add_personal_workspace_ownership.sql",
    ):
        assert migration in docker_guide
        assert migration in supabase_guide
