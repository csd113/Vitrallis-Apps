"use strict";
const $ = id => document.getElementById(id);
let token = "", state = null, selected = null, uploading = false, busy = false;
try { token = sessionStorage.getItem("carousel-code") || ""; } catch (_) { /* Private mode may deny storage. */ }
function notice(message, error = false) { $("notice").textContent = message; $("notice").classList.toggle("error", error); }
function lock() {
  token = ""; state = null; selected = null;
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
function renderFolder() {
  const row = folder();
  if (!row) { selected = null; show("collections"); return; }
  $("folder-title").textContent = row.name; $("item-count").textContent = `· ${row.items.length}`;
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
    controls.append(up, down, remove); li.append(details, controls); $("media").append(li);
  });
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
  renderCollections(); if (selected) renderFolder(); if (state.warning) notice(state.warning, true);
}
function renderSettings() {
  const config = state.settings; $("image-seconds").value = config.image_seconds; $("repeats").value = config.repeats;
  $("order").value = config.order; $("loop").value = String(config.loop); show("settings");
}
function sendFile(file, cid, index, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open("POST", `/api/collections/${cid}/media?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`); xhr.setRequestHeader("Content-Type", "application/octet-stream"); xhr.timeout = 160000;
    xhr.upload.onprogress = event => { if (event.lengthComputable) { $("progress").value = event.loaded / event.total * 100; $("upload-label").textContent = `${index}/${total} · ${file.name} · ${event.loaded === event.total ? "Checking media…" : Math.round($("progress").value) + "%"}`; } };
    xhr.onload = () => { try { const data = JSON.parse(xhr.responseText); if (xhr.status === 401) lock(); if (xhr.status !== 201) throw new Error(data.error || "Upload failed"); resolve(data); } catch (error) { reject(error); } };
    xhr.onerror = () => reject(new Error("Connection lost during upload")); xhr.ontimeout = () => reject(new Error("Upload timed out")); xhr.send(file);
  });
}
async function upload(files) {
  if (uploading || !selected || !files.length) return;
  uploading = true; const cid = selected; $("files").disabled = true; $("delete-folder").disabled = true;
  $("upload-status").hidden = false; $("upload-results").replaceChildren(); renderFolder(); let success = 0;
  // Retain at most 100 File references/results per batch; library limits remain server enforced.
  const batch = Array.from(files).slice(0, 100);
  try {
    for (const [index, file] of batch.entries()) {
      $("progress").value = 0; $("upload-label").textContent = `${index + 1}/${batch.length} · ${file.name}`;
      const result = document.createElement("li");
      try { if (file.size > state.max_upload) throw new Error("Over the 64 MiB limit"); await sendFile(file, cid, index + 1, batch.length); result.textContent = `${file.name}: saved`; success++; }
      catch (error) { result.textContent = `${file.name}: ${error.message}`; }
      $("upload-results").append(result); if (!token) break;
    }
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
$("settings-form").onsubmit = guarded(async () => { await api("/api/settings", "PUT", {image_seconds: Number($("image-seconds").value), repeats: Number($("repeats").value), order: $("order").value, loop: $("loop").value === "true"}); await refresh(); notice("Settings saved. Start a collection to use them."); });
$("files").onchange = event => upload(event.target.files);
for (const name of ["dragenter", "dragover"]) $("drop-zone").addEventListener(name, event => { event.preventDefault(); $("drop-zone").classList.add("dragover"); });
$("drop-zone").addEventListener("dragleave", () => $("drop-zone").classList.remove("dragover"));
$("drop-zone").addEventListener("drop", event => { event.preventDefault(); $("drop-zone").classList.remove("dragover"); upload(event.dataTransfer.files); });
window.addEventListener("beforeunload", event => { if (uploading) { event.preventDefault(); event.returnValue = ""; } });
if (token) guarded(async () => { await refresh(); show("collections"); })();
