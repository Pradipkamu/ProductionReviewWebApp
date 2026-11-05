import re
from pathlib import Path

from app.enums import UserRole
from app.page_access import PAGE_CATALOG, PAGE_KEYS, default_page_keys


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_page_catalog_has_unique_keys_and_paths():
    keys = [page["key"] for page in PAGE_CATALOG]
    paths = [page["path"] for page in PAGE_CATALOG]

    assert len(keys) == len(set(keys))
    assert len(paths) == len(set(paths))
    assert all(page.get("label") and page.get("path") for page in PAGE_CATALOG)


def test_every_frontend_navigation_page_is_in_role_visibility_catalog():
    source = (REPO_ROOT / "frontend" / "src" / "pageAccess.ts").read_text(encoding="utf-8")
    navigation_source = source.split("const legacyRestrictions", maxsplit=1)[0]
    navigation_keys = set(re.findall(r"\{key:'([^']+)'", navigation_source))

    missing = sorted(navigation_keys - set(PAGE_KEYS))
    assert not missing, f"Frontend pages missing from Page Visibility by Role: {missing}"


def test_new_intelligence_and_product_pages_are_available_to_role_configuration():
    expected = {
        "control_tower",
        "dispatch_intelligence",
        "capacity_intelligence",
        "operations_intelligence",
        "management_assistant",
        "product_master",
    }

    assert expected.issubset(set(PAGE_KEYS))
    assert expected.issubset(set(default_page_keys(UserRole.VIEW_ONLY)))
