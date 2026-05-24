from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from easy_social import create_app
from easy_social.extensions import db
from easy_social.models import Comment, Poll, PollOption, PollVote, Post, User

selenium = pytest.importorskip("selenium")

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@pytest.fixture(scope="module")
def ui_app():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{temp_path / 'ui.sqlite'}",
                "UPLOAD_FOLDER": str(temp_path / "uploads"),
                "MEDIA_STORAGE_BACKEND": "local",
                "WTF_CSRF_ENABLED": False,
            }
        )
        with app.app_context():
            db.create_all()
        yield app


@pytest.fixture(scope="module")
def live_server(ui_app):
    try:
        server = make_server("127.0.0.1", 0, ui_app, threaded=True)
    except SystemExit:
        pytest.skip("Selenium live server could not bind to a local port")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{server.server_port}"

    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture()
def browser():
    browser_name = os.environ.get("SELENIUM_BROWSER", "chrome").lower()
    headless = os.environ.get("SELENIUM_HEADLESS", "1") != "0"

    try:
        if browser_name == "firefox":
            options = webdriver.FirefoxOptions()
            if headless:
                options.add_argument("-headless")
            driver = webdriver.Firefox(options=options)
        else:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,900")
            driver = webdriver.Chrome(options=options)
    except WebDriverException as exc:
        pytest.skip(f"Selenium browser could not start: {exc.msg}")

    yield driver

    driver.quit()


@pytest.fixture(autouse=True)
def clean_database(ui_app):
    with ui_app.app_context():
        db.session.query(Comment).delete()
        db.session.query(PollVote).delete()
        db.session.query(PollOption).delete()
        db.session.query(Poll).delete()
        db.session.query(Post).delete()
        db.session.query(User).delete()
        db.session.commit()


def wait_for_text(browser, text: str):
    WebDriverWait(browser, 5).until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), text))


def wait_for_feed(browser):
    WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "form.composer")))
    wait_for_text(browser, "Feed")


def wait_for_login(browser):
    WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.NAME, "username_or_email")))
    wait_for_text(browser, "Log in")


def set_field_value(browser, field, value: str):
    browser.execute_script(
        """
        arguments[0].value = arguments[1];
        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
        """,
        field,
        value,
    )


def submit_form(browser, form):
    browser.execute_script("arguments[0].requestSubmit ? arguments[0].requestSubmit() : arguments[0].submit();", form)


def register_via_ui(browser, live_server: str, username: str):
    browser.get(f"{live_server}/auth/register")
    form = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.form-stack"))
    )
    set_field_value(browser, form.find_element(By.NAME, "username"), username)
    set_field_value(browser, form.find_element(By.NAME, "email"), f"{username}@example.com")
    set_field_value(browser, form.find_element(By.NAME, "password"), "password")
    submit_form(browser, form)
    wait_for_feed(browser)


def logout_via_ui(browser):
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, "header form"))
    wait_for_login(browser)


def login_via_ui(browser, live_server: str, username: str, password: str = "password"):
    browser.get(f"{live_server}/auth/login")
    form = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.form-stack"))
    )
    set_field_value(browser, form.find_element(By.NAME, "username_or_email"), username)
    set_field_value(browser, form.find_element(By.NAME, "password"), password)
    submit_form(browser, form)
    wait_for_feed(browser)


def create_poll_via_ui(browser, question: str, options: list[str]):
    composer = browser.find_element(By.CSS_SELECTOR, "form.composer")
    poll_radio = composer.find_element(By.CSS_SELECTOR, 'input[name="post_type"][value="poll"]')
    poll_radio.click()
    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-poll-fields]"))
    )

    set_field_value(browser, composer.find_element(By.NAME, "body"), question)
    option_inputs = composer.find_elements(By.CSS_SELECTOR, "[data-poll-option]")
    for index, label in enumerate(options):
        set_field_value(browser, option_inputs[index], label)

    submit_button = composer.find_element(By.CSS_SELECTOR, "[data-composer-submit]")
    WebDriverWait(browser, 5).until(lambda _: submit_button.text.strip() == "Create poll")
    submit_form(browser, composer)
    wait_for_text(browser, question)


@pytest.mark.parametrize(
    ("filename", "contents", "expected_tag"),
    [
        ("preview.png", b"fake image data", "img"),
        ("preview.mp4", b"fake video data", "video"),
    ],
)
@pytest.mark.ui
def test_composer_shows_media_preview_before_posting(
    browser, live_server, tmp_path, filename, contents, expected_tag
):
    register_via_ui(browser, live_server, "previewer")
    media_path = tmp_path / filename
    media_path.write_bytes(contents)

    composer = browser.find_element(By.CSS_SELECTOR, "form.composer")
    media_input = composer.find_element(By.NAME, "media")
    browser.execute_script("arguments[0].style.display = 'block';", media_input)
    media_input.send_keys(str(media_path))

    preview = composer.find_element(By.CSS_SELECTOR, "[data-media-preview]")
    WebDriverWait(browser, 5).until(lambda _: preview.is_displayed())
    media = preview.find_element(By.CSS_SELECTOR, ".composer-preview-media")

    assert media.tag_name == expected_tag
    assert media.get_attribute("src").startswith("blob:")
    assert filename in preview.text
    if expected_tag == "video":
        assert media.get_attribute("controls") is not None

    preview.find_element(By.CSS_SELECTOR, "[data-media-preview-clear]").click()
    WebDriverWait(browser, 5).until(lambda _: not preview.is_displayed())
    assert media_input.get_attribute("value") == ""


@pytest.mark.ui
def test_user_can_register_create_post_and_comment(browser, live_server):
    register_via_ui(browser, live_server, "alice")

    composer = browser.find_element(By.CSS_SELECTOR, "form.composer")
    set_field_value(browser, composer.find_element(By.NAME, "body"), "Hello from Selenium")
    submit_form(browser, composer)
    wait_for_text(browser, "Hello from Selenium")

    comments_link = browser.find_element(By.PARTIAL_LINK_TEXT, "0 comments")
    browser.get(comments_link.get_attribute("href"))
    wait_for_text(browser, "Comments")
    comment_form = browser.find_element(By.CSS_SELECTOR, "form.comment-form")
    set_field_value(browser, comment_form.find_element(By.NAME, "body"), "First UI comment")
    submit_form(browser, comment_form)
    wait_for_text(browser, "First UI comment")


@pytest.mark.ui
def test_user_can_create_poll_post_from_composer(browser, live_server):
    register_via_ui(browser, live_server, "pollauthor")
    create_poll_via_ui(browser, "Favorite season?", ["Spring", "Summer", "Fall"])

    poll_root = browser.find_element(By.CSS_SELECTOR, "[data-poll]")
    choices = poll_root.find_elements(By.CSS_SELECTOR, ".poll-choice")
    assert len(choices) == 3
    assert {choice.text for choice in choices} == {"Spring", "Summer", "Fall"}


@pytest.mark.ui
def test_poll_mode_hides_media_attachment(browser, live_server):
    register_via_ui(browser, live_server, "pollui")
    composer = browser.find_element(By.CSS_SELECTOR, "form.composer")
    composer.find_element(By.CSS_SELECTOR, 'input[name="post_type"][value="poll"]').click()

    WebDriverWait(browser, 5).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "[data-poll-fields]"))
    )
    media_picker = composer.find_element(By.CSS_SELECTOR, "[data-media-picker]")
    assert not media_picker.is_displayed()


@pytest.mark.ui
def test_user_can_vote_and_see_live_percentages(browser, live_server):
    register_via_ui(browser, live_server, "pollalice")
    create_poll_via_ui(browser, "Pick a team", ["Cats", "Dogs"])
    logout_via_ui(browser)

    register_via_ui(browser, live_server, "pollbob")
    poll_root = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-poll]"))
    )
    cats_button = poll_root.find_element(By.CSS_SELECTOR, ".poll-choice")
    assert cats_button.text == "Cats"
    cats_button.click()

    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".poll-bar-fill"))
    )
    WebDriverWait(browser, 10).until(
        EC.text_to_be_present_in_element((By.CSS_SELECTOR, ".poll-meta"), "100")
    )
    assert poll_root.find_elements(By.CSS_SELECTOR, ".poll-choice") == []
    assert "1 vote" in poll_root.find_element(By.CSS_SELECTOR, ".poll-total").text


@pytest.mark.ui
def test_second_voter_updates_split_percentages(browser, live_server):
    register_via_ui(browser, live_server, "voterone")
    create_poll_via_ui(browser, "Best fruit?", ["Apple", "Banana"])
    logout_via_ui(browser)

    register_via_ui(browser, live_server, "votertwo")
    poll_root = browser.find_element(By.CSS_SELECTOR, "[data-poll]")
    poll_root.find_element(By.CSS_SELECTOR, ".poll-choice").click()
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".poll-bar-fill"))
    )
    logout_via_ui(browser)

    login_via_ui(browser, live_server, "voterone")
    browser.get(f"{live_server}/")
    wait_for_text(browser, "Best fruit?")
    poll_root = browser.find_element(By.CSS_SELECTOR, "[data-poll]")
    assert len(poll_root.find_elements(By.CSS_SELECTOR, ".poll-choice")) == 2

    poll_root.find_elements(By.CSS_SELECTOR, ".poll-choice")[1].click()
    WebDriverWait(browser, 10).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, ".poll-meta")) == 2
    )
    metas = [element.text for element in browser.find_elements(By.CSS_SELECTOR, ".poll-meta")]
    assert any("50" in meta for meta in metas)
    assert "2 votes" in poll_root.find_element(By.CSS_SELECTOR, ".poll-total").text


@pytest.mark.ui
def test_following_user_adds_their_posts_to_feed(browser, live_server):
    register_via_ui(browser, live_server, "bob")
    composer = browser.find_element(By.CSS_SELECTOR, "form.composer")
    set_field_value(browser, composer.find_element(By.NAME, "body"), "Bob browser update")
    submit_form(browser, composer)
    wait_for_text(browser, "Bob browser update")
    logout_via_ui(browser)

    register_via_ui(browser, live_server, "alice")
    assert "Bob browser update" not in browser.find_element(By.TAG_NAME, "body").text

    browser.get(f"{live_server}/explore")
    wait_for_text(browser, "@bob")
    submit_form(browser, browser.find_element(By.CSS_SELECTOR, ".user-row form"))
    wait_for_text(browser, "Unfollow")

    browser.get(f"{live_server}/")
    wait_for_text(browser, "Bob browser update")


# ---------------------------------------------------------------------------
# CAPTCHA E2E fixtures: separate live server with real captcha validation
# ---------------------------------------------------------------------------

_CAPTCHA_FORCE = "TESTX"


@pytest.fixture(scope="module")
def captcha_ui_app():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-captcha",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{temp_path / 'captcha_ui.sqlite'}",
                "UPLOAD_FOLDER": str(temp_path / "uploads"),
                "MEDIA_STORAGE_BACKEND": "local",
                "WTF_CSRF_ENABLED": False,
                "CAPTCHA_FORCE_TEXT": _CAPTCHA_FORCE,
            }
        )
        with app.app_context():
            db.create_all()
        yield app


@pytest.fixture(scope="module")
def captcha_live_server(captcha_ui_app):
    try:
        server = make_server("127.0.0.1", 0, captcha_ui_app, threaded=True)
    except SystemExit:
        pytest.skip("Captcha live server could not bind to a local port")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{server.server_port}"

    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture(autouse=False)
def clean_captcha_database(captcha_ui_app):
    with captcha_ui_app.app_context():
        db.session.query(Comment).delete()
        db.session.query(PollVote).delete()
        db.session.query(PollOption).delete()
        db.session.query(Poll).delete()
        db.session.query(Post).delete()
        db.session.query(User).delete()
        db.session.commit()
    yield


# ---------------------------------------------------------------------------
# CAPTCHA E2E Tests
# ---------------------------------------------------------------------------


@pytest.mark.ui
def test_captcha_image_is_displayed_on_register_page(browser, live_server):
    """The register page must show a CAPTCHA image and refresh button."""
    browser.get(f"{live_server}/auth/register")
    WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.ID, "captcha-img"))
    )
    img = browser.find_element(By.ID, "captcha-img")
    assert img.is_displayed()
    refresh_btn = browser.find_element(By.ID, "refresh-captcha")
    assert refresh_btn.is_displayed()


@pytest.mark.ui
def test_captcha_refresh_button_reloads_image(browser, live_server):
    """Clicking the refresh button changes the captcha image src."""
    browser.get(f"{live_server}/auth/register")
    WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.ID, "captcha-img")))
    img = browser.find_element(By.ID, "captcha-img")
    original_src = img.get_attribute("src")

    browser.find_element(By.ID, "refresh-captcha").click()
    WebDriverWait(browser, 5).until(
        lambda d: d.find_element(By.ID, "captcha-img").get_attribute("src") != original_src
    )
    new_src = browser.find_element(By.ID, "captcha-img").get_attribute("src")
    assert new_src != original_src


def wait_for_captcha_image_loaded(browser):
    """Wait until the CAPTCHA image has fully loaded and the server session is seeded."""
    WebDriverWait(browser, 10).until(
        lambda d: d.execute_script(
            "var img = document.getElementById('captcha-img');"
            "return img && img.complete && img.naturalWidth > 0;"
        )
    )


@pytest.mark.ui
def test_register_with_correct_captcha_succeeds(browser, captcha_live_server, clean_captcha_database):
    """Submitting the correct CAPTCHA allows registration to complete."""
    browser.get(f"{captcha_live_server}/auth/register")
    form = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.form-stack"))
    )
    wait_for_captcha_image_loaded(browser)

    set_field_value(browser, form.find_element(By.NAME, "username"), "captchauser")
    set_field_value(browser, form.find_element(By.NAME, "email"), "captchauser@example.com")
    set_field_value(browser, form.find_element(By.NAME, "password"), "password")
    set_field_value(browser, form.find_element(By.NAME, "captcha"), _CAPTCHA_FORCE)
    submit_form(browser, form)
    wait_for_feed(browser)


@pytest.mark.ui
def test_register_with_wrong_captcha_shows_error(browser, captcha_live_server, clean_captcha_database):
    """Submitting a wrong CAPTCHA keeps the user on the register page with an error."""
    browser.get(f"{captcha_live_server}/auth/register")
    form = WebDriverWait(browser, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.form-stack"))
    )
    wait_for_captcha_image_loaded(browser)

    set_field_value(browser, form.find_element(By.NAME, "username"), "captchauser2")
    set_field_value(browser, form.find_element(By.NAME, "email"), "captchauser2@example.com")
    set_field_value(browser, form.find_element(By.NAME, "password"), "password")
    set_field_value(browser, form.find_element(By.NAME, "captcha"), "WRONG")
    submit_form(browser, form)

    WebDriverWait(browser, 5).until(
        EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Incorrect CAPTCHA")
    )
    assert "register" in browser.current_url
