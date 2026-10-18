"""Linear-dark design tokens and the shared HTML shell for the web dashboard pages."""

from __future__ import annotations

from html import escape



#: The single source of truth for the dashboard's content width -- every
#: page shares this via BASE_CSS/page_shell rather than each page picking
#: its own value.
CONTENT_MAX_WIDTH = 1180

#: The single source of truth for the mobile breakpoint -- BASE_CSS and
#: ui.py both stack layouts and grow tap targets below this width, so a
#: page never flips to single-column at one width while its controls
#: still expect two.
MOBILE_BREAKPOINT = 640

#: Navigation order shared by every CareerOS page. The slug is the route
#: and the label is the word a person reads, which is why they differ for
#: jobs: M2 (CAREER-39, decision D10) renamed the section to My Jobs,
#: because a board holds the signed-in user's own postings and nobody
#: else's, while /jobs stays /jobs.
NAV_PAGES = (
    ("search", "Search"),
    ("experiences", "Experiences"),
    ("jobs", "My Jobs"),
    ("companies", "Companies"),
)

#: CSS custom properties for the Linear dark palette (shared with life-os; token
#: changes must be applied to BOTH repos).
CSS_VARS = """
:root {
  --bg-page: #08090a;
  --bg-panel: #0f1011;
  --bg-elevated: #191a1b;
  --text-primary: #f7f8f8;
  --text-secondary: #d0d6e0;
  --text-muted: #8a8f98;
  --text-faint: #62666d;
  --accent-indigo: #5e6ad2;
  --accent-violet: #7170ff;
  --link-external: var(--text-muted);
  --status-success: #27a644;
  --status-emerald: #10b981;
  --status-fail: #e5484d;
  --status-warn: #f5a623;
  --border-standard: rgba(255,255,255,0.08);
  --border-subtle: rgba(255,255,255,0.05);
  --card-bg: rgba(255,255,255,0.03);
  --card-bg-elevated: rgba(255,255,255,0.05);
}
"""

FONT_LINKS = ""

#: Shared base styles every page starts from; pages layer page-specific CSS on
#: top. The max-width token is substituted in (rather than an f-string) so
#: the many literal CSS braces below don't need doubling.
BASE_CSS = """
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg-page);
  color: var(--text-primary);
  max-width: __CONTENT_MAX_WIDTH__px;
  margin-left: auto;
  margin-right: auto;
  font-family: 'Inter', -apple-system, Helvetica, Arial, sans-serif;
  font-feature-settings: 'cv01', 'ss03';
  font-weight: 400;
}
.mono { font-family: 'JetBrains Mono', monospace; }
.page-nav { display: flex; gap: 24px; margin-bottom: 24px; font-size: 13px; }
.page-nav a { color: var(--text-secondary); text-decoration: none; }
.page-nav a:hover { color: var(--accent-violet); }
.page-nav a.active { color: var(--text-primary); font-weight: 590; }
.page { padding: 28px 32px; }
h1, h2, h3 { margin: 0; font-weight: 590; letter-spacing: -0.02em; }
h1 { font-size: 22px; }
h2 { font-size: 15px; color: var(--text-secondary); font-weight: 510; }
.muted { color: var(--text-muted); }
.faint { color: var(--text-faint); }
.card {
  background: var(--card-bg);
  border: 1px solid var(--border-standard);
  border-radius: 12px;
  padding: 16px 18px;
}
.chip {
  display: inline-block;
  min-width: 20px;
  height: 20px;
  border-radius: 5px;
}
a { color: var(--accent-violet); }
a.external { color: var(--link-external); }
a.external::after { content: ' \\2197'; display: inline-block; }
.goal-annotation { color: var(--text-faint); font-size: 0.85em; font-weight: 400; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.job-detail-header { flex-direction: column; gap: 8px; overflow-wrap: anywhere; }
.job-detail-header > * { max-width: 100%; }
.stat-row { display: flex; gap: 22px; font-size: 13px; color: var(--text-secondary); align-items: baseline; }
.stat-row b { color: var(--text-primary); font-weight: 510; }
.status-chip {
  display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 10.5px; font-weight: 510;
  background: rgba(255,255,255,0.06);
}
.filter-row { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; font-size: 12.5px; }
.filter-btn {
  background: var(--card-bg); border: 1px solid var(--border-standard); color: var(--text-secondary);
  border-radius: 6px; padding: 4px 10px; font-size: 12px; cursor: pointer; font-family: inherit;
}
.filter-btn.active { background: var(--accent-indigo); border-color: var(--accent-indigo); color: var(--text-primary); }
.icon-legend { display: flex; gap: 16px; margin-top: 8px; }
.src-icon { font-size: 11px; }
.chart-title-row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.app-header { display: flex; align-items: center; gap: 14px; margin-bottom: 32px; }
.app-header .logout { margin-left: auto; }
.wordmark { color: var(--text-primary); font-size: 20px; font-weight: 590; text-decoration: none; letter-spacing: -0.02em; }
.page-nav { flex-wrap: wrap; gap: 12px 24px; border-bottom: 1px solid var(--border-standard); padding-bottom: 16px; }
.page-nav a.active { text-decoration: underline; text-decoration-color: var(--accent-indigo); text-underline-offset: 17px; }
a:focus-visible { outline: 2px solid var(--accent-indigo); outline-offset: 5px; border-radius: 2px; }
.empty-state { padding: 32px; min-height: 180px; }
.empty-state p { font-size: 14px; line-height: 1.7; margin: 12px 0 0; max-width: 640px; }
@media (max-width: __MOBILE_BREAKPOINT__px) {
  html, body { font-size: 17px; }
  h1 { font-size: 24px; }
  .page { padding: 24px 18px; }
  .empty-state { padding: 24px; }
  .page-nav a.active { text-underline-offset: 5px; }
  .page-nav a { min-height: 44px; display: inline-flex; align-items: center; }
  table { display: block; max-width: 100%; overflow-x: auto; }
}
""".replace("__CONTENT_MAX_WIDTH__", str(CONTENT_MAX_WIDTH)).replace("__MOBILE_BREAKPOINT__", str(MOBILE_BREAKPOINT))

#: Section 5: one shared, reusable scrollbar style used app-wide. Scoped to
#: the selectors that already scroll (.kanban, the mobile table overflow
#: rule) plus an opt-in .scroll-thin class for any future overflow surface,
#: rather than a blanket "*" override that would block a later per-surface
#: exception. Every color below reuses an existing CSS_VARS token.
SCROLLBAR_CSS = """
.scroll-thin, .kanban, table {
  scrollbar-width: thin;
  scrollbar-color: var(--border-standard) transparent;
}
.scroll-thin::-webkit-scrollbar, .kanban::-webkit-scrollbar, table::-webkit-scrollbar {
  height: 8px;
  width: 8px;
}
.scroll-thin::-webkit-scrollbar-track, .kanban::-webkit-scrollbar-track, table::-webkit-scrollbar-track {
  background: transparent;
}
.scroll-thin::-webkit-scrollbar-thumb, .kanban::-webkit-scrollbar-thumb, table::-webkit-scrollbar-thumb {
  background-color: var(--border-standard);
  border-radius: 8px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.scroll-thin::-webkit-scrollbar-thumb:hover, .kanban::-webkit-scrollbar-thumb:hover, table::-webkit-scrollbar-thumb:hover {
  background-color: var(--text-faint);
}
.scroll-thin::-webkit-scrollbar-thumb:active, .kanban::-webkit-scrollbar-thumb:active, table::-webkit-scrollbar-thumb:active {
  background-color: var(--text-muted);
}
"""

def fmt1(value: float) -> str:
    """Round a displayed float to at most one decimal without trailing zeros."""
    return f"{round(value, 1):g}"


def nav_html(current_page: str) -> str:
    """The shared nav bar, with ``current_page`` (a slug from NAV_PAGES) highlighted.

    JOZ-283: the Search page's own URL is ``/``, not ``/search``. Its
    slug no longer doubles as its own path segment, the one exception in
    NAV_PAGES.
    """
    active_class = " class='active' aria-current='page'"
    links = "".join(
        f"<a href='{'/' if slug == 'search' else f'/{slug}'}'{active_class if slug == current_page else ''}>{label}</a>"
        for slug, label in NAV_PAGES
    )
    return f"<nav class='page-nav' aria-label='Main'>{links}</nav>"


#: The logout affordance a page behind the login gate carries (M1), in the
#: chrome every page already shows rather than as a settings page that
#: would exist for one action. A form and not a link, because logging out
#: changes state, and it needs no JavaScript.
LOGOUT_FORM = ("<form class='logout' method='post' action='/logout'>"
               "<button type='submit'>Log out</button></form>")


def page_shell(title: str, current_page: str, body: str, extra_css: str = "",
               logout: bool = False, nav: bool = True) -> str:
    """Wrap already-escaped page body HTML in the shared Linear-dark head/shell.

    ``title`` is escaped for the document title. ``current_page`` is a slug from NAV_PAGES, highlighted in the nav.
    ``logout`` adds the logout affordance; it is off by default so the one
    page reachable without a session does not offer to end one.
    ``nav`` drops the navigation and the wordmark link for the same page:
    every link they offer leads back to the login page until there is a
    session, so showing them would be chrome standing for nothing.
    """
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} · CareerOS</title>"
        f"{FONT_LINKS}"
        f"<style>{CSS_VARS}{BASE_CSS}{SCROLLBAR_CSS}{extra_css}</style>"
        "</head><body>"
        "<div class='page'><header class='app-header'>"
        + ("<a class='wordmark' href='/'>CareerOS</a>" if nav
           else "<span class='wordmark'>CareerOS</span>")
        + f"{LOGOUT_FORM if logout else ''}</header>"
        + f"{nav_html(current_page) if nav else ''}<main>{body}</main></div>"
        "</body></html>"
    )
