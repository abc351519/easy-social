from __future__ import annotations

import io
import random
import string

from captcha.image import ImageCaptcha
from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")

_CAPTCHA_LENGTH = 5
_CAPTCHA_CHARS = string.ascii_uppercase + string.digits


def _generate_captcha_text() -> str:
    return "".join(random.choices(_CAPTCHA_CHARS, k=_CAPTCHA_LENGTH))


def _validate_captcha(user_input: str) -> bool:
    # Bypass validation in TESTING mode unless CAPTCHA_FORCE_TEXT is set.
    # CAPTCHA_FORCE_TEXT enables real validation in E2E tests by using a known text.
    if current_app.config.get("TESTING") and not current_app.config.get("CAPTCHA_FORCE_TEXT"):
        return True
    expected = session.pop("captcha_text", None)
    if expected is None:
        return False
    return user_input.strip().upper() == expected.upper()


@bp.get("/captcha")
def captcha_image() -> Response:
    force_text = current_app.config.get("CAPTCHA_FORCE_TEXT")
    text = force_text if force_text else _generate_captcha_text()
    session["captcha_text"] = text
    image = ImageCaptcha()
    data = image.generate(text)
    img_bytes = io.BytesIO(data.read())
    return Response(img_bytes.getvalue(), mimetype="image/png")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("social.feed"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        captcha_input = request.form.get("captcha", "")

        error = None
        if not username or not email or not password:
            error = "Username, email, and password are required."
        elif len(username) > 40:
            error = "Username must be 40 characters or fewer."
        elif not current_app.config.get("TESTING") and not captcha_input:
            error = "Please enter the CAPTCHA."
        elif not _validate_captcha(captcha_input):
            error = "Incorrect CAPTCHA. Please try again."
        elif User.query.filter_by(username=username).first():
            error = "That username is already taken."
        elif User.query.filter_by(email=email).first():
            error = "That email is already registered."

        if error:
            flash(error, "error")
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            return redirect(url_for("social.feed"))

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("social.feed"))

    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter(
            (User.username == username_or_email)
            | (User.email == username_or_email.lower())
        ).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("social.feed"))

        flash("Invalid username/email or password.", "error")

    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

