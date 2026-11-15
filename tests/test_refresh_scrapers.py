import subprocess

from scripts import refresh_scrapers


def test_public_refresh_still_runs_after_official_failure(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(args[3:])
        return subprocess.CompletedProcess(args, 1 if len(calls) == 1 else 0)

    monkeypatch.setattr(refresh_scrapers.subprocess, "run", run)
    storage, public = tmp_path / "session.json", tmp_path / "public.json"
    assert (
        refresh_scrapers.main(
            [
                "--rules-only",
                "--storage-state",
                str(storage),
                "--public-sources",
                str(public),
            ]
        )
        == 1
    )
    assert calls == [
        ["scripts.refresh_notices", "--rules-only", "--storage-state", str(storage)],
        ["scripts.refresh_reports", "--rules-only", "--sources", str(public)],
    ]
