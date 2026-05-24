from __future__ import annotations

import pytest

from easy_social.extensions import db
from easy_social.models import PollVote, Post, User
from easy_social.poll_service import (
    MAX_POLL_OPTIONS,
    MIN_POLL_OPTIONS,
    cast_poll_vote,
    create_poll_post,
    normalize_poll_options,
    poll_summaries_for_posts,
    poll_summary_as_json,
    validate_poll_options,
)

from conftest import login, register

pytestmark_integration = pytest.mark.integration
pytestmark_unit = pytest.mark.unit


def make_user(username: str) -> User:
    user = User(username=username, email=f"{username}@example.com")
    user.set_password("password")
    return user


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_poll_options_trims_and_deduplicates():
    assert normalize_poll_options([" Yes ", "yes", "", "No"]) == ["Yes", "No"]


@pytest.mark.unit
def test_normalize_poll_options_truncates_long_labels():
    long_label = "x" * 250
    assert len(normalize_poll_options([long_label])[0]) == 200


@pytest.mark.unit
def test_validate_poll_options_enforces_bounds():
    assert validate_poll_options(["a", "b"]) is None
    assert "at least" in (validate_poll_options(["only"]) or "")
    assert "at most" in (validate_poll_options(["a", "b", "c", "d", "e"]) or "")


@pytest.mark.unit
def test_create_poll_post_rejects_empty_question(app):
    with app.app_context():
        alice = make_user("alice")
        db.session.add(alice)
        db.session.commit()

        with pytest.raises(ValueError, match="question"):
            create_poll_post(alice, "   ", ["A", "B"])


@pytest.mark.unit
def test_create_poll_post_persists_options_in_order(app):
    with app.app_context():
        alice = make_user("alice")
        post = create_poll_post(alice, "Order?", ["First", "Second", "Third"])
        db.session.add(alice)
        db.session.add(post)
        db.session.commit()

        labels = [option.label for option in post.poll.options]
        positions = [option.position for option in post.poll.options]
        assert labels == ["First", "Second", "Third"]
        assert positions == [0, 1, 2]


@pytest.mark.unit
def test_poll_summaries_for_posts_skips_non_poll_posts(app):
    with app.app_context():
        alice = make_user("alice")
        text_post = Post(author=alice, body="Just text")
        db.session.add_all([alice, text_post])
        db.session.commit()

        assert poll_summaries_for_posts([text_post], alice.id) == {}


@pytest.mark.unit
def test_poll_summary_percentages(app):
    with app.app_context():
        alice = make_user("alice")
        bob = make_user("bob")
        post = create_poll_post(alice, "Favorite color?", ["Red", "Blue"])
        db.session.add_all([alice, bob, post])
        db.session.commit()

        cast_poll_vote(post.poll, alice.id, post.poll.options[0].id)
        cast_poll_vote(post.poll, bob.id, post.poll.options[1].id)
        bob_id = bob.id
        post_id = post.id

    with app.app_context():
        post = db.session.get(Post, post_id)
        summary = poll_summaries_for_posts([post], bob_id)[post_id]
        by_label = {option.label: option for option in summary.options}

        assert summary.total_votes == 2
        assert by_label["Red"].vote_count == 1
        assert by_label["Blue"].vote_count == 1
        assert by_label["Red"].percentage == 50.0
        assert summary.user_vote_option_id == by_label["Blue"].id


@pytest.mark.unit
def test_poll_summary_as_json_shape(app):
    with app.app_context():
        alice = make_user("alice")
        post = create_poll_post(alice, "Snack?", ["A", "B"])
        db.session.add_all([alice, post])
        db.session.commit()
        cast_poll_vote(post.poll, alice.id, post.poll.options[0].id)

        summary = poll_summaries_for_posts([post], alice.id)[post.id]
        payload = poll_summary_as_json(summary)
        post_id = post.id
        voted_option_id = post.poll.options[0].id

    assert payload["post_id"] == post_id
    assert payload["total_votes"] == 1
    assert payload["user_vote_option_id"] == voted_option_id
    assert payload["options"][0]["percentage"] == 100.0


@pytest.mark.unit
def test_poll_vote_unique_per_user(app):
    with app.app_context():
        alice = make_user("alice")
        post = create_poll_post(alice, "Pick one", ["A", "B"])
        db.session.add_all([alice, post])
        db.session.commit()

        cast_poll_vote(post.poll, alice.id, post.poll.options[0].id)
        with pytest.raises(ValueError, match="already voted"):
            cast_poll_vote(post.poll, alice.id, post.poll.options[1].id)


@pytest.mark.unit
def test_cast_poll_vote_rejects_foreign_option(app):
    with app.app_context():
        alice = make_user("alice")
        bob = make_user("bob")
        post_a = create_poll_post(alice, "A?", ["One", "Two"])
        post_b = create_poll_post(bob, "B?", ["X", "Y"])
        db.session.add_all([alice, bob, post_a, post_b])
        db.session.commit()

        foreign_option_id = post_b.poll.options[0].id
        with pytest.raises(ValueError, match="does not exist"):
            cast_poll_vote(post_a.poll, alice.id, foreign_option_id)


@pytest.mark.unit
def test_poll_option_constants():
    assert MIN_POLL_OPTIONS == 2
    assert MAX_POLL_OPTIONS == 4


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_poll_post_via_route(client, app):
    register(client, "alice")

    response = client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Best snack?",
            "poll_options": ["Cookies", "Chips", "Cookies", ""],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        post = Post.query.one()
        assert post.is_poll
        assert post.body == "Best snack?"
        assert [option.label for option in post.poll.options] == ["Cookies", "Chips"]


@pytest.mark.integration
def test_create_poll_with_four_options(client, app):
    register(client, "alice")

    client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Pick one",
            "poll_options": ["One", "Two", "Three", "Four"],
        },
        follow_redirects=True,
    )

    with app.app_context():
        post = Post.query.one()
        assert len(post.poll.options) == 4


@pytest.mark.integration
def test_create_poll_requires_two_options(client, app):
    register(client, "alice")

    response = client.post(
        "/posts",
        data={"post_type": "poll", "body": "Only one?", "poll_options": ["Solo"]},
        follow_redirects=True,
    )

    assert b"at least" in response.data
    with app.app_context():
        assert Post.query.count() == 0


@pytest.mark.integration
def test_create_poll_requires_question(client, app):
    register(client, "alice")

    response = client.post(
        "/posts",
        data={"post_type": "poll", "body": "   ", "poll_options": ["A", "B"]},
        follow_redirects=True,
    )

    assert b"question" in response.data
    with app.app_context():
        assert Post.query.count() == 0


@pytest.mark.integration
def test_create_poll_rejects_five_options(client, app):
    register(client, "alice")

    response = client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Too many?",
            "poll_options": ["1", "2", "3", "4", "5"],
        },
        follow_redirects=True,
    )

    assert b"at most" in response.data
    with app.app_context():
        assert Post.query.count() == 0


@pytest.mark.integration
def test_cast_vote_returns_json_and_updates_feed(client, app):
    register(client, "alice")
    register(client, "bob")
    login(client, "alice")

    client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Team?",
            "poll_options": ["A", "B"],
        },
        follow_redirects=True,
    )

    with app.app_context():
        post = Post.query.one()
        option_id = post.poll.options[0].id
        post_id = post.id

    login(client, "bob")
    response = client.post(
        f"/posts/{post_id}/vote",
        data={"option_id": option_id},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total_votes"] == 1
    assert payload["options"][0]["vote_count"] == 1
    assert payload["options"][0]["percentage"] == 100.0
    assert payload["user_vote_option_id"] == option_id

    feed = client.get("/")
    assert b"100.0%" in feed.data or b"100%" in feed.data


@pytest.mark.integration
def test_cast_vote_without_option_id_returns_error(client, app):
    register(client, "alice")
    login(client, "alice")

    client.post(
        "/posts",
        data={"post_type": "poll", "body": "Go?", "poll_options": ["Yes", "No"]},
        follow_redirects=True,
    )

    with app.app_context():
        post_id = Post.query.one().id

    response = client.post(
        f"/posts/{post_id}/vote",
        data={},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 400
    assert "Choose a poll option" in response.get_json()["error"]


@pytest.mark.integration
def test_cast_vote_redirects_for_html_clients(client, app):
    register(client, "alice")
    register(client, "bob")
    login(client, "alice")

    client.post(
        "/posts",
        data={"post_type": "poll", "body": "Color?", "poll_options": ["Red", "Blue"]},
        follow_redirects=True,
    )

    with app.app_context():
        post = Post.query.one()
        post_id = post.id
        option_id = post.poll.options[1].id

    login(client, "bob")
    response = client.post(
        f"/posts/{post_id}/vote",
        data={"option_id": option_id},
        follow_redirects=False,
    )

    assert response.status_code == 302


@pytest.mark.integration
def test_duplicate_vote_is_rejected(client, app):
    register(client, "alice")
    login(client, "alice")

    client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Go?",
            "poll_options": ["Yes", "No"],
        },
        follow_redirects=True,
    )

    with app.app_context():
        post = Post.query.one()
        first_option = post.poll.options[0].id
        second_option = post.poll.options[1].id
        post_id = post.id

    client.post(
        f"/posts/{post_id}/vote",
        data={"option_id": first_option},
        headers={"Accept": "application/json"},
    )
    response = client.post(
        f"/posts/{post_id}/vote",
        data={"option_id": second_option},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 400
    assert "already voted" in response.get_json()["error"]
    with app.app_context():
        assert PollVote.query.count() == 1


@pytest.mark.integration
def test_poll_appears_on_profile_and_post_detail(client, app):
    register(client, "alice")
    login(client, "alice")

    client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Lunch?",
            "poll_options": ["Pizza", "Salad"],
        },
        follow_redirects=True,
    )

    profile = client.get("/users/alice")
    assert b"Lunch?" in profile.data
    assert b"Pizza" in profile.data

    with app.app_context():
        post_id = Post.query.one().id

    detail = client.get(f"/posts/{post_id}")
    assert b'data-poll' in detail.data
    assert b"poll-choice" in detail.data


@pytest.mark.integration
def test_explore_lists_poll_posts(client, app):
    register(client, "alice")
    login(client, "alice")

    client.post(
        "/posts",
        data={
            "post_type": "poll",
            "body": "Explore poll?",
            "poll_options": ["Alpha", "Beta"],
        },
        follow_redirects=True,
    )

    explore = client.get("/explore")
    assert b"Explore poll?" in explore.data
    assert b"Alpha" in explore.data


@pytest.mark.integration
def test_voted_poll_shows_results_not_buttons(client, app):
    register(client, "alice")
    register(client, "bob")
    login(client, "alice")

    client.post(
        "/posts",
        data={"post_type": "poll", "body": "Done?", "poll_options": ["X", "Y"]},
        follow_redirects=True,
    )

    with app.app_context():
        post = Post.query.one()
        post_id = post.id
        option_id = post.poll.options[0].id

    login(client, "bob")
    client.post(
        f"/posts/{post_id}/vote",
        data={"option_id": option_id},
        headers={"Accept": "application/json"},
    )

    feed = client.get("/")
    assert b"poll-bar-fill" in feed.data
    assert b"poll-choice" not in feed.data
