import hashlib
import io
from pathlib import Path

from campus_notices.residence_plans import (
    _floor_tokens,
    _safe_file_path,
    extract_plan_metadata,
    reusable_plan,
)


def test_floor_tokens_support_grouped_and_basement_plans():
    assert _floor_tokens("354-03.04.06.07.09.10.pdf") == [
        "03",
        "04",
        "06",
        "07",
        "09",
        "10",
    ]
    assert _floor_tokens("Wheeler-BT.pdf") == ["basement"]
    assert _floor_tokens("Van Meter_2_3_010125.pdf") == ["02", "03"]


def test_floor_tokens_do_not_escape_or_include_extension():
    assert _floor_tokens("028-04 .pdf") == ["04"]


def test_safe_file_path_sanitizes_sharepoint_names():
    path = _safe_file_path(
        Path("tmp/test-residence"), "Southwest/..", "John Adams Hall", "plan?.pdf"
    )
    assert path.parent.name == "John_Adams_Hall"
    assert path.name == "plan_.pdf"
    assert Path(path).is_relative_to(Path("tmp/test-residence"))


def test_extract_plan_metadata_reads_source_text():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    metadata = extract_plan_metadata(output.getvalue())
    assert metadata["page_count"] == 1
    assert metadata["room_labels"] == []


def test_reuse_requires_unchanged_remote_version_and_intact_local_pdf(tmp_path):
    path = tmp_path / "plan.pdf"
    path.write_bytes(b"%PDF-unchanged")
    current = {"modified": "2026-01-01T00:00:00Z", "size_bytes": path.stat().st_size}
    old = dict(
        current, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), extracted={"pages": 1}
    )
    assert reusable_plan(current, old, path)
    assert not reusable_plan(dict(current, modified="2026-02-01T00:00:00Z"), old, path)
    path.write_bytes(b"%PDF-corrupted")
    assert not reusable_plan(current, old, path)
