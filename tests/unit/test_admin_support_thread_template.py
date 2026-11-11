from pathlib import Path


# Проверяет, что длинные сообщения в админке раскрываются без public URL.
def test_admin_support_template_expandable_and_private_photos():
    html = Path("src/templates/site/admin/support.html").read_text(encoding="utf-8")
    assert "data-support-message-toggle" in html
    assert "Развернуть" in html
    assert "data-support-lightbox" in html
    assert "data-support-photo-link" in html
    assert "/support/tickets/{{ detail.id }}/attachments/{{ att.id }}/file" in html
    assert "public_url" not in html
    assert "/media/support" not in html
    assert "is-collapsed" in html
    assert 'id="admin-support-delete-btn"' in html
    assert "data-support-delete-checkbox" in html
    assert "data-support-select-all" in html


# Проверяет, что JS вешает toggle/lightbox на тред поддержки.
def test_admin_support_js_toggles_long_messages():
    js = Path("src/static/site/js/admin.js").read_text(encoding="utf-8")
    assert "function initSupportThread(" in js
    assert "  initSupportThread(root);" in js
    assert "Свернуть" in js
    assert "function initAdminSupportBulkDelete(" in js
    assert "function adminSupportDeleteSelected(" in js
    assert "/internal/admin/support/delete-selected" in js
