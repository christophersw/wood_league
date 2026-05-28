"""
Title: views.py — Member management views
Description:
    Provides views for managing club members: listing all members with login
    status, adding new members, editing member details, deleting members,
    and inviting members to create login accounts. Admin-only access.

Changelog:
    2026-05-28: Add invite button column with status to members list (#218)
    2026-05-28: Add member_send_invite for magic-link invite endpoint (#218)
    2026-05-08: Added file header to meet documentation standards
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils.html import escape
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from accounts.email_service import EmailService
from accounts.magic_link_service import MagicLinkService
from accounts.models import LoginLink, User
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
    """Display members with login + invite status; admins can send/resend invites.

    Args:
        request: Authenticated HTTP GET request. Must be from an admin user.

    Returns:
        Rendered members list page with per-player invite and login state.
    """
    players = Player.objects.all().order_by("username")
    emails = [p.email.lower() for p in players if p.email]
    users_by_email = {u.email: u for u in User.objects.filter(email__in=emails)}

    rows = []
    for p in players:
        user = users_by_email.get((p.email or "").lower())
        latest_invite = None
        if user is not None:
            latest_invite = (
                LoginLink.objects
                .filter(user=user, purpose=LoginLink.PURPOSE_INVITE)
                .order_by("-created_at").first()
            )
        rows.append({
            "player": p,
            "user": user,
            "has_login": bool(p.email and p.email.lower() in users_by_email),
            "has_logged_in": bool(user and user.last_login),
            "invited_at": latest_invite.created_at if latest_invite else None,
        })

    is_admin = getattr(request.user, "role", None) == "admin"
    return render(request, "players/members.html", {"rows": rows, "is_admin": is_admin})


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
            '<p class="font-mono text-sm text-crimson">Email already in use.</p>',
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

# ── Send / Resend magic-link invite ───────────────────────────────────────────

@login_required
@require_POST
def member_send_invite(request: HttpRequest, player_id: int) -> HttpResponse:
    """Issue or resend a welcome+invite magic link for the given player.

    Args:
        request: Authenticated HTTP POST request. Must be from an admin user.
        player_id: Primary key of the Player to invite.

    Returns:
        HttpResponseForbidden if caller is not admin.
        HttpResponseBadRequest if player not found or has no email.
        Redirect to players:members_list on success or throttle.

    Side effects:
        Creates a User account if none exists for the player email.
        Invalidates any prior unconsumed invite links for that user.
        Sends a welcome+invite email containing the magic link.
    """
    if request.user.role != "admin":
        return HttpResponseForbidden("Admin only.")

    player = Player.objects.filter(pk=player_id).first()
    if player is None:
        return HttpResponseBadRequest("Unknown player.")
    if not player.email:
        return HttpResponseBadRequest("Player has no email on file.")

    email = player.email.strip().lower()
    user, _ = User.objects.get_or_create(
        email=email, defaults={"role": "member", "is_active": True},
    )
    if not user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=["password"])

    svc = MagicLinkService()
    if not svc.throttle_check(user):
        messages.info(request, "An invite was sent recently. Please wait a minute and try again.")
        return redirect("players:members_list")

    _, raw = svc.issue_link(user, purpose=LoginLink.PURPOSE_INVITE, created_by=request.user)
    EmailService().send_invite_email(user, player, raw, invited_by=request.user)
    messages.success(request, f"Invite sent to {email}.")
    return redirect("players:members_list")
