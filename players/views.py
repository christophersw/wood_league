"""Views for member management: list, add, edit, delete, and invite players."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.utils.html import escape
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.models import User
from games.models import GameParticipant

from .models import Player

_admin_required = user_passes_test(lambda u: u.role == "admin")


def _admin_login_required(view):
    """Decorator requiring login and admin role."""
    return login_required(_admin_required(view))


# ── Members list ──────────────────────────────────────────────────────────────

@_admin_login_required
@require_GET
def members_list(request: HttpRequest) -> HttpResponse:
    """Display table of all club members with login status."""
    players = Player.objects.order_by("username")
    login_emails = set(
        User.objects.values_list("email", flat=True)
    )
    rows = []
    for p in players:
        rows.append({
            "player": p,
            "has_login": bool(p.email and p.email in login_emails),
        })
    return render(request, "players/members.html", {"rows": rows})


# ── Add member ────────────────────────────────────────────────────────────────

@_admin_login_required
@require_POST
def add_member(request: HttpRequest) -> HttpResponse:
    """Create a new club member from POST data and return updated member table."""
    username = request.POST.get("username", "").strip().lower()
    display_name = request.POST.get("display_name", "").strip() or username
    name = request.POST.get("name", "").strip() or None
    email = request.POST.get("email", "").strip() or None

    error = None
    if not username:
        error = "Username is required."
    elif Player.objects.filter(username=username).exists():
        error = f"A member with username '{username}' already exists."
    elif email and Player.objects.filter(email=email).exists():
        error = f"Email '{email}' is already used by another member."

    if error:
        return HttpResponse(
            f'<p class="font-mono text-sm text-crimson mt-2">{escape(error)}</p>',
            status=422,
        )

    Player.objects.create(username=username, display_name=display_name, name=name, email=email)
    players = Player.objects.order_by("username")
    login_emails = set(User.objects.values_list("email", flat=True))
    rows = [{"player": p, "has_login": bool(p.email and p.email in login_emails)} for p in players]
    return render(request, "players/_table.html", {"rows": rows})


# ── Edit member (inline) ──────────────────────────────────────────────────────

@_admin_login_required
@require_POST
def edit_member(request: HttpRequest, pk: int) -> HttpResponse:
    """Update a player's name and email from POST data and return updated row."""
    player = get_object_or_404(Player, pk=pk)
    name = request.POST.get("name", "").strip() or None
    email = request.POST.get("email", "").strip() or None

    if email and Player.objects.filter(email=email).exclude(pk=pk).exists():
        return HttpResponse(
            f'<p class="font-mono text-sm text-crimson">Email already in use.</p>',
            status=422,
        )

    player.name = name
    player.email = email
    try:
        player.save()
    except IntegrityError:
        return HttpResponse(
            '<p class="font-mono text-sm text-crimson">Save failed — duplicate email.</p>',
            status=422,
        )

    login_emails = set(User.objects.values_list("email", flat=True))
    return render(request, "players/_row.html", {
        "row": {"player": player, "has_login": bool(player.email and player.email in login_emails)},
    })


# ── Delete member ─────────────────────────────────────────────────────────────

@_admin_login_required
@require_http_methods(["DELETE"])
def delete_member(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a player and all associated game records."""
    player = get_object_or_404(Player, pk=pk)
    GameParticipant.objects.filter(player=player).delete()
    player.delete()
    return HttpResponse("")


# ── Invite member (create login) ──────────────────────────────────────────────

@_admin_login_required
@require_POST
def invite_member(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a login account for a player with email and password, assigning a role."""
    player = get_object_or_404(Player, pk=pk)
    if not player.email:
        return HttpResponse(
            '<p class="font-mono text-sm text-crimson">Player has no email set.</p>',
            status=422,
        )

    password = request.POST.get("password", "").strip()
    role = request.POST.get("role", "member")
    if role not in ("member", "admin"):
        role = "member"

    if len(password) < 8:
        return HttpResponse(
            '<p class="font-mono text-sm text-crimson">Password must be at least 8 characters.</p>',
            status=422,
        )

    if User.objects.filter(email=player.email).exists():
        return HttpResponse(
            '<p class="font-mono text-sm text-crimson">A login already exists for this email.</p>',
            status=422,
        )

    User.objects.create_user(email=player.email, password=password, role=role)
    return render(request, "players/_invite_result.html", {
        "player": player,
        "email": player.email,
    })
