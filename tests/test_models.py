from __future__ import annotations

from sqlalchemy.exc import IntegrityError

import pytest

from easy_social.extensions import db
from easy_social.models import Post, User

pytestmark = pytest.mark.unit


def make_user(username: str) -> User:
    user = User(username=username, email=f"{username}@example.com")
    user.set_password("password")
    return user


def test_user_password_hashing_round_trip(app):
    with app.app_context():
        user = make_user("alice")

        assert user.password_hash != "password"
        assert user.check_password("password")
        assert not user.check_password("wrong-password")


def test_follow_is_idempotent_and_blocks_self_follow(app):
    with app.app_context():
        alice = make_user("alice")
        bob = make_user("bob")
        db.session.add_all([alice, bob])
        db.session.commit()

        alice.follow(alice)
        alice.follow(bob)
        alice.follow(bob)
        db.session.commit()

        assert not alice.is_following(alice)
        assert alice.is_following(bob)
        assert alice.following.count() == 1


def test_unfollow_removes_existing_follow_only(app):
    with app.app_context():
        alice = make_user("alice")
        bob = make_user("bob")
        db.session.add_all([alice, bob])
        db.session.commit()

        alice.unfollow(bob)
        alice.follow(bob)
        db.session.commit()

        alice.unfollow(bob)
        alice.unfollow(bob)
        db.session.commit()

        assert not alice.is_following(bob)
        assert alice.following.count() == 0


def test_post_requires_content_media_or_repost(app):
    with app.app_context():
        alice = make_user("alice")
        db.session.add(alice)
        db.session.commit()

        db.session.add(Post(author=alice, body=""))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
        else:
            raise AssertionError("empty post should violate content constraint")


def test_poll_post_satisfies_content_constraint(app):
    with app.app_context():
        alice = make_user("alice")
        poll_post = Post(author=alice, body="Question?", is_poll=True)
        db.session.add_all([alice, poll_post])
        db.session.commit()

        assert poll_post.is_poll
        assert poll_post.body == "Question?"


def test_repost_display_post_points_to_original(app):
    with app.app_context():
        alice = make_user("alice")
        bob = make_user("bob")
        original = Post(author=alice, body="Original post")
        repost = Post(author=bob, body="", repost_of=original)
        db.session.add_all([alice, bob, original, repost])
        db.session.commit()

        assert not original.is_repost
        assert original.display_post == original
        assert repost.is_repost
        assert repost.display_post == original
