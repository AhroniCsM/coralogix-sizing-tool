"""Authentication router — Google OAuth 2.0 for @coralogix.com users."""

import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# ---------------------------------------------------------------------------
# OAuth setup
# ---------------------------------------------------------------------------
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

ALLOWED_DOMAIN = "coralogix.com"


def get_current_user(request: Request) -> dict | None:
    """Return user dict from session, or None if not logged in."""
    return request.session.get("user")


def require_auth(request: Request) -> RedirectResponse | None:
    """If user is not authenticated, return a redirect to /login."""
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page. If already logged in, redirect to home."""
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    error = request.query_params.get("error")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@router.get("/auth/google")
async def auth_google(request: Request):
    """Redirect to Google OAuth consent screen."""
    # Build callback URL — use X-Forwarded-Host if behind a proxy (Firebase Hosting)
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        redirect_uri = f"https://{forwarded_host}/auth/callback"
    else:
        redirect_uri = str(request.url_for("auth_callback"))
        if "fly.dev" in redirect_uri or "coralogix" in redirect_uri or "run.app" in redirect_uri:
            redirect_uri = redirect_uri.replace("http://", "https://")
    response = await oauth.google.authorize_redirect(request, redirect_uri)
    # Prevent Firebase Hosting from caching this redirect (state is unique per request)
    response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate"
    return response


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle Google OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.exception("OAuth token exchange failed")
        return RedirectResponse(f"/login?error=Authentication failed: {e}", status_code=303)

    user_info = token.get("userinfo")
    if not user_info:
        return RedirectResponse("/login?error=Could not retrieve user info", status_code=303)

    email = user_info.get("email", "")
    name = user_info.get("name", email)

    # Domain restriction
    if not email.endswith(f"@{ALLOWED_DOMAIN}"):
        logger.warning("Rejected login from non-Coralogix email: %s", email)
        return RedirectResponse(
            f"/login?error=Only @{ALLOWED_DOMAIN} emails are allowed. You signed in as {email}.",
            status_code=303,
        )

    # Store in session
    request.session["user"] = {
        "email": email,
        "name": name,
        "picture": user_info.get("picture", ""),
    }
    logger.info("User logged in: %s", email)

    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
