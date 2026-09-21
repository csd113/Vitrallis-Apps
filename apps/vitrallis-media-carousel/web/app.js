"use strict";
const $ = id => document.getElementById(id);
let previewURLs = [], previewQueue = [], previewActive = 0;
let token = "", state = null, selected = null, uploading = false, busy = false, conversionTimer = null;
try { token = sessionStorage.getItem("carousel-code") || ""; } catch (_) { /* Private mode may deny storage. */ }
function notice(message, error = false) { $("notice").textContent = message; $("notice").classList.toggle("error", error); }
function lock() {
  token = ""; state = null; selected = null;
  clearTimeout(conversionTimer); conversionTimer = null;
  previewObserver.disconnect(); previewQueue = [];
  previewURLs.forEach(url => URL.revokeObjectURL(url)); previewURLs = [];
  $("media").replaceChildren();
  try { sessionStorage.removeItem("carousel-code"); } catch (_) { /* In-memory access still works. */ }
  $("workspace").hidden = true; $("login").hidden = false; $("connection").textContent = "Locked";
}
async function api(path, method = "GET", body) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {method, headers: {Authorization: `Bearer ${token}`, ...(body ? {"Content-Type": "application/json"} : {})}, body: body ? JSON.stringify(body) : undefined, signal: controller.signal});
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
    try { await action(event); } catch (error) { notice(error.message || "Device unavailable. Check the connection.", true); }
    finally { busy = false; }
  };
}
function show(view) {
  for (const name of ["collections", "folder", "settings"]) $(name + "-view").hidden = name !== view;
  $("collections-tab").classList.toggle("active", view !== "settings");
  $("settings-tab").classList.toggle("active", view === "settings");
}
function button(text, label, action, className = "secondary") {
  const node = document.createElement("button"); node.type = "button"; node.textContent = text;
  node.setAttribute("aria-label", label); node.className = className; node.addEventListener("click", guarded(action)); return node;
}
function renderCollections() {
  $("collections").replaceChildren();
  for (const folder of state.collections) {
    const card = button("", `Open ${folder.name}`, () => openFolder(folder.id), "collection");
    const symbol = document.createElement("span"); symbol.className = "folder-symbol"; symbol.textContent = "▱"; symbol.setAttribute("aria-hidden", "true");
    const name = document.createElement("span"); name.textContent = folder.name;
    const count = document.createElement("small"); count.textContent = `${folder.items.length} ${folder.items.length === 1 ? "item" : "items"}  →`;
    card.append(symbol, name, count); $("collections").append(card);
  }
}
function folder() { return state.collections.find(row => row.id === selected); }
function openFolder(id) { selected = id; renderFolder(); show("folder"); }
function conversionState() { return (state && state.conversion) || {}; }
function conversionRunning() { return conversionState().status === "running"; }
function renderConversion() {
  const conversion = conversionState(), line = $("conversion-status");
  if (conversion.status !== "running") { line.hidden = true; line.textContent = ""; return; }
  line.hidden = false;
  line.textContent = `${conversion.message || "Converting GIF to WebP…"}${conversion.name ? ` · ${conversion.name}` : ""}`;
}
function scheduleConversionPoll() {
  if (conversionTimer) return;
  conversionTimer = setTimeout(async () => {
    conversionTimer = null;
    try {
      await refresh();
      if (conversionRunning()) { scheduleConversionPoll(); return; }
      const conversion = conversionState();
      if (conversion.status === "ready") notice(`${conversion.name || "GIF"} converted to WebP.`);
      else if (conversion.status === "failed") notice(`${conversion.name ? `${conversion.name}: ` : ""}${conversion.message || "Conversion failed."}`, true);
    } catch (error) { notice(error.message || "Device unavailable. Check the connection.", true); }
  }, 1500);
}
async function convertItem(item) {
  state.conversion = await api(`/api/collections/${selected}/media/${item.id}/convert`, "POST");
  notice(conversionState().message || "Converting GIF to WebP…"); renderFolder(); renderConversion(); scheduleConversionPoll();
}
function renderFolder() {
  const row = folder();
  if (!row) { selected = null; show("collections"); return; }
  $("folder-title").textContent = row.name; $("item-count").textContent = `· ${row.items.length}`;
  previewURLs.forEach(url => URL.revokeObjectURL(url)); previewURLs = [];
  previewQueue = []; previewObserver.disconnect();
  $("media").replaceChildren();
  if (!row.items.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "Nothing here yet. Choose a few files to begin."; $("media").append(empty); }
  row.items.forEach((item, index) => {
    const li = document.createElement("li"), details = document.createElement("div"); details.className = "details";
    const name = document.createElement("span"); name.className = "filename"; name.textContent = item.name;
    const meta = document.createElement("small"); meta.textContent = `${item.kind.toUpperCase()} · ${(item.size / 1024 / 1024).toFixed(2)} MiB`;
    details.append(name, meta); const controls = document.createElement("div"); controls.className = "actions";
    const up = button("↑", `Move ${item.name} earlier`, () => move(index, -1)); up.disabled = index === 0 || uploading;
    const down = button("↓", `Move ${item.name} later`, () => move(index, 1)); down.disabled = index === row.items.length - 1 || uploading;
    const remove = button("Delete", `Delete ${item.name}`, async () => {
      if (!confirm(`Delete “${item.name}” from this device?`)) return;
      await api(`/api/collections/${selected}/media/${item.id}`, "DELETE"); await refresh(); notice("File deleted.");
    }, "danger"); remove.disabled = uploading;
    const buttons = [up, down];
    if (item.kind === "gif") {
      const convert = button("To WebP", `Convert ${item.name} to WebP`, () => convertItem(item));
      convert.disabled = uploading || conversionRunning();
      buttons.push(convert);
    }
    buttons.push(remove);
    const preview = document.createElement("img"); preview.className = "thumbnail";
    preview.alt = `${item.kind.toUpperCase()} preview`; preview.width = 128; preview.height = 80;
    controls.append(...buttons); li.append(preview, details, controls); $("media").append(li);
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
    if (!response.ok) { const data = await response.json(); throw new Error(data.error || "Download failed"); }
    return await response.blob();
  } finally { clearTimeout(timer); }
}
function archiveError(blob) {
  return new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = () => { try { resolve(JSON.parse(reader.result).error || "Download failed"); } catch (_) { resolve("Download failed"); } };
    reader.onerror = () => resolve("Download failed");
    reader.readAsText(blob);
  });
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
      if (xhr.status !== 200) { reject(new Error(await archiveError(xhr.response))); return; }
      resolve(xhr.response);
    };
    xhr.onerror = () => reject(new Error("Connection lost during download"));
    xhr.ontimeout = () => reject(new Error("Download timed out"));
    xhr.send();
  });
}
function loadPreviews() {
  while (previewActive < 2 && previewQueue.length) {
    const image = previewQueue.shift();
    if (!image.isConnected) continue;
    previewActive++;
    binary(image.dataset.path).then(blob => {
      if (!image.isConnected) return;
      const url = URL.createObjectURL(blob); previewURLs.push(url); image.src = url;
    }).catch(() => { image.alt = "Preview unavailable"; })
      .finally(() => { previewActive--; loadPreviews(); });
  }
}
async function move(index, direction) {
  const ids = folder().items.map(item => item.id); [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
  await api(`/api/collections/${selected}/order`, "PUT", {ids}); await refresh();
  const control = $("media").children[index + direction]?.querySelectorAll("button")[direction < 0 ? 0 : 1];
  if (control && !control.disabled) control.focus(); notice("Play order saved.");
}
async function refresh() {
  state = await api("/api/state");
  $("workspace").hidden = false; $("login").hidden = true; $("connection").textContent = state.status;
  $("device").textContent = `${state.device} · ${state.urls.join(" · ")}`;
  $("decoder-note").textContent = `${state.capabilities.webm ? "WebM decoder available." : "WebM unavailable."} ${state.capabilities.webm_note}`;
  $("install-media").hidden = state.capabilities.ready;
  $("install-media").disabled = state.installation.status === "running" || !state.installation.available;
  $("install-status").textContent = state.installation.message || (!state.capabilities.ready && !state.installation.available ? "Administrator setup is required to enable installation." : "");
  renderCollections(); if (selected) renderFolder(); renderConversion();
  if (conversionRunning()) scheduleConversionPoll();
  if (state.warning) notice(state.warning, true);
}
function renderSettings() {
  const config = state.settings; $("image-seconds").value = config.image_seconds; $("repeats").value = config.repeats;
  $("order").value = config.order; $("loop").value = String(config.loop); $("convert-gifs").value = String(config.convert_gifs); show("settings");
}
function sendFile(file, cid, progress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open("POST", `/api/collections/${cid}/media?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`); xhr.setRequestHeader("Content-Type", "application/octet-stream"); xhr.timeout = 160000;
    xhr.upload.onprogress = event => { if (event.lengthComputable) progress(event.loaded, event.total); };
    xhr.onload = () => { try { const data = JSON.parse(xhr.responseText); if (xhr.status === 401) lock(); if (xhr.status !== 201) throw new Error(data.error || "Upload failed"); resolve(data); } catch (error) { reject(error); } };
    xhr.onerror = () => reject(new Error("Connection lost during upload")); xhr.ontimeout = () => reject(new Error("Upload timed out")); xhr.send(file);
  });
}
async function upload(files) {
  if (uploading || !selected || !files.length) return;
  $("progress").value = 0;
  uploading = true; const cid = selected; $("files").disabled = true; $("delete-folder").disabled = true;
  $("upload-status").hidden = false; $("upload-results").replaceChildren(); renderFolder(); let success = 0;
  // Retain at most 100 File references/results per batch; library limits remain server enforced.
  const batch = Array.from(files).slice(0, 100);
  try {
    const loaded = batch.map(() => 0), totalBytes = batch.reduce((sum, file) => sum + file.size, 0);
    let next = 0, finished = 0;
    const rows = batch.map(file => { const row = document.createElement("li"); row.textContent = `${file.name}: queued`; $("upload-results").append(row); return row; });
    const worker = async () => {
      while (next < batch.length && token) {
        const index = next++, file = batch[index], result = rows[index];
        try {
          if (file.size > state.max_upload) throw new Error("Over the 64 MiB limit");
          result.textContent = `${file.name}: uploading`;
          await sendFile(file, cid, (bytes, total) => {
            loaded[index] = bytes;
            $("progress").value = totalBytes ? loaded.reduce((sum, value) => sum + value, 0) / totalBytes * 100 : 0;
            result.textContent = `${file.name}: ${bytes === total ? "checking media…" : Math.round(bytes / total * 100) + "%"}`;
          });
          result.textContent = `${file.name}: saved`; success++;
        } catch (error) { result.textContent = `${file.name}: ${error.message}`; }
        finished++; $("upload-label").textContent = `${finished}/${batch.length} files checked · ${success} saved`;
      }
    };
    // Two transfers overlap; server serializes expensive media validation.
    await Promise.all([worker(), worker()]);
    if (token) await refresh(); notice(`${success} of ${batch.length} files saved.${files.length > 100 ? " Select remaining files in another batch (100 maximum)." : ""}`, success !== batch.length);
  } catch (error) { notice(error.message, true); }
  finally { uploading = false; $("files").disabled = false; $("delete-folder").disabled = false; $("files").value = ""; $("upload-label").textContent = "Batch finished"; if (state && selected) renderFolder(); }
}
$("login-form").onsubmit = guarded(async () => { token = $("access-code").value.trim().toLowerCase(); await refresh(); try { sessionStorage.setItem("carousel-code", token); } catch (_) { /* Optional browser storage. */ } $("access-code").value = ""; notice(""); show("collections"); });
$("lock").onclick = () => { if (!uploading) lock(); else notice("Wait for the current batch to finish."); };
$("collections-tab").onclick = () => show("collections"); $("back").onclick = () => { selected = null; show("collections"); };
$("settings-tab").onclick = guarded(async () => { await refresh(); renderSettings(); }); $("refresh").onclick = guarded(refresh);
$("create-form").onsubmit = guarded(async () => { const row = await api("/api/collections", "POST", {name: $("collection-name").value}); $("collection-name").value = ""; await refresh(); openFolder(row.id); notice("Collection created."); });
$("rename").onclick = () => { $("rename-name").value = folder().name; $("rename-form").hidden = false; $("rename-name").focus(); };
$("cancel-rename").onclick = () => { $("rename-form").hidden = true; $("rename").focus(); };
$("rename-form").onsubmit = guarded(async () => { await api(`/api/collections/${selected}`, "PUT", {name: $("rename-name").value}); $("rename-form").hidden = true; await refresh(); notice("Collection renamed."); });
$("delete-folder").onclick = guarded(async () => { if (!confirm(`Delete “${folder().name}” and ALL of its media from this device?`)) return; await api(`/api/collections/${selected}`, "DELETE"); selected = null; await refresh(); show("collections"); notice("Collection deleted."); });
$("settings-form").onsubmit = guarded(async () => { await api("/api/settings", "PUT", {image_seconds: Number($("image-seconds").value), repeats: Number($("repeats").value), order: $("order").value, loop: $("loop").value === "true", convert_gifs: $("convert-gifs").value === "true"}); await refresh(); notice("Settings saved. Start a collection to use them."); });
$("files").onchange = event => upload(event.target.files);
for (const name of ["dragenter", "dragover"]) $("drop-zone").addEventListener(name, event => { event.preventDefault(); $("drop-zone").classList.add("dragover"); });
$("drop-zone").addEventListener("dragleave", () => $("drop-zone").classList.remove("dragover"));
$("drop-zone").addEventListener("drop", event => { event.preventDefault(); $("drop-zone").classList.remove("dragover"); upload(event.dataTransfer.files); });
window.addEventListener("beforeunload", event => { if (uploading) { event.preventDefault(); event.returnValue = ""; } });
if (token) guarded(async () => { await refresh(); show("collections"); })();

$("download-folder").onclick = guarded(async () => {
  const name = folder().name, cid = selected;
  $("download-folder").disabled = true; notice("Preparing folder download…");
  try {
    const blob = await folderArchive(`/api/collections/${cid}/download`);
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = `${name}.zip`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notice("Folder download ready.");
  } finally { $("download-folder").disabled = false; }
});

$("install-media").onclick = guarded(async () => {
  const result = await api("/api/dependencies/install", "POST", {install: "ffmpeg"});
  $("install-status").textContent = result.message; $("install-media").disabled = true;
  const poll = async () => {
    try { await refresh(); if (state.installation.status === "running") setTimeout(poll, 2000); }
    catch (error) { notice(error.message, true); }
  };
  setTimeout(poll, 1000);
});
