import pytest

from campus_notices.building_documents import brochure_link


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
