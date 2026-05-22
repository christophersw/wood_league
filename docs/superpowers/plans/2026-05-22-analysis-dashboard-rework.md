# Analysis Dashboard Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the admin worker dashboard, scheduling page, and queue pages into a single `admin/analysis/` page with responsive two-column table rows, and delete the queue pages.

**Architecture:** A new `overview` view (in `analysis/views_schedule.py`, where the schedule context already lives) renders one template `analysis/overview.html`. The dashboard sections remain HTMX-polled partials (unchanged views, repathed URLs, unchanged URL *names*); the scheduling sections are server-rendered from the same context the old scheduling page used. The legacy worker-dashboard shell, scheduling shell, and all queue pages/views/templates/tests are removed.

**Tech Stack:** Django 5, HTMX, Tailwind v4 (compiled `main.css` → committed `tailwind.css`), pytest.

---

## Conventions for every task

- Work from the repo root `/Users/christopherwebster/Projects/wood_league`.
- App code lives under `services/app/`. Run Python/tests from there with the venv:
  `cd services/app && source .venv/bin/activate`.
- Run a single test: `pytest <path>::<test> -v`. Run the analysis suite:
  `pytest analysis/tests/ -q`.
- A per-edit quality-gate hook hard-fails on ruff/mypy/pytest and complexity.
  After editing any `.py`, expect the gate to run; keep imports clean (remove
  now-unused imports) or ruff will fail.
- After editing a `.py` file also run `bandit -ll <file>` and fix Medium/High.
- Branch is already `issue/200-rework-analysis-dashboard`.

---

## File Structure

**Created:**
- `services/app/templates/analysis/overview.html` — the single combined page.

**Modified:**
- `services/app/analysis/dashboard_helpers.py` — add `game_label_short`.
- `services/app/templates/analysis/_dash_workers.html` — show short gameId.
- `services/app/static/css/main.css` — add `.panel-grid--even`.
- `services/app/static/css/tailwind.css` — rebuilt artifact.
- `services/app/analysis/views_schedule.py` — `scheduling_page` → `overview`; redirects → `analysis:overview`.
- `services/app/analysis/urls.py` — add `overview` route; repath dashboard partials; remove queue/dashboard/schedule-shell/diagnostics routes.
- `services/app/analysis/partial_urls.py` — drop `analysis/queue/` entry.
- `services/app/analysis/views.py` — remove `queues_summary`, `overview_partial`, `_queue_context`, `_engine_metric` + now-unused imports.
- `services/app/analysis/views_dashboard.py` — remove the `dashboard` shell view.
- `services/app/templates/base.html` — nav link → `analysis:overview`.
- Tests: rework `test_views_schedule.py`, `test_dashboard_view.py`, `test_dashboard_helpers.py`.

**Deleted:**
- `services/app/analysis/views_queue.py`
- Templates: `dashboard.html`, `scheduling.html`, `queues_summary.html`, `queue.html`, `status.html`, `_overview_cards.html`, `_workers_panel.html`, `_queue_action_result.html`, `_queue_active.html`, `_queue_partial.html`, `_queue_pending_table.html`, `_queue_recent.html`.
- Tests: `test_views_queue.py`, `test_views_queue_reorder.py`, `test_views_queues_summary.py`, `test_status_overview.py`.

**Kept (verified, out of scope):** `runpod_start_view` + its route + `test_runpod_admin.py` (an action endpoint, not a page; its only UI trigger was on the removed queues page but RunPod removal is out of scope).

---

## Task 1: Truncate worker-card gameId to first 6 chars

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py` (`_worker_recent_games`, ~line 542)
- Modify: `services/app/templates/analysis/_dash_workers.html` (recent-games `<li>`, ~lines 98-103)
- Test: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing test**

Add after the existing `test_worker_recent_games_newest_first_limited`
(around line 556) in `services/app/analysis/tests/test_dashboard_helpers.py`:

```python
@pytest.mark.django_db
def test_worker_recent_games_short_label_truncates_id():
    """game_label_short is '#' + first 6 chars of the (long) game id."""
    long_id = "1234567890abcdef"  # 16 chars, like a chess.com game id
    g = _make_wem_game(long_id)
    AnalysisJob.objects.create(
        game=g, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED,
        worker_id="wr-short", duration_seconds=1.0,
        completed_at=timezone.now(),
    )
    rows = _worker_recent_games("wr-short", limit=10)
    assert rows[0]["game_label"] == f"#{g.id}"
    assert rows[0]["game_label_short"] == f"#{g.id[:6]}"
    assert len(rows[0]["game_label_short"]) == 7  # '#' + 6 chars
```

Note: `_make_wem_game(suffix)` builds a Game whose `id` includes `suffix`;
confirm the created `g.id` here so the assertion uses the real id. If
`_make_wem_game` prefixes/suffixes the id, assert against `g.id[:6]` (it
already does), which stays correct regardless of the exact id string.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && source .venv/bin/activate && pytest analysis/tests/test_dashboard_helpers.py::test_worker_recent_games_short_label_truncates_id -v`
Expected: FAIL with `KeyError: 'game_label_short'`.

- [ ] **Step 3: Add `game_label_short` in the helper**

In `services/app/analysis/dashboard_helpers.py`, inside `_worker_recent_games`,
change the appended dict (currently starting at the `"game_label"` key):

```python
        out.append({
            "game_label": f"#{job.game_id}",
            "game_label_short": f"#{str(job.game_id)[:6]}",
            "game_url": url,
            "engine": job.engine,
            "duration_seconds": (
                round(job.duration_seconds, 1)
                if job.duration_seconds is not None else None
            ),
            "completed_at": job.completed_at,
        })
```

Also update the docstring `Returns:` line to mention `game_label_short`
(``"#<id[:6]>"``).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest analysis/tests/test_dashboard_helpers.py -q`
Expected: PASS (both recent-games tests).

- [ ] **Step 5: Update the worker-card template**

In `services/app/templates/analysis/_dash_workers.html`, replace the
recent-games list item (around lines 98-103) so the short label shows with the
full id on hover:

```html
                {% for g in card.recent_games %}
                  <li>
                    {% if g.game_url %}<a href="{{ g.game_url }}" title="{{ g.game_label }}">{{ g.game_label_short }}</a>{% else %}<span title="{{ g.game_label }}">{{ g.game_label_short }}</span>{% endif %}
                    <span class="dash-recent-list__meta">{{ g.engine }} · {% if g.duration_seconds is not None %}{{ g.duration_seconds }}s{% else %}—{% endif %}</span>
                  </li>
                {% endfor %}
```

- [ ] **Step 6: bandit + commit**

```bash
cd services/app && source .venv/bin/activate
bandit -ll analysis/dashboard_helpers.py
git add analysis/dashboard_helpers.py templates/analysis/_dash_workers.html analysis/tests/test_dashboard_helpers.py
git commit -m "feat(#200): truncate worker-card gameId to 6 chars

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `.panel-grid--even` and rebuild Tailwind

**Files:**
- Modify: `services/app/static/css/main.css` (the `@media (min-width: 880px)` block, ~lines 563-565)
- Modify: `services/app/static/css/tailwind.css` (rebuilt)

- [ ] **Step 1: Confirm Node 22**

Run: `node --version`
Expected: `v22.x`. If not v22, use an nvm-selected Node 22 (or `npx node@22`)
for Step 3 — the build output is byte-sensitive to the Node major and CI's
staleness guard fails otherwise.

- [ ] **Step 2: Add the even-split modifier**

In `services/app/static/css/main.css`, extend the existing breakpoint block so
it reads:

```css
  @media (min-width: 880px) {
    .panel-grid--2 { grid-template-columns: 1fr 1.4fr; }
    .panel-grid--even { grid-template-columns: 1fr 1fr; }
  }
```

- [ ] **Step 3: Rebuild the served stylesheet**

Run: `services/app/bin/build_tailwind.sh`
Expected: ends with `Done: static/css/tailwind.css`.

- [ ] **Step 4: Verify the class made it into the artifact**

Run: `grep -c "panel-grid--even" services/app/static/css/tailwind.css`
Expected: `1` (or more).

- [ ] **Step 5: Commit**

```bash
cd services/app
git add static/css/main.css static/css/tailwind.css
git commit -m "feat(#200): add .panel-grid--even responsive 50/50 grid

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Build the combined `overview` page (additive + repoint)

This task adds the new page and points everything that referenced the old
scheduling page at it. The worker-dashboard shell and queue pages are left
intact here and removed in Task 4, so the tree stays working throughout.

**Files:**
- Create: `services/app/templates/analysis/overview.html`
- Modify: `services/app/analysis/views_schedule.py`
- Modify: `services/app/analysis/urls.py`
- Modify: `services/app/templates/base.html`
- Test: `services/app/analysis/tests/test_views_schedule.py`

- [ ] **Step 1: Rework the schedule tests to target `overview`**

Replace the whole body of `services/app/analysis/tests/test_views_schedule.py`
gating class and the two `reverse("analysis:scheduling")` calls so they use the
new name. Apply these edits:

In `SchedulingGatingTests`, change all three `reverse("analysis:scheduling")` to
`reverse("analysis:overview")`.

In `test_recent_and_future_tables_render`, change
`reverse("analysis:scheduling")` to `reverse("analysis:overview")`.

Add a new test at the end of `SchedulingActionsTests`:

```python
    def test_run_once_redirects_to_overview(self):
        """Run-once 302s back to the combined overview page."""
        resp = self.client.post(reverse("analysis:run_once"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("analysis:overview"))
```

- [ ] **Step 2: Run the schedule tests to verify they fail**

Run: `cd services/app && source .venv/bin/activate && pytest analysis/tests/test_views_schedule.py -q`
Expected: FAIL — `NoReverseMatch: 'overview' not found`.

- [ ] **Step 3: Rename the view and repoint redirects**

In `services/app/analysis/views_schedule.py`:

Change `_render_page` to render the new template:

```python
    return render(request, "analysis/overview.html", ctx, status=status)
```

Rename the page view (replace `scheduling_page`):

```python
@_admin_login_required
@require_GET
def overview(request: HttpRequest) -> HttpResponse:
    """Render the combined analysis page (dashboard + scheduling).

    The worker-dashboard sections are HTMX-polled partials, so this view
    only supplies the scheduling context; the dashboard data loads via
    HTMX after the shell renders.
    """
    return _render_page(request, RecurringAnalysisScheduleForm())
```

Change every `return redirect("analysis:scheduling")` in this file (in
`rule_create`, `rule_edit`, `rule_delete`, `rule_toggle`, `run_once`, `rerun`)
to `return redirect("analysis:overview")`.

- [ ] **Step 4: Add the route**

In `services/app/analysis/urls.py`, add the combined-page route. Put it with the
scheduling block; reference `views_schedule.overview`:

```python
    # Combined analysis page (dashboard + scheduling) — #200.
    path("analysis/", views_schedule.overview, name="overview"),
```

Leave the existing `schedule/` shell route in place for now (removed in Task 4)
so nothing else breaks mid-task.

- [ ] **Step 5: Create `overview.html`**

Create `services/app/templates/analysis/overview.html` with the full combined
layout. Dashboard partials are HTMX wrappers (URL names unchanged); scheduling
sections are copied from `scheduling.html` and arranged into the new rows:

```html
{% extends "base.html" %}
{% comment %}
  Title: overview.html — combined analysis page (#200)
  Description: Single admin page at /admin/analysis/. Top half stacks the
      worker-dashboard HTMX sections (banner, workers, recently completed
      full width; queues+throughput and failures+logs in 50/50 rows).
      Bottom half is the scheduling admin (run-once + new-rule forms,
      recurring rules + future runs in a 50/50 row, recent runs full width).
      Replaces dashboard.html and scheduling.html.
  Changelog:
      2026-05-22 (#200): Initial — merge of dashboard + scheduling.
{% endcomment %}
{% block title %}Analysis · Wood League Chess{% endblock %}
{% block content %}

<div class="page-hero">
  <div>
    <h1>Analysis</h1>
    <p class="page-hero-sub">Worker health, queue depth, throughput, and scheduling.</p>
  </div>
</div>

{# ── Worker dashboard (HTMX-polled) ───────────────────────────────────── #}
<div id="dash-banner"
     hx-get="{% url 'analysis:dash_banner' %}"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="loading-pip">Loading banner…</span></div>
</div>

<div id="dash-workers"
     hx-get="{% url 'analysis:dash_workers' %}"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="loading-pip">Loading workers…</span></div>
</div>

<div id="dash-recent"
     hx-get="{% url 'analysis:dash_recent' %}"
     hx-trigger="load, every 30s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="loading-pip">Loading recently completed…</span></div>
</div>

<div class="panel-grid panel-grid--even">
  <div id="dash-queues"
       hx-get="{% url 'analysis:dash_queues' %}"
       hx-trigger="load, every 10s"
       hx-swap="innerHTML">
    <div class="pg-section"><span class="loading-pip">Loading queues…</span></div>
  </div>
  <div id="dash-throughput"
       hx-get="{% url 'analysis:dash_throughput' %}"
       hx-trigger="load, every 60s"
       hx-swap="innerHTML">
    <div class="pg-section"><span class="loading-pip">Loading throughput…</span></div>
  </div>
</div>

<div class="panel-grid panel-grid--even">
  <div id="dash-failures"
       hx-get="{% url 'analysis:dash_failures' %}"
       hx-trigger="load, every 60s"
       hx-swap="innerHTML">
    <div class="pg-section"><span class="loading-pip">Loading failures…</span></div>
  </div>
  <div id="dash-logs"
       hx-get="{% url 'analysis:dash_logs' %}"
       hx-trigger="load, every 30s"
       hx-swap="innerHTML">
    <div class="pg-section"><span class="loading-pip">Loading worker logs…</span></div>
  </div>
</div>

{# ── Scheduling ───────────────────────────────────────────────────────── #}
<div class="page-hero" style="margin-top:2.5rem;">
  <div>
    <h2 style="margin:0;">Scheduling</h2>
    <p class="page-hero-sub">Recurring rules · one-off runs · history</p>
  </div>
  <div class="page-hero-meta">
    {{ rules|length }} rule{{ rules|length|pluralize }} · {{ future_rows|length }} planned
  </div>
</div>

<div class="panel-grid panel-grid--2">

  <section class="filter-panel" aria-labelledby="run-once-title">
    <h2 class="filter-panel__title" id="run-once-title">Run once now</h2>
    <p class="filter-panel__caption">Launches a single vast.ai instance on the next reconcile tick.</p>

    <form method="post" action="{% url 'analysis:run_once' %}">
      {% csrf_token %}
      <div class="wc-form-grid wc-form-grid--2">
        <div>
          <label for="run-once-max-jobs" class="wc-label">Max jobs</label>
          <input type="number"
                 id="run-once-max-jobs"
                 name="max_jobs"
                 min="1"
                 step="1"
                 placeholder="default"
                 class="wc-input">
        </div>
        <div style="align-self:end;">
          <button type="submit" class="wc-btn wc-btn-solid" style="width:100%;text-align:center;">
            Trigger run
          </button>
        </div>
      </div>
      <p style="font-family:var(--font-mono);font-size:.58rem;letter-spacing:.08em;color:var(--color-slate);margin:.35rem 0 0;">
        ≈ 2 jobs per game (1 lc0 + 1 Stockfish). Leave blank to use the deploy default.
      </p>
    </form>
  </section>

  <section class="filter-panel" aria-labelledby="new-rule-title">
    <h2 class="filter-panel__title" id="new-rule-title">New recurring rule</h2>
    <p class="filter-panel__caption">Cron expression — preview updates as you type.</p>

    <form method="post" action="{% url 'analysis:rule_create' %}">
      {% csrf_token %}
      {{ form.as_p }}
      <div id="cron-preview"
           hx-get="{% url 'analysis:schedule_preview' %}"
           hx-trigger="load, change from:#id_crontab, change from:#id_timezone"
           hx-include="#id_crontab,#id_timezone"
           style="font-family:var(--font-mono);font-size:.7rem;color:var(--color-peat);margin:.5rem 0 1rem;">
      </div>
      <button type="submit" class="wc-btn wc-btn-solid">Create rule</button>
    </form>
  </section>

</div>

<div class="panel-grid panel-grid--even">

  {# ── Recurring rules ──────────────────────────────────────────────── #}
  <section class="pg-section">
    <div class="pg-head">
      <span class="pg-title">Recurring rules</span>
      <span class="pg-caption">{{ rules|length }} total</span>
    </div>

    <table class="wc-table wc-table--zebra">
      <thead>
        <tr>
          <th>Name</th>
          <th>Crontab</th>
          <th>TZ</th>
          <th>Max jobs</th>
          <th>Enabled</th>
          <th style="width:1%;">Actions</th>
        </tr>
      </thead>
      <tbody>
      {% for r in rules %}
        <tr>
          <td>{{ r.name }}</td>
          <td><code>{{ r.crontab }}</code></td>
          <td>{{ r.timezone }}</td>
          <td>{{ r.max_jobs|default:"—" }}</td>
          <td>
            {% if r.enabled %}
              <span class="wc-badge" style="color:var(--color-forest);">On</span>
            {% else %}
              <span class="wc-badge" style="color:var(--color-slate);">Off</span>
            {% endif %}
          </td>
          <td>
            <div class="wc-btn-row">
              <form method="post" action="{% url 'analysis:rule_toggle' r.pk %}" style="margin:0;">
                {% csrf_token %}
                <button type="submit" class="wc-btn wc-btn--sm">
                  {{ r.enabled|yesno:"Disable,Enable" }}
                </button>
              </form>
              <form method="post" action="{% url 'analysis:rule_delete' r.pk %}" style="margin:0;"
                    onsubmit="return confirm('Delete rule “{{ r.name|escapejs }}”?');">
                {% csrf_token %}
                <button type="submit" class="wc-btn wc-btn--sm wc-btn-ghost">Delete</button>
              </form>
            </div>

            <details class="wc-row-edit">
              <summary class="wc-row-edit__summary">Edit</summary>
              <form method="post" action="{% url 'analysis:rule_edit' r.pk %}" style="margin:.5rem 0 0;">
                {% csrf_token %}
                <div class="wc-form-grid wc-form-grid--3">
                  <div>
                    <label class="wc-label" for="edit-name-{{ r.pk }}">Name</label>
                    <input type="text" id="edit-name-{{ r.pk }}" name="name" value="{{ r.name }}" class="wc-input wc-input--sm">
                  </div>
                  <div>
                    <label class="wc-label" for="edit-cron-{{ r.pk }}">Crontab</label>
                    <input type="text" id="edit-cron-{{ r.pk }}" name="crontab" value="{{ r.crontab }}" class="wc-input wc-input--sm">
                  </div>
                  <div>
                    <label class="wc-label" for="edit-tz-{{ r.pk }}">Timezone</label>
                    <input type="text" id="edit-tz-{{ r.pk }}" name="timezone" value="{{ r.timezone }}" class="wc-input wc-input--sm">
                  </div>
                  <div>
                    <label class="wc-label" for="edit-mj-{{ r.pk }}">Max jobs</label>
                    <input type="number" id="edit-mj-{{ r.pk }}" name="max_jobs" value="{{ r.max_jobs|default_if_none:'' }}" class="wc-input wc-input--sm">
                  </div>
                </div>
                {% if r.enabled %}
                  <input type="hidden" name="enabled" value="on">
                {% endif %}
                <button type="submit" class="wc-btn wc-btn--sm wc-btn-solid">Save</button>
              </form>
            </details>
          </td>
        </tr>
      {% empty %}
        <tr><td colspan="6" style="color:var(--color-slate);font-style:italic;">No rules yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </section>

  {# ── Future planned runs ──────────────────────────────────────────── #}
  <section class="pg-section">
    <div class="pg-head">
      <span class="pg-title">Future planned runs</span>
      <span class="pg-caption">{{ future_rows|length }} upcoming</span>
    </div>

    <table class="wc-table wc-table--zebra">
      <thead>
        <tr>
          <th>When</th>
          <th>Source</th>
          <th>Max jobs</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
      {% for row in future_rows %}
        <tr>
          <td>{{ row.when }}</td>
          <td>{{ row.source }}</td>
          <td>{{ row.max_jobs|default:"—" }}</td>
          <td>{{ row.status }}</td>
        </tr>
      {% empty %}
        <tr><td colspan="4" style="color:var(--color-slate);font-style:italic;">Nothing scheduled.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </section>

</div>

{# ── Recent runs ──────────────────────────────────────────────────────── #}
<section class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Recent runs</span>
    <span class="pg-caption">{{ recent_rows|length }} shown</span>
  </div>

  <table class="wc-table wc-table--zebra">
    <thead>
      <tr>
        <th>When</th>
        <th>Source</th>
        <th>Status</th>
        <th>Instance</th>
        <th>$/hr</th>
        <th style="width:1%;"></th>
      </tr>
    </thead>
    <tbody>
    {% for row in recent_rows %}
      <tr{% if row.failed %} class="text-crimson"{% endif %}>
        <td>{{ row.when }}</td>
        <td>{{ row.source }}</td>
        <td>{{ row.status }}</td>
        <td>{{ row.instance_id|default:"—" }}</td>
        <td>{{ row.offer_dph|default:"—" }}</td>
        <td>
          <form method="post" action="{% url 'analysis:rerun' row.id %}" style="margin:0;">
            {% csrf_token %}
            <button type="submit" class="wc-btn wc-btn--sm">Re-run</button>
          </form>
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="6" style="color:var(--color-slate);font-style:italic;">No runs yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>

{% endblock %}
```

- [ ] **Step 6: Repoint the header nav link**

In `services/app/templates/base.html`, change both `analysis:queues_summary`
references (desktop nav ~line 43 and mobile drawer ~line 84) to
`analysis:overview`:

```html
        <a href="{% url 'analysis:overview' %}"
           class="nav-link {% if request.resolver_match.namespace == 'analysis' %}nav-link--active{% endif %}">
          Analysis
        </a>
```

(and the same in the mobile drawer block).

- [ ] **Step 7: Add an overview render test**

Append to `services/app/analysis/tests/test_views_schedule.py` (it already
imports `reverse`, `TestCase`, `_user`):

```python
class OverviewPageTests(TestCase):
    """The combined /admin/analysis/ page renders both halves."""

    def setUp(self):
        self.client.force_login(_user("admin"))

    def test_overview_renders_dashboard_and_schedule_sections(self):
        """Page shows dashboard HTMX wrappers + scheduling sections."""
        body = self.client.get(reverse("analysis:overview")).content.decode()
        for wrapper_id in (
            "dash-banner", "dash-workers", "dash-recent",
            "dash-queues", "dash-throughput", "dash-failures", "dash-logs",
        ):
            self.assertIn(f'id="{wrapper_id}"', body)
        self.assertIn("Recurring rules", body)
        self.assertIn("Future planned runs", body)
        self.assertIn("Recent runs", body)
        self.assertIn("Run once now", body)

    def test_overview_uses_even_grid_rows(self):
        """The 50/50 rows use the panel-grid--even modifier."""
        body = self.client.get(reverse("analysis:overview")).content.decode()
        self.assertIn("panel-grid--even", body)
```

- [ ] **Step 8: Run the schedule tests**

Run: `pytest analysis/tests/test_views_schedule.py -q`
Expected: PASS (all, including the new overview tests).

- [ ] **Step 9: bandit + commit**

```bash
cd services/app && source .venv/bin/activate
bandit -ll analysis/views_schedule.py
git add analysis/views_schedule.py analysis/urls.py templates/analysis/overview.html templates/base.html analysis/tests/test_views_schedule.py
git commit -m "feat(#200): add combined /admin/analysis page

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Remove the old dashboard, scheduling shell, and queue pages

Now delete everything the combined page replaced. After this task the full
suite must be green.

**Files:** see deletions listed in File Structure, plus `urls.py`,
`partial_urls.py`, `views.py`, `views_dashboard.py`.

- [ ] **Step 1: Delete the dead tests**

```bash
cd services/app
git rm analysis/tests/test_views_queue.py \
       analysis/tests/test_views_queue_reorder.py \
       analysis/tests/test_views_queues_summary.py \
       analysis/tests/test_status_overview.py
```

- [ ] **Step 2: Rework `test_dashboard_view.py`**

The dashboard *partials* survive (names unchanged), but the shell and the
diagnostics redirect are gone. Edit
`services/app/analysis/tests/test_dashboard_view.py`:

Delete `test_dashboard_shell_renders_for_admin`, `test_diagnostics_redirects_to_dashboard`,
and `test_dashboard_requires_admin` (the shell + diagnostics are removed; the
overview render/gating is covered in `test_views_schedule.py`).

Add `dash_logs` to the partial parametrize list so all seven partials are
covered:

```python
@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "dash_banner", "dash_workers", "dash_queues",
    "dash_throughput", "dash_recent", "dash_failures", "dash_logs",
])
def test_each_partial_renders_for_admin(client, name):
    """Each partial endpoint returns 200 for an admin."""
    admin = _make_user("admin")
    client.force_login(admin)
    response = client.get(reverse(f"analysis:{name}"))
    assert response.status_code == 200
```

Update the module docstring to drop the "shell" / "diagnostics" wording.

- [ ] **Step 3: Edit `urls.py` — remove dead routes, repath partials**

Replace the body of `services/app/analysis/urls.py` `urlpatterns` so it keeps
only the surviving routes. The dashboard partials move under `analysis/`; their
names are unchanged. Final `urlpatterns`:

```python
from django.urls import path

from . import views, views_dashboard, views_schedule

app_name = "analysis"

urlpatterns = [
    path("runpod/start/", views.runpod_start_view, name="runpod_start"),

    # Combined analysis page (dashboard + scheduling) — #200.
    path("analysis/", views_schedule.overview, name="overview"),

    # Dashboard partials (HTMX-polled by the overview page).
    path("analysis/banner/", views_dashboard.dashboard_banner, name="dash_banner"),
    path("analysis/workers/", views_dashboard.dashboard_workers, name="dash_workers"),
    path("analysis/queues/", views_dashboard.dashboard_queues, name="dash_queues"),
    path("analysis/throughput/", views_dashboard.dashboard_throughput, name="dash_throughput"),
    path("analysis/recent/", views_dashboard.dashboard_recent, name="dash_recent"),
    path("analysis/failures/", views_dashboard.dashboard_failures, name="dash_failures"),
    path("analysis/logs/", views_dashboard.dashboard_logs, name="dash_logs"),

    # Scheduling actions (forms POST here; redirect to analysis:overview).
    path("schedule/rule/new/", views_schedule.rule_create, name="rule_create"),
    path("schedule/rule/<int:pk>/edit/", views_schedule.rule_edit, name="rule_edit"),
    path("schedule/rule/<int:pk>/delete/", views_schedule.rule_delete, name="rule_delete"),
    path("schedule/rule/<int:pk>/toggle/", views_schedule.rule_toggle, name="rule_toggle"),
    path("schedule/run-once/", views_schedule.run_once, name="run_once"),
    path("schedule/<int:pk>/rerun/", views_schedule.rerun, name="rerun"),
    path("schedule/preview/", views_schedule.schedule_preview, name="schedule_preview"),
]
```

This drops the `views_queue` import, the `queues/*` routes, the `dashboard/`
shell, the `schedule/` shell (`scheduling`), the `diagnostics/` redirect, and
the `RedirectView` import. Update the file header changelog with a `2026-05-22
(#200)` line.

- [ ] **Step 4: Edit `partial_urls.py` — drop the queue partial**

In `services/app/analysis/partial_urls.py`, set:

```python
from django.urls import path  # noqa: F401  (kept for future partials)

urlpatterns: list = []
```

Update the header to note the `analysis/queue/` overview partial was removed
(#200). (Leaving the empty include in `config/urls.py` is harmless.)

- [ ] **Step 5: Remove the queue views from `views.py`**

In `services/app/analysis/views.py`, delete `queues_summary`,
`overview_partial`, `_queue_context`, and `_engine_metric`. Keep
`_admin_login_required`, `_admin_required`, `runpod_start_view`, and
`_runpod_creds`. Then remove imports that are now unused — after deletion these
are no longer referenced, so delete them:

```python
from datetime import timedelta            # remove
from django.utils import timezone         # remove
from django.utils.timesince import timesince  # remove
from .models import AnalysisJob, WorkerHeartbeat  # remove
from . import services                    # remove
```

Keep `require_GET`/`require_POST` only if still used (`runpod_start_view` uses
`require_POST`; `require_GET` is now unused — remove it from the import). Update
the file header changelog.

- [ ] **Step 6: Delete `views_queue.py` and the dead templates**

```bash
cd services/app
git rm analysis/views_queue.py \
       templates/analysis/dashboard.html \
       templates/analysis/scheduling.html \
       templates/analysis/queues_summary.html \
       templates/analysis/queue.html \
       templates/analysis/status.html \
       templates/analysis/_overview_cards.html \
       templates/analysis/_workers_panel.html \
       templates/analysis/_queue_action_result.html \
       templates/analysis/_queue_active.html \
       templates/analysis/_queue_partial.html \
       templates/analysis/_queue_pending_table.html \
       templates/analysis/_queue_recent.html
```

- [ ] **Step 7: Remove the dashboard shell view**

In `services/app/analysis/views_dashboard.py`, delete the `dashboard` shell
view function (the `@staff_member_required def dashboard(...)` block). Keep the
seven partial views and `_aware`. If `reverse` is still used by the partials
(it is, in `dashboard_recent`/`dashboard_logs`), keep its import; otherwise
remove. Update the file header changelog.

- [ ] **Step 8: Verify no dangling references remain**

Run (from repo root):

```bash
cd services/app
grep -rn "analysis:queues_summary\|analysis:scheduling\|analysis:dashboard\|analysis:queue_stockfish\|analysis:queue_lc0\|analysis:queue_reorder\|analysis:diagnostics\|analysis-queue-partial\|overview_partial\|views_queue\|_queue_context\|queues_summary\.html\|_overview_cards" . | grep -vE "/node_modules/|docs/superpowers/"
```

Expected: no output. If anything prints, fix that reference before continuing.

- [ ] **Step 9: Run the full analysis suite + lint**

Run:

```bash
cd services/app && source .venv/bin/activate
ruff check analysis/
pytest analysis/tests/ -q
bandit -ll analysis/views.py analysis/views_dashboard.py
```

Expected: ruff clean, all tests pass, no Medium/High bandit findings.

- [ ] **Step 10: Commit**

```bash
cd services/app
git add -A
git commit -m "refactor(#200): remove legacy dashboard, schedule shell, and queue pages

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full-suite verification + manual smoke

**Files:** none (verification only).

- [ ] **Step 1: Run the entire app test suite**

Run: `cd services/app && source .venv/bin/activate && pytest -q`
Expected: all pass. (If the dev test DB `.env.test` is missing, create it per
the project's dev-test-DB note before running.)

- [ ] **Step 2: Confirm Tailwind artifact is current**

Run: `services/app/bin/build_tailwind.sh && git status --short services/app/static/css/tailwind.css`
Expected: no diff (artifact already committed in Task 2 and unchanged).

- [ ] **Step 3: Manual smoke (optional but recommended)**

Start the app, log in as an admin, and load `/admin/analysis/`. Verify:
- The header "Analysis" link lands on the page.
- Banner, workers, and recently-completed load full width.
- Queues/Throughput sit side-by-side on desktop and stack on mobile; same for
  Failures/Worker logs and Recurring rules/Future runs.
- Worker-card recent-game IDs are single-line (6-char ids, full id on hover).
- `/admin/dashboard/`, `/admin/schedule/`, and `/admin/queues/` return 404.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin issue/200-rework-analysis-dashboard
gh pr create --title "Rework analysis dashboard (#200)" \
  --body "$(cat <<'EOF'
Combines admin/dashboard, admin/schedule, and admin/queues into a single
/admin/analysis page with responsive 50/50 table rows; removes the queue
pages. Closes #200.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** single page at `admin/analysis` (Task 3) ✓; header link
  (Task 3 Step 6) ✓; dashboard stacked on top (Task 3 template) ✓; gameId 6-char
  truncation (Task 1) ✓; queues+throughput / failures+logs 50/50 rows (Task 3 +
  `.panel-grid--even` Task 2) ✓; recently-completed full width (Task 3) ✓;
  recurring+future 50/50, recent runs full width (Task 3) ✓; remove queue pages
  (Task 4) ✓; tests reworked/added (Tasks 1, 3, 4) ✓; Tailwind rebuild (Task 2)
  ✓.
- **RunPod:** kept intentionally (verified only the removed queues page used it;
  it has its own test). Documented in File Structure.
- **No placeholders:** every code step contains full content.
- **Name consistency:** new URL name is `analysis:overview` everywhere; partial
  names (`dash_*`) unchanged; helper key `game_label_short` used identically in
  helper, template, and test.
