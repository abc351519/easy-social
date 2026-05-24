(function () {
  function mediaKind(file) {
    if (file.type.startsWith("image/")) {
      return "image";
    }
    if (file.type.startsWith("video/")) {
      return "video";
    }

    const extension = file.name.split(".").pop().toLowerCase();
    if (["gif", "jpg", "jpeg", "png", "webp"].includes(extension)) {
      return "image";
    }
    if (["mov", "mp4", "ogg", "webm"].includes(extension)) {
      return "video";
    }
    return "";
  }

  function clearPreview(preview, frame, name, input, state) {
    if (state.objectUrl) {
      URL.revokeObjectURL(state.objectUrl);
      state.objectUrl = "";
    }
    frame.replaceChildren();
    name.textContent = "";
    preview.hidden = true;
    if (input) {
      input.value = "";
    }
  }

  function setupComposer(composer) {
    const input = composer.querySelector("[data-media-input]");
    const preview = composer.querySelector("[data-media-preview]");
    const frame = composer.querySelector("[data-media-preview-frame]");
    const name = composer.querySelector("[data-media-preview-name]");
    const clear = composer.querySelector("[data-media-preview-clear]");

    if (!input || !preview || !frame || !name || !clear) {
      return;
    }

    const state = { objectUrl: "" };

    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      clearPreview(preview, frame, name, null, state);

      if (!file) {
        return;
      }

      const kind = mediaKind(file);
      if (!kind) {
        return;
      }

      state.objectUrl = URL.createObjectURL(file);
      const element = document.createElement(kind === "image" ? "img" : "video");
      element.className = "composer-preview-media";
      element.src = state.objectUrl;

      if (kind === "image") {
        element.alt = "Selected image preview";
      } else {
        element.controls = true;
        element.muted = true;
        element.preload = "metadata";
      }

      frame.replaceChildren(element);
      name.textContent = file.name;
      preview.hidden = false;
    });

    clear.addEventListener("click", function () {
      clearPreview(preview, frame, name, input, state);
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  function setupComposerMode(composer) {
    const typeInputs = composer.querySelectorAll("[data-post-type-input]");
    const pollFields = composer.querySelector("[data-poll-fields]");
    const mediaPicker = composer.querySelector("[data-media-picker]");
    const body = composer.querySelector("[data-composer-body]");
    const submit = composer.querySelector("[data-composer-submit]");

    if (!typeInputs.length || !pollFields || !body || !submit) {
      return;
    }

    function syncMode() {
      const isPoll = composer.querySelector('[name="post_type"]:checked')?.value === "poll";
      pollFields.hidden = !isPoll;
      if (mediaPicker) {
        mediaPicker.hidden = isPoll;
      }
      body.placeholder = isPoll ? "Ask a question for your poll" : "What is happening?";
      submit.textContent = isPoll ? "Create poll" : "Post";
    }

    typeInputs.forEach(function (input) {
      input.addEventListener("change", syncMode);
    });
    syncMode();
  }

  function renderPollResults(pollRoot, payload) {
    const optionsRoot = pollRoot.querySelector(".poll-options");
    if (!optionsRoot) {
      return;
    }

    optionsRoot.replaceChildren();
    payload.options.forEach(function (option) {
      const wrapper = document.createElement("div");
      wrapper.className = "poll-option is-results";
      if (payload.user_vote_option_id === option.id) {
        wrapper.classList.add("is-selected");
      }
      wrapper.dataset.optionId = String(option.id);

      const result = document.createElement("div");
      result.className = "poll-result";

      const header = document.createElement("div");
      header.className = "poll-result-header";

      const label = document.createElement("span");
      label.className = "poll-label";
      label.textContent = option.label;

      const meta = document.createElement("span");
      meta.className = "poll-meta";
      const voteLabel = option.vote_count === 1 ? "vote" : "votes";
      meta.textContent = option.percentage + "% · " + option.vote_count + " " + voteLabel;

      const track = document.createElement("div");
      track.className = "poll-bar-track";
      const fill = document.createElement("div");
      fill.className = "poll-bar-fill";
      fill.style.width = option.percentage + "%";

      header.append(label, meta);
      track.append(fill);
      result.append(header, track);
      wrapper.append(result);
      optionsRoot.append(wrapper);
    });

    const total = pollRoot.querySelector(".poll-total");
    if (total) {
      const voteLabel = payload.total_votes === 1 ? "vote" : "votes";
      total.textContent = payload.total_votes + " " + voteLabel;
    }
  }

  function setupPollVoting() {
    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.classList.contains("poll-vote-form")) {
        return;
      }

      const pollRoot = form.closest("[data-poll]");
      if (!pollRoot) {
        return;
      }

      event.preventDefault();
      const optionId = form.querySelector('input[name="option_id"]')?.value;
      if (!optionId) {
        return;
      }

      const submitButton = form.querySelector("button[type='submit']");
      if (submitButton) {
        submitButton.disabled = true;
      }

      fetch(form.action, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({ option_id: optionId }),
      })
        .then(function (response) {
          return response.json().then(function (payload) {
            if (!response.ok) {
              throw new Error(payload.error || "Vote failed.");
            }
            return payload;
          });
        })
        .then(function (payload) {
          renderPollResults(pollRoot, payload);
        })
        .catch(function (error) {
          window.alert(error.message);
          if (submitButton) {
            submitButton.disabled = false;
          }
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form.composer").forEach(function (composer) {
      setupComposer(composer);
      setupComposerMode(composer);
    });
    setupPollVoting();
  });
})();
