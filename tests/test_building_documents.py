import pytest

from campus_notices.building_documents import brochure_link, goodell_image


def test_only_official_tenant_brochure_link_is_used_for_authenticated_request():
    url = "https://umass.sharepoint.com/:b:/s/AFWD/example?e=public-link-tag"
    html = f'<a href="{url}">Green Building Brochure</a>'
    assert brochure_link(html) == url
    with pytest.raises(ValueError, match="host"):
        brochure_link(html.replace("umass.sharepoint.com", "another.sharepoint.com"))
    with pytest.raises(ValueError, match="host"):
        brochure_link(html.replace("https://umass", "https://name:password@umass"))
    with pytest.raises(ValueError, match="link changed"):
        brochure_link("<p>No brochure in the new page</p>")


def test_chapel_uses_tour_guide_instead_of_short_brochure():
    guide = "https://umass.sharepoint.com/:b:/s/AFWD/guide?e=tag"
    brochure = "https://umass.sharepoint.com/:b:/s/AFWD/brochure?e=tag"
    html = (
        f'<a href="{brochure}">Green Building Brochure</a>'
        f'<a href="{guide}">Green Building Tour Guide</a>'
    )
    assert brochure_link(html, "Green Building Tour Guide") == guide


def test_goodell_rejects_login_html_and_preview_images():
    import pymupdf

    with pytest.raises(ValueError, match="JPEG"):
        goodell_image(b"<html>Sign in</html>")
    preview = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 48, 40))
    with pytest.raises(ValueError, match="dimensions"):
        goodell_image(preview.tobytes("jpeg"))


@pytest.mark.parametrize("public_succeeds", [True, False])
def test_expired_private_session_does_not_block_public_fetch_or_change_cached_time(
    tmp_path, monkeypatch, public_succeeds
):
    from contextlib import nullcontext

    import httpx
    import playwright.sync_api

    from campus_notices import building_documents as documents
    from campus_notices.cache import atomic_json

    old_time = "2025-01-01T00:00:00+00:00"
    old = [
        dict(building_id=k, observed_at=old_time, sha256="a" * 64)
        for k in ("old-chapel", "goodell")
    ]
    atomic_json(tmp_path / "data/private/building_documents/manifest.json", dict(records=old))

    def expired(*args):
        raise ValueError("Expired session")

    def response(request):
        if str(request.url) == documents.GOODELL_IMAGE:
            return httpx.Response(200 if public_succeeds else 503, content=b"NEW_PUBLIC_IMAGE")
        html = (
            '<a href="https://umass.sharepoint.com/:b:/s/AFWD/example">'
            'Green Building Brochure</a><a href="https://umass.sharepoint.com/:b:/s/AFWD/guide">'
            "Green Building Tour Guide</a>" + documents.GOODELL_IMAGE
        )
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(response))
    monkeypatch.setattr(documents.httpx, "Client", lambda **kw: client)
    monkeypatch.setattr(documents, "read_session", expired)
    monkeypatch.setattr(documents, "goodell_image", lambda raw: (5326, 4013))
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: nullcontext(None))
    result = documents.collect(tmp_path)
    rows = {r["building_id"]: r for r in result["records"]}
    assert rows["old-chapel"]["observed_at"] == old_time
    assert result["sources"]["old-chapel"]["mode"] == "cache"
    assert result["sources"]["goodell"]["mode"] == ("live" if public_succeeds else "cache")
    if public_succeeds:
        assert rows["goodell"]["observed_at"] != old_time
        assert (tmp_path / "data/private/building_documents/goodell.jpg").read_bytes() == (
            b"NEW_PUBLIC_IMAGE"
        )
    else:
        assert rows["goodell"]["observed_at"] == old_time
