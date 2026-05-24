from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Poll, PollOption, PollVote, Post

MIN_POLL_OPTIONS = 2
MAX_POLL_OPTIONS = 4
MAX_OPTION_LABEL_LENGTH = 200


@dataclass(frozen=True)
class PollOptionSummary:
    id: int
    label: str
    position: int
    vote_count: int
    percentage: float


@dataclass(frozen=True)
class PollSummary:
    poll_id: int
    post_id: int
    total_votes: int
    options: tuple[PollOptionSummary, ...]
    user_vote_option_id: int | None


def normalize_poll_options(raw_options: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_options:
        label = raw.strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(label[:MAX_OPTION_LABEL_LENGTH])
    return cleaned


def validate_poll_options(options: list[str]) -> str | None:
    if len(options) < MIN_POLL_OPTIONS:
        return f"Poll posts need at least {MIN_POLL_OPTIONS} options."
    if len(options) > MAX_POLL_OPTIONS:
        return f"Poll posts can have at most {MAX_POLL_OPTIONS} options."
    return None


def create_poll_post(author, body: str, option_labels: list[str]) -> Post:
    options = normalize_poll_options(option_labels)
    error = validate_poll_options(options)
    if error:
        raise ValueError(error)

    question = body.strip()
    if not question:
        raise ValueError("Add a question before publishing a poll.")

    post = Post(body=question, author=author, is_poll=True)
    poll = Poll(post=post)
    for position, label in enumerate(options):
        poll.options.append(PollOption(label=label, position=position))
    db.session.add(post)
    return post


def poll_summaries_for_posts(posts: list[Post], user_id: int | None) -> dict[int, PollSummary]:
    poll_posts = [post.display_post for post in posts if post.display_post.is_poll and post.display_post.poll]
    if not poll_posts:
        return {}

    poll_ids = [post.poll.id for post in poll_posts]
    polls_by_post_id = {post.id: post.poll for post in poll_posts}

    count_rows = (
        db.session.query(PollVote.option_id, func.count(PollVote.id))
        .filter(PollVote.poll_id.in_(poll_ids))
        .group_by(PollVote.option_id)
        .all()
    )
    counts_by_option_id = dict(count_rows)
    total_by_poll_id: dict[int, int] = dict.fromkeys(poll_ids, 0)
    for option_id, count in count_rows:
        option = db.session.get(PollOption, option_id)
        if option is not None:
            total_by_poll_id[option.poll_id] = total_by_poll_id.get(option.poll_id, 0) + count

    user_votes_by_poll_id: dict[int, int] = {}
    if user_id is not None:
        vote_rows = (
            db.session.query(PollVote.poll_id, PollVote.option_id)
            .filter(PollVote.poll_id.in_(poll_ids), PollVote.user_id == user_id)
            .all()
        )
        user_votes_by_poll_id = {poll_id: option_id for poll_id, option_id in vote_rows}

    summaries: dict[int, PollSummary] = {}
    for post_id, poll in polls_by_post_id.items():
        total_votes = total_by_poll_id.get(poll.id, 0)
        option_summaries: list[PollOptionSummary] = []
        for option in poll.options:
            vote_count = counts_by_option_id.get(option.id, 0)
            percentage = (vote_count / total_votes * 100.0) if total_votes else 0.0
            option_summaries.append(
                PollOptionSummary(
                    id=option.id,
                    label=option.label,
                    position=option.position,
                    vote_count=vote_count,
                    percentage=round(percentage, 1),
                )
            )
        summaries[post_id] = PollSummary(
            poll_id=poll.id,
            post_id=post_id,
            total_votes=total_votes,
            options=tuple(option_summaries),
            user_vote_option_id=user_votes_by_poll_id.get(poll.id),
        )
    return summaries


def cast_poll_vote(poll: Poll, user_id: int, option_id: int) -> PollSummary:
    option = PollOption.query.filter_by(id=option_id, poll_id=poll.id).first()
    if option is None:
        raise ValueError("That poll option does not exist.")

    if PollVote.query.filter_by(poll_id=poll.id, user_id=user_id).first():
        raise ValueError("You already voted on this poll.")

    db.session.add(PollVote(poll_id=poll.id, option_id=option.id, user_id=user_id))
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValueError("You already voted on this poll.") from exc

    summaries = poll_summaries_for_posts([poll.post], user_id)
    return summaries[poll.post_id]


def poll_summary_as_json(summary: PollSummary) -> dict:
    return {
        "poll_id": summary.poll_id,
        "post_id": summary.post_id,
        "total_votes": summary.total_votes,
        "user_vote_option_id": summary.user_vote_option_id,
        "options": [
            {
                "id": option.id,
                "label": option.label,
                "position": option.position,
                "vote_count": option.vote_count,
                "percentage": option.percentage,
            }
            for option in summary.options
        ],
    }
