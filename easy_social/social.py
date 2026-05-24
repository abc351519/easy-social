from __future__ import annotations

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import joinedload

from .extensions import db
from .media import save_media
from .models import Comment, Poll, Post, User, followers
from .poll_service import (
    cast_poll_vote,
    create_poll_post,
    poll_summaries_for_posts,
    poll_summary_as_json,
)

bp = Blueprint("social", __name__)


def _post_query():
    return Post.query.options(
        joinedload(Post.author),
        joinedload(Post.repost_of).joinedload(Post.author),
        joinedload(Post.poll).joinedload(Poll.options),
    )


def _comment_counts_for_posts(posts: list[Post]) -> dict[int, int]:
    post_ids = {post.display_post.id for post in posts}
    if not post_ids:
        return {}

    counts = dict.fromkeys(post_ids, 0)
    rows = (
        db.session.query(Comment.post_id, func.count(Comment.id))
        .filter(Comment.post_id.in_(post_ids))
        .group_by(Comment.post_id)
        .all()
    )
    counts.update({post_id: count for post_id, count in rows})
    return counts


def _followed_user_ids(users: list[User]) -> set[int]:
    user_ids = [user.id for user in users]
    if not user_ids:
        return set()

    return {
        followed_id
        for (followed_id,) in db.session.query(followers.c.followed_id)
        .filter(
            followers.c.follower_id == current_user.id,
            followers.c.followed_id.in_(user_ids),
        )
        .all()
    }


def _render_posts_page(template_name: str, posts: list[Post], **context):
    return render_template(
        template_name,
        posts=posts,
        comment_counts=_comment_counts_for_posts(posts),
        poll_summaries=poll_summaries_for_posts(posts, current_user.id),
        **context,
    )


@bp.route("/")
@login_required
def feed():
    followed_ids = db.session.query(followers.c.followed_id).filter(
        followers.c.follower_id == current_user.id
    )
    posts = (
        _post_query()
        .filter(or_(Post.author_id == current_user.id, Post.author_id.in_(followed_ids)))
        .order_by(desc(Post.created_at))
        .limit(100)
        .all()
    )
    return _render_posts_page("social/feed.html", posts)


@bp.route("/explore")
@login_required
def explore():
    posts = _post_query().order_by(desc(Post.created_at)).limit(100).all()
    users = User.query.filter(User.id != current_user.id).order_by(User.username).limit(50).all()
    return _render_posts_page(
        "social/explore.html",
        posts,
        users=users,
        followed_user_ids=_followed_user_ids(users),
    )


@bp.post("/posts")
@login_required
def create_post():
    post_type = request.form.get("post_type", "standard")
    body = request.form.get("body", "").strip()

    if post_type == "poll":
        try:
            create_poll_post(
                current_user,
                body,
                request.form.getlist("poll_options"),
            )
            db.session.commit()
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(request.referrer or url_for("social.feed"))

    try:
        media_filename, media_type = save_media(request.files.get("media"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("social.feed"))

    if not body and not media_filename:
        flash("Add text, an image, or a video before posting.", "error")
        return redirect(request.referrer or url_for("social.feed"))

    post = Post(
        body=body,
        media_filename=media_filename,
        media_type=media_type,
        author=current_user,
    )
    db.session.add(post)
    db.session.commit()
    return redirect(url_for("social.feed"))


@bp.get("/posts/<int:post_id>")
@login_required
def post_detail(post_id: int):
    post = _post_query().filter(Post.id == post_id).first_or_404()
    comments = post.display_post.comments.order_by(Comment.created_at.asc()).all()
    poll_summaries = poll_summaries_for_posts([post], current_user.id)
    return render_template(
        "social/post_detail.html",
        post=post,
        comments=comments,
        comment_counts={post.display_post.id: len(comments)},
        poll_summaries=poll_summaries,
    )


@bp.post("/posts/<int:post_id>/vote")
@login_required
def cast_vote(post_id: int):
    post = _post_query().filter(Post.id == post_id).first_or_404()
    content = post.display_post
    poll = content.poll
    if poll is None:
        abort(404)

    option_id = request.form.get("option_id", type=int)
    if option_id is None:
        message = "Choose a poll option before voting."
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": message}), 400
        flash(message, "error")
        return redirect(request.referrer or url_for("social.post_detail", post_id=content.id))

    try:
        summary = cast_poll_vote(poll, current_user.id, option_id)
    except ValueError as exc:
        if request.accept_mimetypes.best == "application/json":
            return jsonify({"error": str(exc)}), 400
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("social.post_detail", post_id=content.id))

    if request.accept_mimetypes.best == "application/json":
        return jsonify(poll_summary_as_json(summary))

    return redirect(request.referrer or url_for("social.post_detail", post_id=content.id))


@bp.post("/posts/<int:post_id>/comments")
@login_required
def add_comment(post_id: int):
    post = db.get_or_404(Post, post_id)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Comment cannot be empty.", "error")
    else:
        db.session.add(Comment(body=body, author=current_user, post=post))
        db.session.commit()
    return redirect(url_for("social.post_detail", post_id=post.id))


@bp.post("/posts/<int:post_id>/repost")
@login_required
def repost(post_id: int):
    original = db.get_or_404(Post, post_id).display_post
    if original.author_id == current_user.id:
        flash("You cannot repost your own post.", "error")
        return redirect(request.referrer or url_for("social.feed"))

    existing = Post.query.filter_by(author_id=current_user.id, repost_of_id=original.id).first()
    if existing:
        flash("You already reposted this.", "error")
        return redirect(request.referrer or url_for("social.feed"))

    db.session.add(Post(author=current_user, repost_of=original))
    db.session.commit()
    return redirect(request.referrer or url_for("social.feed"))


@bp.route("/users/<username>")
@login_required
def profile(username: str):
    user = User.query.filter_by(username=username).first_or_404()
    posts = (
        _post_query()
        .filter(Post.author_id == user.id)
        .order_by(desc(Post.created_at))
        .all()
    )
    return render_template(
        "social/profile.html",
        profile_user=user,
        posts=posts,
        comment_counts=_comment_counts_for_posts(posts),
        poll_summaries=poll_summaries_for_posts(posts, current_user.id),
    )


@bp.post("/users/<username>/follow")
@login_required
def follow(username: str):
    user = User.query.filter_by(username=username).first_or_404()
    current_user.follow(user)
    db.session.commit()
    return redirect(request.referrer or url_for("social.profile", username=user.username))


@bp.post("/users/<username>/unfollow")
@login_required
def unfollow(username: str):
    user = User.query.filter_by(username=username).first_or_404()
    current_user.unfollow(user)
    db.session.commit()
    return redirect(request.referrer or url_for("social.profile", username=user.username))
