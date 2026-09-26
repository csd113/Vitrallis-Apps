"use strict";
const $ = id => document.getElementById(id);
const CONVERTIBLE = new Set(["gif", "png", "jpeg"]);
const TERMINAL_JOB_STATES = new Set(["completed", "failed", "cancelled"]);
let previewURLs = [], previewQueue = [], previewActive = 0;
let token = "", state = null, selected = null, uploading = false, busy = false;
let conversionTimer = null, jobDismissed = 0;

try { token = sessionStorage.getItem("carousel-code") || ""; } catch (_) { /* Private mode may deny storage. */ }

function notice(message, kind = "") {
  const node = $("notice");
  node.textContent = message;
  node.classList.toggle("error", kind === "error");
  node.classList.toggle("success", kind === "success");
}
function lock() {
  token = ""; state = null; selected = null;
  clearTimeout(conversionTimer); conversionTimer = null;
  previewObserver.disconnect(); previewQueue = [];
  previewURLs.forEach(url => URL.revokeObjectURL(url)); previewURLs = [];
  $("media").replaceChildren();
  try { sessionStorage.removeItem("carousel-code"); } catch (_) { /* In-memory access still works. */ }
  $("workspace").hidden = true; $("login").hidden = false;
  $("connection").textContent = "Locked"; $("connection").className = "badge badge-quiet";
  $("job").hidden = true; $("footer-state").textContent = "Local media. No cloud.";
}
async function api(path, method = "GET", body) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      method,
      headers: {Authorization: `Bearer ${token}`, ...(body ? {"Content-Type": "application/json"} : {})},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal
    });
    const data = await response.json();
    if (response.status === 401) lock();
    if (!response.ok) throw new Error(data.error || "Request failed");
    return data;
  } finally { clearTimeout(timer); }
}
function guarded(action) {
  return async event => {
    if (event) event.preventDefault();
    if (busy) return;
    busy = true;
    try { await action(event); }
    catch (error) { notice(error.message || "Device unavailable. Check the connection.", "error"); }
    finally { busy = false; }
  };
}
function show(view) {
  for (const name of ["collections", "folder", "convert", "settings"]) {
    $(name + "-view").hidden = name !== view;
  }
  $("collections-tab").classList.toggle("active", view === "collections" || view === "folder");
  $("convert-tab").classList.toggle("active", view === "convert");
  $("settings-tab").classList.toggle("active", view === "settings");
  $("collections-tab").removeAttribute("aria-current");
  $("convert-tab").removeAttribute("aria-current");
  $("settings-tab").removeAttribute("aria-current");
  if (view === "collections" || view === "folder") $("collections-tab").setAttribute("aria-current", "page");
  else if (view === "convert") $("convert-tab").setAttribute("aria-current", "page");
  else $("settings-tab").setAttribute("aria-current", "page");
}
function button(text, label, action, className = "secondary") {
  const node = document.createElement("button");
  node.type = "button"; node.textContent = text;
  node.setAttribute("aria-label", label); node.className = className;
  node.addEventListener("click", guarded(action));
  return node;
}
function text(tag, content, className = "") {
  const node = document.createElement(tag);
  node.textContent = content;
  if (className) node.className = className;
  return node;
}

/* ---------------------------------------------------------------- collections */

function renderCollections() {
  const list = $("collections");
  list.replaceChildren();
  if (!state.collections.length) {
    list.append(text("p", "No collections yet. Create one to start uploading.", "empty"));
    return;
  }
  for (const folder of state.collections) {
    const card = button("", `Open ${folder.name}`, () => openFolder(folder.id), "collection");
    const symbol = text("span", "▱", "folder-symbol");
    symbol.setAttribute("aria-hidden", "true");
    const name = text("span", folder.name, "name");
    const convertible = folder.items.filter(item => CONVERTIBLE.has(item.kind)).length;
    const count = text("small", `${folder.items.length} ${folder.items.length === 1 ? "item" : "items"}` +
      (convertible ? ` · ${convertible} convertible` : "") + "  →");
    card.append(symbol, name, count);
    list.append(card);
  }
}
function folder() { return state.collections.find(row => row.id === selected); }
function openFolder(id) { selected = id; renderFolder(); show("folder"); }

/* ---------------------------------------------------------------- conversion */

function conversionJob() { return (state && state.conversion && state.conversion.job) || {}; }
function conversionRunning() {
  const status = conversionJob().status;
  return status === "running" || status === "queued";
}
function renderConversion() {
  const job = conversionJob();
  const active = conversionRunning();
  const finished = TERMINAL_JOB_STATES.has(job.status);
  const panel = $("job");
  const visible = job.id && job.id !== jobDismissed && (active || finished);
  panel.hidden = !visible;
  $("convert-empty").hidden = !!active;
  if (!visible) return;

  const total = job.total || 0;
  const done = job.completed || 0, failed = job.failed || 0, skipped = job.skipped || 0;
  const handled = done + failed + skipped;
  const labels = {queued: "Queued", running: "Converting", completed: "Finished",
                  failed: "Failed", cancelled: "Cancelled"};
  $("job-state").textContent = labels[job.status] || "Converting";
  $("job-state").className = "badge" + (job.status === "failed" ? " badge-danger"
    : (active ? "" : " badge-quiet"));
  $("job-scope").textContent = [job.scope_name || (job.all ? "All collections" : ""),
                                job.kinds && job.kinds.length ? job.kinds.join(" + ") : "",
                                job.converter ? "via " + job.converter : ""]
    .filter(Boolean).join(" · ");
  $("job-progress").value = total ? Math.round(handled / total * 100) : 0;
  $("job-line").textContent = total
    ? `${handled} of ${total} checked${job.current ? ` · ${job.current}` : ""}`
    : (job.message || "");
  $("job-total").textContent = total;
  $("job-done").textContent = done;
  $("job-failed").textContent = failed;
  $("job-skipped").textContent = skipped;
  $("job-message").textContent = job.message || (job.truncated
    ? `${job.truncated} further results not listed.` : "");
  $("job-cancel").hidden = !active;
  const problems = (job.results || []).filter(row => row.status === "failed");
  $("job-details").hidden = problems.length === 0;
  $("job-details-summary").textContent = `${problems.length} could not be converted`;
  const failures = $("job-failures");
  failures.replaceChildren();
  for (const row of problems.slice(0, 40)) {
    failures.append(text("li", `${row.name}: ${row.message || "conversion failed"}`));
  }
}
function scheduleConversionPoll() {
  if (conversionTimer) return;
  conversionTimer = setTimeout(async () => {
    conversionTimer = null;
    try {
      await refresh();
      if (conversionRunning()) { scheduleConversionPoll(); return; }
      const job = conversionJob();
      if (job.status === "completed") {
        notice(`Conversion finished · ${job.message || ""}`.trim(), "success");
      } else if (job.status === "failed" || job.status === "cancelled") {
        notice(job.message || "Conversion stopped.", job.status === "failed" ? "error" : "");
      }
    } catch (error) { notice(error.message || "Device unavailable. Check the connection.", "error"); }
  }, 1200);
}
async function startConversion(kinds, scope, collection, replace) {
  if (conversionRunning()) { notice("A conversion is already running.", "error"); return; }
  notice("Starting conversion…");
  await api("/api/convert", "POST", {scope, collection, kinds, replace});
  jobDismissed = 0;
  await refresh();
  renderConversion();
  scheduleConversionPoll();
}
function scopeSelect() {
  const select = $("library-scope");
  const previous = select.value;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "all"; all.textContent = `All collections (${state.collections.length})`;
  select.append(all);
  for (const row of state.collections) {
    const option = document.createElement("option");
    option.value = row.id;
    option.textContent = `${row.name} (${row.items.length})`;
    select.append(option);
  }
  select.value = previous && [...select.options].some(option => option.value === previous)
    ? previous : "all";
}
async function convertItem(item) {
  state.conversion = await api(`/api/collections/${selected}/media/${item.id}/convert`, "POST");
  jobDismissed = 0;
  notice(state.conversion.message || "Converting…");
  renderFolder(); renderConversion(); scheduleConversionPoll();
}

/* ---------------------------------------------------------------- folder view */

function renderFolder() {
  const row = folder();
  if (!row) { selected = null; show("collections"); return; }
  $("folder-title").textContent = row.name;
  const convertible = row.items.filter(item => CONVERTIBLE.has(item.kind)).length;
  const animation = row.items.filter(item => item.animated).length;
  $("folder-summary").textContent = `${row.items.length} ${row.items.length === 1 ? "item" : "items"}` +
    ` · ${animation} animated · ${convertible} convertible to WebP`;
  $("item-count").textContent = `· ${row.items.length}`;
  $("convert-hint").textContent = convertible
    ? `${convertible} of ${row.items.length} items would convert.`
    : "Nothing in this collection needs converting.";
  for (const node of document.querySelectorAll("#folder-view [data-kinds]")) {
    node.disabled = convertible === 0 || conversionRunning() || uploading;
  }
  previewURLs.forEach(url => URL.revokeObjectURL(url)); previewURLs = [];
  previewQueue = []; previewObserver.disconnect();
  $("media").replaceChildren();
  if (!row.items.length) {
    $("media").append(text("p", "Nothing here yet. Add a few files above to begin.", "empty"));
    return;
  }
  row.items.forEach((item, index) => {
    const li = document.createElement("li");
    const position = text("span", String(index + 1), "order-index");
    position.setAttribute("aria-hidden", "true");
    const details = document.createElement("div");
    details.className = "details";
    const name = text("span", item.name, "filename");
    name.title = item.name;
    const meta = text("small", `${item.kind.toUpperCase()}` +
      (item.animated ? " · animated" : "") +
      ` · ${(item.size / 1024 / 1024).toFixed(2)} MiB`);
    meta.className = "meta";
    details.append(name, meta);
    const controls = document.createElement("div");
    controls.className = "actions";
    const up = button("↑", `Move ${item.name} earlier`, () => move(index, -1));
    up.disabled = index === 0 || uploading;
    const down = button("↓", `Move ${item.name} later`, () => move(index, 1));
    down.disabled = index === row.items.length - 1 || uploading;
    const remove = button("Delete", `Delete ${item.name}`, async () => {
      if (!confirm(`Delete “${item.name}” from this device?`)) return;
      await api(`/api/collections/${selected}/media/${item.id}`, "DELETE");
      await refresh(); notice("File deleted.", "success");
    }, "danger");
    remove.disabled = uploading;
    const buttons = [up, down];
    if (CONVERTIBLE.has(item.kind)) {
      const convert = button("To WebP", `Convert ${item.name} to WebP`, () => convertItem(item));
      convert.disabled = uploading || conversionRunning();
      buttons.push(convert);
    }
    buttons.push(remove);
    const preview = document.createElement("img");
    preview.className = "thumbnail";
    preview.alt = `${item.kind.toUpperCase()} preview of ${item.name}`;
    preview.width = 128; preview.height = 80;
    preview.loading = "lazy";
    controls.append(...buttons);
    li.append(position, preview, details, controls);
    $("media").append(li);
    preview.dataset.path = `/api/collections/${row.id}/media/${item.id}/thumbnail`;
    previewObserver.observe(preview);
  });
}
const previewObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) { previewObserver.unobserve(entry.target); previewQueue.push(entry.target); }
  });
  loadPreviews();
}, {rootMargin: "100px"});
async function binary(path, timeout = 15000) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {headers: {Authorization: `Bearer ${token}`}, signal: controller.signal});
    if (response.status === 401) lock();
    if (!response.ok) {
      let message = "Download failed";
      try { message = (await response.json()).error || message; } catch (_) { /* Non-JSON body. */ }
      throw new Error(message);
    }
    return await response.blob();
  } finally { clearTimeout(timer); }
}
function loadPreviews() {
  while (previewActive < 2 && previewQueue.length) {
    const image = previewQueue.shift();
    if (!image.isConnected) continue;
    previewActive++;
    binary(image.dataset.path).then(blob => {
      if (!image.isConnected) return;
      const url = URL.createObjectURL(blob);
      previewURLs.push(url); image.src = url;
    }).catch(() => { image.alt = "Preview unavailable"; })
      .finally(() => { previewActive--; loadPreviews(); });
  }
}
async function move(index, direction) {
  const ids = folder().items.map(item => item.id);
  [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
  await api(`/api/collections/${selected}/order`, "PUT", {ids});
  await refresh();
  const control = $("media").children[index + direction]?.querySelectorAll("button")[direction < 0 ? 0 : 1];
  if (control && !control.disabled) control.focus();
  notice("Play order saved.", "success");
}

/* ---------------------------------------------------------------- uploads */

function sendFile(file, cid, progress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/collections/${cid}/media?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.timeout = 160000;
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(event.loaded, event.total); };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status === 401) lock();
        if (xhr.status !== 201) throw new Error(data.error || "Upload failed");
        resolve(data);
      } catch (error) { reject(error); }
    };
    xhr.onerror = () => reject(new Error("Connection lost during upload"));
    xhr.ontimeout = () => reject(new Error("Upload timed out"));
    xhr.send(file);
  });
}
async function upload(files) {
  if (uploading || !selected || !files.length) return;
  $("progress").value = 0;
  uploading = true;
  const cid = selected;
  $("files").disabled = true;
  $("delete-folder").disabled = true;
  // A conversion started during an upload would compete for CPU with two media
  // validations, so hold every bulk action until the batch finishes.
  for (const node of document.querySelectorAll("#convert-view [data-kinds]")) node.disabled = true;
  $("upload-status").hidden = false;
  $("upload-results").replaceChildren();
  renderFolder();
  let success = 0, expired = false;
  // Retain at most 100 File references/results per batch; library limits stay server enforced.
  const batch = Array.from(files).slice(0, 100);
  try {
    const loaded = batch.map(() => 0);
    const totalBytes = batch.reduce((sum, file) => sum + file.size, 0);
    let next = 0, finished = 0;
    const rows = batch.map(file => {
      const row = document.createElement("li");
      row.textContent = `${file.name}: queued`;
      row.title = file.name;
      $("upload-results").append(row);
      return row;
    });
    const worker = async () => {
      while (next < batch.length && token) {
        const index = next++;
        const file = batch[index], result = rows[index];
        try {
          if (file.size === 0) throw new Error("empty file · not sent");
          if (file.size > state.max_upload) throw new Error("Over the 64 MiB limit");
          result.textContent = `${file.name}: uploading`;
          await sendFile(file, cid, (bytes, total) => {
            loaded[index] = bytes;
            $("progress").value = totalBytes
              ? loaded.reduce((sum, value) => sum + value, 0) / totalBytes * 100 : 0;
            result.textContent = `${file.name}: ${bytes === total ? "checking media…"
              : Math.round(bytes / total * 100) + "%"}`;
          });
          result.textContent = `${file.name}: saved`;
          success++;
        } catch (error) { result.textContent = `${file.name}: ${error.message}`; }
        finished++;
        $("upload-label").textContent =
          `${finished}/${batch.length} files checked · ${success} saved`;
      }
    };
    // Two transfers overlap; the server serializes expensive media validation.
    await Promise.all([worker(), worker()]);
    expired = !token;
    if (expired) {
      for (const row of rows) {
        if (row.textContent.endsWith(": queued")) {
          row.textContent = `${row.title}: not uploaded · session expired`;
        }
      }
      notice(`Session expired. ${batch.length - success} of ${batch.length} files were not uploaded. ` +
        "Reconnect with the code shown on the device.", "error");
    } else {
      await refresh();
      notice(`${success} of ${batch.length} files saved.` +
        (files.length > 100 ? " Select remaining files in another batch (100 maximum)." : ""),
        success === batch.length ? "success" : "error");
    }
  } catch (error) { notice(error.message, "error"); }
  finally {
    uploading = false;
    $("files").disabled = false;
    $("delete-folder").disabled = false;
    for (const node of document.querySelectorAll("#convert-view [data-kinds]")) node.disabled = false;
    $("files").value = "";
    $("upload-label").textContent = expired ? "Session expired" : "Batch finished";
    if (state && selected) renderFolder();
  }
}
function folderArchive(path) {
  // XHR keeps progress events and, with no timeout, supports multi-gigabyte archives.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", path); xhr.responseType = "blob"; xhr.timeout = 0;
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.onprogress = event => notice(`Downloading… ${(event.loaded / 1048576).toFixed(1)} MiB`);
    xhr.onload = async () => {
      if (xhr.status === 401) lock();
      if (xhr.status !== 200) {
        let message = "Download failed";
        try { message = JSON.parse(await xhr.response.text()).error || message; } catch (_) { /* raw body */ }
        reject(new Error(message));
        return;
      }
      resolve(xhr.response);
    };
    xhr.onerror = () => reject(new Error("Connection lost during download"));
    xhr.ontimeout = () => reject(new Error("Download timed out"));
    xhr.send();
  });
}

/* ---------------------------------------------------------------- state */

function serverBadge() {
  const server = (state && state.server) || {};
  const node = $("connection");
  if (server.state === "failed") {
    node.textContent = "Management UI unavailable";
    node.className = "badge badge-danger";
  } else if (server.state === "starting") {
    node.textContent = "Starting management UI…";
    node.className = "badge badge-warn";
  } else {
    node.textContent = server.detail || "Ready";
    node.className = "badge badge-quiet";
  }
  $("footer-state").textContent = server.state === "failed"
    ? "Slideshow keeps playing without the management UI."
    : "Local media. No cloud.";
}
function accelerationText() {
  const acceleration = (state.capabilities && state.capabilities.acceleration) || {};
  const codecs = Object.entries(acceleration.codecs || {})
    .map(([codec, backend]) => `${codec.toUpperCase()} ${backend.verified ? backend.method : "software"}`);
  if (!codecs.length) return "";
  return `Decoder backends: ${codecs.join(" · ")}. Policy: ${acceleration.policy || "auto"}.`;
}
async function refresh() {
  state = await api("/api/state");
  $("workspace").hidden = false;
  $("login").hidden = true;
  serverBadge();
  $("device").textContent = `${state.device} · ${state.urls.join(" · ")}`;
  $("decoder-note").textContent =
    `${state.capabilities.webm ? "WebM decoder available." : "WebM unavailable."} ${state.capabilities.webm_note}`;
  $("acceleration-note").textContent = accelerationText();
  $("install-media").hidden = state.capabilities.ready;
  $("install-media").disabled = state.installation.status === "running" || !state.installation.available;
  $("install-status").textContent = state.installation.message ||
    (!state.capabilities.ready && !state.installation.available
      ? "Administrator setup is required to enable installation." : "");
  scopeSelect();
  renderCollections();
  if (selected) renderFolder();
  renderConversion();
  if (conversionRunning()) scheduleConversionPoll();
  if (state.warning) notice(state.warning, "error");
}
function renderSettings() {
  const config = state.settings;
  $("image-seconds").value = config.image_seconds;
  $("repeats").value = config.repeats;
  $("order").value = config.order;
  $("loop").value = String(config.loop);
  $("convert-gifs").value = String(config.convert_gifs);
  show("settings");
}

/* ---------------------------------------------------------------- wiring */

$("login-form").onsubmit = guarded(async () => {
  token = $("access-code").value.trim().toLowerCase();
  await refresh();
  try { sessionStorage.setItem("carousel-code", token); } catch (_) { /* Optional browser storage. */ }
  $("access-code").value = "";
  notice("");
  show("collections");
});
$("lock").onclick = () => {
  if (!uploading) lock(); else notice("Wait for the current batch to finish.", "error");
};
$("collections-tab").onclick = () => show(selected ? "folder" : "collections");
$("convert-tab").onclick = guarded(async () => { await refresh(); show("convert"); });
$("settings-tab").onclick = guarded(async () => { await refresh(); renderSettings(); });
$("refresh").onclick = guarded(() => refresh());
$("back").onclick = () => { selected = null; show("collections"); };
$("create-form").onsubmit = guarded(async () => {
  const row = await api("/api/collections", "POST", {name: $("collection-name").value});
  $("collection-name").value = "";
  await refresh(); openFolder(row.id); notice("Collection created.", "success");
});
$("rename").onclick = () => {
  $("rename-name").value = folder().name;
  $("rename-form").hidden = false;
  $("rename-name").focus();
};
$("cancel-rename").onclick = () => { $("rename-form").hidden = true; $("rename").focus(); };
$("rename-form").onsubmit = guarded(async () => {
  await api(`/api/collections/${selected}`, "PUT", {name: $("rename-name").value});
  $("rename-form").hidden = true; await refresh(); notice("Collection renamed.", "success");
});
$("delete-folder").onclick = guarded(async () => {
  if (!confirm(`Delete “${folder().name}” and ALL of its media from this device?`)) return;
  await api(`/api/collections/${selected}`, "DELETE");
  selected = null; await refresh(); show("collections"); notice("Collection deleted.", "success");
});
$("settings-form").onsubmit = guarded(async () => {
  await api("/api/settings", "PUT", {
    image_seconds: Number($("image-seconds").value),
    repeats: Number($("repeats").value),
    order: $("order").value,
    loop: $("loop").value === "true",
    convert_gifs: $("convert-gifs").value === "true"
  });
  await refresh(); notice("Settings saved. Start a collection to use them.", "success");
});
$("files").onchange = event => upload(event.target.files);
for (const name of ["dragenter", "dragover"]) {
  $("drop-zone").addEventListener(name, event => {
    event.preventDefault(); $("drop-zone").classList.add("dragover");
  });
}
$("drop-zone").addEventListener("dragleave", () => $("drop-zone").classList.remove("dragover"));
$("drop-zone").addEventListener("drop", event => {
  event.preventDefault();
  $("drop-zone").classList.remove("dragover");
  if (uploading) { notice("Wait for the current upload batch to finish.", "error"); return; }
  upload(event.dataTransfer.files);
});
window.addEventListener("beforeunload", event => {
  if (uploading || conversionRunning()) { event.preventDefault(); event.returnValue = ""; }
});
for (const node of document.querySelectorAll("#folder-view [data-kinds]")) {
  node.addEventListener("click", guarded(() => startConversion(
    node.dataset.kinds.split(","), "collection", selected, $("folder-replace").checked)));
}
for (const node of document.querySelectorAll("#convert-view [data-kinds]")) {
  node.addEventListener("click", guarded(() => {
    const scope = $("library-scope").value;
    return startConversion(node.dataset.kinds.split(","),
      scope === "all" ? "all" : "collection",
      scope === "all" ? null : scope,
      $("library-replace").checked);
  }));
}
$("job-cancel").onclick = guarded(async () => {
  await api("/api/convert/cancel", "POST", {});
  await refresh(); renderConversion(); notice("Cancelling conversion…");
});
$("job-dismiss").onclick = () => { jobDismissed = conversionJob().id || 0; renderConversion(); };
$("download-folder").onclick = guarded(async () => {
  const name = folder().name, cid = selected;
  const control = $("download-folder");
  control.disabled = true;
  notice("Preparing folder download…");
  try {
    const blob = await folderArchive(`/api/collections/${cid}/download`);
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = `${name}.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notice("Folder download ready.", "success");
  } finally { control.disabled = false; }
});
$("install-media").onclick = guarded(async () => {
  const result = await api("/api/dependencies/install", "POST", {install: "ffmpeg"});
  $("install-status").textContent = result.message;
  $("install-media").disabled = true;
  const poll = async () => {
    try { await refresh(); if (state.installation.status === "running") setTimeout(poll, 2000); }
    catch (error) { notice(error.message, "error"); }
  };
  setTimeout(poll, 1000);
});
if (token) guarded(async () => { await refresh(); show("collections"); })();
