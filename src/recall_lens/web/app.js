// RecallLens web client: sends a check to the API and renders its event stream.

const STEPS = {
  perceive: "Read the photo",
  retake: "Took your new photo or description",
  identify: "Picked out brands and codes",
  retrieve: "Searched the recall notices",
  verify: "Compared your product with each recall",
  arbitrate: "Asked Claude about unclear matches",
  advise: "Wrote the answer",
};

const $ = (id) => document.getElementById(id);
const MAX_SIDE = 2048; // the server reads photos at this size; larger only slows the upload
let photo = null; // base64 JPEG of the chosen photo
let paused = null; // id of a check waiting for a clearer photo or a description
let finished = null; // id of the check whose answer is shown, which can be watched
let watched = null; // token of the watched product on screen

// Server-sent events of a fetch response, as {event, data}; keep-alive comments are skipped.
async function* events(response) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    for (let end; (end = buffer.indexOf("\n\n")) >= 0; buffer = buffer.slice(end + 2)) {
      const block = buffer.slice(0, end);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (event && data) yield { event, data: JSON.parse(data) };
    }
  }
}

function addStep(node, update) {
  const item = document.createElement("li");
  item.textContent = STEPS[node] ?? node;
  let detail = "";
  if (node === "identify" && update?.codes?.length) detail = `Codes: ${update.codes.join(", ")}`;
  if (node === "retrieve") detail = `${update?.candidates?.length ?? 0} closest recalls`;
  if (node === "perceive" && update?.photo_error) detail = update.photo_error;
  if (detail) item.append(Object.assign(document.createElement("small"), { textContent: detail }));
  $("steps").append(item);
}

// One line of the server's answer; all text goes in as text, never as HTML.
function line(text) {
  const quote = /^The notice says: "(.*)"$/.exec(text);
  const element = document.createElement(quote ? "blockquote" : "p");
  if (/^https?:\/\/\S+$/.test(text)) {
    const link = Object.assign(document.createElement("a"), {
      href: text, textContent: "Read the official notice", target: "_blank", rel: "noopener",
    });
    element.append(link);
  } else {
    element.textContent = quote ? quote[1] : text;
  }
  return element;
}

function showAnswer(verdict, message) {
  const [headline, ...rest] = message.split("\n");
  $("verdict").textContent = headline;
  $("verdict").dataset.verdict = verdict;
  $("message").replaceChildren(...rest.map(line));
  showWatch(null);
  $("answer").hidden = false;
  $("answer").focus();
}

// The watch controls: the form for a finished check, or "stop" for a watched product.
function showWatch(token, note = "") {
  watched = token;
  $("watch").hidden = token !== null || finished === null;
  $("stop").hidden = token === null;
  $("watching").textContent = note;
}

// What the server said went wrong, in its words when it gave any.
async function problem(response) {
  const body = await response.json().catch(() => ({}));
  return typeof body.detail === "string" ? body.detail : `The server answered ${response.status}.`;
}

// The photo as a JPEG data URL, upright and at most MAX_SIDE on its longer side.
async function shrink(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = Object.assign(document.createElement("canvas"), {
    width: Math.round(bitmap.width * scale),
    height: Math.round(bitmap.height * scale),
  });
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.9);
}

function setPhoto(dataUrl) {
  photo = dataUrl ? dataUrl.split(",")[1] : null;
  $("thumb").src = dataUrl ?? "";
  $("preview").hidden = !dataUrl;
  $("photo").value = "";
}

async function run(url, body) {
  $("submit").disabled = true;
  $("steps").replaceChildren();
  $("progress").hidden = false;
  $("answer").hidden = true;
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`The server answered ${response.status}.`);
    let check = paused;
    paused = finished = null;
    for await (const { event, data } of events(response)) {
      if (event === "check") check = data.id;
      if (event === "progress") addStep(data.node, data.update);
      if (event === "answer") {
        finished = check;
        showAnswer(data.verdict, data.message);
      }
      if (event === "error") throw new Error(data.message);
      if (event === "question") {
        paused = check; // the next photo or description resumes this check
        showAnswer("needs_info", `${data.reason}\n${data.question}`);
      }
    }
    $("submit").textContent = paused ? "Try again" : "Check";
  } catch (error) {
    showAnswer("error", `The check did not finish.\n${error.message}`);
  } finally {
    $("submit").disabled = false;
  }
}

$("photo").addEventListener("change", async () => {
  const [file] = $("photo").files;
  if (!file) return;
  try {
    setPhoto(await shrink(file));
    $("notice").textContent = "";
  } catch {
    setPhoto(null);
    $("notice").textContent = "That file could not be read as a photo. Try a JPEG or PNG.";
  }
});

$("clear").addEventListener("click", () => setPhoto(null));

$("check").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("query").value.trim();
  if (!query && !photo) {
    $("notice").textContent = "Describe the product or add a photo of its label.";
    return $("query").focus();
  }
  $("notice").textContent = "";
  await run(paused ? `checks/${paused}/resume` : "checks", { query, photo });
  setPhoto(null); // sent once; the server keeps no copy either
  if (paused) $("query").value = ""; // what comes next is added to the description
});

$("watch").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = $("email").value.trim();
  const response = await fetch(`checks/${finished}/watch`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  }).catch(() => null);
  if (response?.ok) {
    const { token } = await response.json();
    showWatch(token, `Watching. We will email ${email} if a recall covers this product.`);
  } else {
    $("watching").textContent = response ? await problem(response) : "The server did not answer.";
  }
});

$("stop").addEventListener("click", async () => {
  const response = await fetch(`watches/${watched}`, { method: "DELETE" }).catch(() => null);
  if (!response?.ok) {
    $("watching").textContent = response ? await problem(response) : "The server did not answer.";
    return;
  }
  if (!finished) $("verdict").textContent = "Stopped watching."; // opened from an email's link
  showWatch(null, "Stopped. You will get no more emails about this product.");
});

// An alert email links here with ?stop=<token> to end the watch on its product.
async function offerStop(token) {
  history.replaceState(null, "", location.pathname); // keep the token out of the address bar
  const response = await fetch(`watches/${token}`).catch(() => null);
  if (!response?.ok) return showAnswer("error", "This product is no longer watched.");
  const { product } = await response.json();
  showAnswer("needs_info", `Stop watching this product?\n${product}`);
  showWatch(token);
}

$("again").addEventListener("click", () => {
  $("answer").hidden = $("progress").hidden = true;
  paused = finished = null;
  $("submit").textContent = "Check";
  $("query").value = "";
  setPhoto(null);
  $("query").focus();
});

const stop = new URLSearchParams(location.search).get("stop");
if (stop) offerStop(stop);

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
