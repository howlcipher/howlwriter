"""
Automated Responsive Regression Tests for HowlWriter Documentation Site.
Verifies that docs/index.html has zero document-level or uncontained element-level
horizontal overflow across mobile, tablet, and desktop viewports, specifically guarding
against minmax(320px, 1fr) regressions on narrow viewports (<= 365px).
"""

import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import pytest
from playwright.sync_api import sync_playwright

DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'docs'))

VIEWPORTS = [
    (320, 568, '320px_small_phone'),
    (340, 600, '340px_boundary_phone'),
    (360, 640, '360px_android_phone'),
    (375, 667, '375px_iphone'),
    (390, 844, '390px_modern_iphone'),
    (430, 932, '430px_large_phone'),
    (768, 1024, '768px_tablet'),
    (1280, 800, '1280px_desktop'),
]

class QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOCS_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

@pytest.fixture(scope="module")
def docs_server():
    server = HTTPServer(('127.0.0.1', 8779), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield 'http://127.0.0.1:8779/'
    server.shutdown()

@pytest.mark.parametrize("width,height,name", VIEWPORTS)
def test_howlwriter_responsive_viewports(docs_server, width, height, name):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': height})
        console_errors = []
        page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)

        page.goto(docs_server, wait_until='networkidle')

        diag = page.evaluate('''() => {
            const doc = document.documentElement;
            const cw = doc.clientWidth;
            const sw = doc.scrollWidth;
            
            const overflowing = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.closest('#eco-drawer') || el.id === 'eco-drawer') return;
                if (el.closest('#eco-drawer-overlay') || el.id === 'eco-drawer-overlay') return;
                if (el.classList.contains('skip-link')) return;
                
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
                
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) return;
                
                if (r.right > cw + 1.5 || r.left < -1.5) {
                    const scrollChild = el.closest('pre, .table-wrap, [style*="overflow-x: auto"]');
                    if (!scrollChild || scrollChild === el) {
                        overflowing.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id,
                            className: el.className,
                            right: Math.round(r.right),
                            cw: cw
                        });
                    }
                }
            });
            return {
                scrollWidth: sw,
                clientWidth: cw,
                hasOverflow: sw > cw,
                uncontained: overflowing
            };
        }''')

        page.close()
        browser.close()

        assert not diag['hasOverflow'], f"Document overflow at {width}px: scrollWidth {diag['scrollWidth']} > clientWidth {diag['clientWidth']}"
        assert len(diag['uncontained']) == 0, f"Uncontained elements at {width}px: {diag['uncontained']}"
        assert len(console_errors) == 0, f"Console errors at {width}px: {console_errors}"
