"use strict";
// Hash-routed pages: #dashboard, #library, #map, #watch/<id>?t=&end=, #search, #investigations, #system.
// All server and user text is inserted with textContent; nothing is inserted as HTML.
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="csrf-token"]').content;
let connection = null, operationRunning = false, planHasChanges = false, libraryLoaded = false;
let scenarioPlan=null, scenarioStop=false, scenarioActive=false;
let videosCache = [], waitingFiles = [], unsupportedFiles = [], activeVideo = null, framePage = 0, watchToken = 0, currentMoment = 0, watchWindow = null;
const time = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.floor((seconds || 0) % 60)).padStart(2,"0")}`;
// A camera name the user gave the recording, else the original upload name ("<12-hex id>_<name>" on disk).
const cameraNames = new Map();
const displayName = filename => cameraNames.get(filename) || String(filename||"").replace(/^[0-9a-f]{12}_/,"");
// "1 clip" / "3 clips": a count with the right word, instead of "clip(s)".
function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + "s")}`; }
function element(tag, text, className) { const node=document.createElement(tag); if(text !== undefined) node.textContent=text; if(className) node.className=className; return node; }
function icon(name) { const ns="http://www.w3.org/2000/svg", svg=document.createElementNS(ns,"svg"), use=document.createElementNS(ns,"use"); use.setAttribute("href","#i-"+name); svg.append(use); return svg; }
let noticeTimer=null;
function notice(text) { $("notice").textContent=text; clearTimeout(noticeTimer); if(text) noticeTimer=setTimeout(()=>{$("notice").textContent="";},9000); }
$("notice").addEventListener("click",()=>notice("")); // click the message to dismiss it
// Each website process sends its own instance id. A different id means the website was restarted since this
// page loaded (e.g. switching to or from the offline demo), so cached video ids may now name other footage.
const instance = document.querySelector('meta[name="tanya-instance"]').content;
const SERVER_GONE = "Can't reach the TanyaCCTV website. It may have been stopped or restarted (for example when switching to or from the offline demo). Start it again, then reload this page.";
const SERVER_CHANGED = "The TanyaCCTV website was restarted since this page was opened, possibly with a different video library. Reload this page (F5) so the videos, times and evidence shown match the server.";
const serverProblem = message => message===SERVER_GONE || message===SERVER_CHANGED;
async function serverFetch(path, options={}) {
  let response;
  try{ response=await fetch(path,{...options,headers:{"X-CSRF-Token":token,...options.headers}}); }
  catch(e){ throw new Error(SERVER_GONE); }   // no HTTP response at all: the browser only says "Failed to fetch"
  const served=response.headers.get("X-TanyaCCTV-Instance");
  if(served && served!==instance) throw new Error(SERVER_CHANGED);
  return response;
}
async function api(path, options={}) {
  const response=await serverFetch(path,options);
  let data; try{data=await response.json();}catch(e){throw new Error(`The server returned an unexpected response (${response.status}).`);}
  if(!response.ok) throw new Error(data.error || "The request failed. Please try again.");
  return data;
}
function post(path, payload) { return api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload||{})}); }

// ---------------------------------------------------------------- routing
const titles={dashboard:"Dashboard",monitor:"Live monitor",library:"Cameras",map:"Map",watch:"Video player",search:"Search",investigations:"Investigations",system:"Settings"};
function route() {
  const hash=location.hash.slice(1)||"dashboard", [path,query=""]=hash.split("?"), [view,arg]=path.split("/");
  const page=titles[view] ? view : "dashboard";
  document.querySelectorAll(".page").forEach(p=>{p.hidden=p.dataset.page!==page;});
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.view===(page==="watch"?"library":page)));
  $("page-title").textContent=titles[page];
  if(page!=="watch"){ $("player").pause(); activeVideo=null; }
  if(page==="watch"){ const params=new URLSearchParams(query); showWatch(Number(arg),Number(params.get("t"))||0,params.has("end")?Number(params.get("end")):null); window.followFromRoute?.(params); }
  if(page==="dashboard") library().catch(error=>notice(error.message)).finally(renderDashboard);
  if(page==="search") library().catch(error=>notice(error.message));
  if(page==="library") library().catch(error=>notice(error.message));
  if(page==="map") library().then(()=>window.showMap?.()).catch(error=>notice(error.message));
  if(page==="monitor") library().then(()=>window.showMonitor?.()).catch(error=>notice(error.message));
  else window.leaveMonitor?.();
  if(page==="investigations" && window.refreshInvestigation) window.refreshInvestigation().catch(error=>notice(error.message)); // never show stale source status
  if(page==="system") Promise.all([library(),status()]).catch(error=>notice(error.message));
  window.scrollTo(0,0);
}
window.addEventListener("hashchange",route);
function playbackEnd(start,end) { return Number.isFinite(end) && end>start ? end : null; }
// follow: optional {t, box, label} to track a boxed target from moment t (see follow.js).
function openVideo(id,name,url,start=0,end=null,follow=null) {
  end=playbackEnd(start,end);
  const hash=`#watch/${id}?t=${start||0}`+(end!==null&&end!==undefined?`&end=${end}`:"")
    +(follow?`&bt=${follow.t}&bx=${follow.box.join(",")}&bl=${encodeURIComponent(follow.label||"")}`:"");
  if(location.hash===hash) route(); else location.hash=hash;
}

// ---------------------------------------------------------------- status
// canSearch: some search works (live AI, quick search or an offline demo). liveAi: Gemini-backed
// features (thorough search, watch mode, AI summary) can run. Unknown until /api/status answers.
const canSearch = () => !!(connection && (connection.offline_demo || connection.scan_ready || connection.search_ready));
const liveAi = () => !!connection?.scan_ready;
window.aiState = () => ({known: !!connection, demo: !!connection?.offline_demo, live: liveAi(), search: canSearch()});
async function status() {
  const data=await api("/api/status"); connection=data;
  if(data.offline_demo){$("visual-check").checked=false;$("visual-consent").checked=false;
    const examples=data.demo_mode==="event_index"?["a person falling","someone entering a shop","a red car","a fight"]:["a person walking","a red car","a person lying on the floor","fire and smoke"];
    document.querySelectorAll("#examples .chip").forEach((chip,i)=>{chip.textContent=examples[i];});
  }
  const ready=data.offline_demo || data.scan_ready || data.search_ready;
  $("ai-pill").textContent=data.offline_demo ? "Offline demo · no live AI" : ready ? "AI connected" : "AI not set up";
  $("ai-pill").classList.toggle("ready",ready);
  $("ai-pill").classList.toggle("off",!ready);
  $("ai-pill").title=ready ? "Open Settings to see the AI connection" : "AI search isn't connected. Open Settings to set it up.";
  document.querySelectorAll("[data-ai-callout]").forEach(box=>{box.hidden=ready;});
  if(libraryLoaded){   // re-label recordings now that readiness is known
    renderLibrary();
    if(!document.querySelector('[data-page="dashboard"]').hidden) renderDashboard();
  }
  document.dispatchEvent(new CustomEvent("tanya:status"));
  window.loadFilterOptions?.();
  $("setup-details").open=!data.search_ready;
  renderStatusList($("system-status")); updateControls();
}
function statusItems() {
  if(!connection) return [["warn","Checking…"]];
  if(connection.demo_mode==="event_index") return [["ok","Offline demo: searches a preset index of annotated events (CAVIAR labels, scripted demo clips). No API key, network or live AI is used."],["ok","Playback, investigations and report export work on this computer."],[connection.yolo_ready?"ok":"warn",connection.yolo_ready?"Optional local YOLO person detection is available from each video's player page.":"Optional YOLO person detection is not set up; cached detections still appear where available."],["warn","AI image checks and quick-search set-up are off in the demo. New uploads have no annotated events."]];
  if(connection.offline_demo) return [["ok","Offline demo: recorded searches on sample footage; no API key or live AI is used."],["ok","Playback, investigations and report export work on this computer."],["warn","AI image checks and quick-search set-up are off in the demo. New uploads aren't in the recorded searches."]];
  const c=connection.coverage, items=[];
  items.push(["ok","Videos are stored and played on this computer."]);
  items.push([connection.engine_ready?"ok":"warn",connection.engine_ready?"Search engine installed.":"Search engine not set up (TANYA_SENTRY_PYTHON)."]);
  items.push([connection.key_ready?"ok":"warn",connection.key_ready?"Gemini API key found.":"No Gemini API key, so AI search won't work."]);
  items.push(["ok",`Quick search (optional): ${c.prepared.length} of ${plural(c.prepared.length+c.needs_preparation.length,"video")} set up.`]);
  if(c.unsupported.length) items.push(["warn",`${plural(c.unsupported.length,"video")} can't use quick search (MP4 / MOV only). Thorough search still works.`]);
  if(waitingFiles.length) items.push(["warn",`${plural(waitingFiles.length,"file")} in the video folder ${waitingFiles.length===1?"hasn't":"haven't"} been added yet.`]);
  return items;
}
function renderStatusList(list, items=statusItems()) {
  list.replaceChildren(...items.map(([kind,text])=>{const li=element("li",undefined,kind);li.append(icon(kind==="ok"?"check":"alert"),element("span",text));return li;}));
}
function searchHints(direct) {
  const c=connection;
  if(!c) return ["",""];
  if(c.demo_mode==="event_index") return ["Offline demo: describe an event, e.g. a person falling, someone entering a shop, people meeting, a red car, a person in the corridor. Words are matched to annotated events; there is no AI.",""];
  if(c.offline_demo) return ["Offline demo: try a red car, a person walking, a person lying on the floor, or fire and smoke. Only these recorded searches work.",""];
  if(direct){
    if(!c.scan_ready) return ["The AI isn't connected yet, so search can't run. See Settings.",""];
    return [videosCache.some(v=>v.status==="done")?"":"Add a video on the Cameras page first.",""];
  }
  if(!c.search_ready) return ["Quick search needs the AI connection. See Settings.",""];
  const prepared=c.coverage.prepared.length, pending=c.coverage.needs_preparation;
  return [prepared?`Quick search covers ${plural(prepared,"video")}.`:"No videos are set up for quick search yet. Set it up in Settings, or switch back to Thorough.",
    pending.length?`Not set up for quick search yet: ${pending.map(displayName).join(", ")}.`:""];
}
function updateControls() {
  const direct=$("search-mode").value==="direct";
  const visual=$("visual-check").checked;
  $("scenario-options").hidden=!direct;
  $("scan-video-label").hidden=!direct;
  const [setup,coverage]=searchHints(direct);
  const callout=connection && !canSearch();   // the callout above the search box already explains this
  $("setup").textContent=callout?"":setup; $("coverage").textContent=callout?"":coverage;
  $("ranked-visual-option").hidden=direct;
  $("scenario-run").disabled=operationRunning || !scenarioPlan || !$("scenario-consent").checked || !connection?.scan_ready;
  for(const id of ["search-mode","scan-video","scan-start","scan-end","scenario-consent","scenario-cancel"]) $(id).disabled=operationRunning;
  $("scan-start").disabled ||= $("scan-video").value==="all";
  $("scan-end").disabled ||= $("scan-video").value==="all";
  $("search-button").disabled=operationRunning || !connection?.search_ready || !connection?.coverage.prepared.length || (visual && !$("visual-consent").checked);
  if(direct) $("search-button").disabled=operationRunning || !videosCache.some(v=>v.status==="done") || connection?.offline_demo || !liveAi();
  $("dash-search-button").disabled=!!connection && !canSearch();
  $("visual-consent-panel").hidden=direct || !visual;
  for(const id of ["visual-check","visual-consent","query","index-button","upload-button"]) $(id).disabled=operationRunning;
  if(connection?.offline_demo) $("visual-check").disabled=true;
  $("plan-button").disabled=operationRunning || !connection?.engine_ready || connection?.offline_demo;
  $("sync-button").disabled=operationRunning || !planHasChanges;
  $("busy-pill").hidden=!operationRunning;
}
function busy(value) { operationRunning=value; updateControls(); }
$("visual-check").onchange=()=>{$("visual-consent").checked=false;updateControls();};
$("visual-consent").onchange=updateControls;
$("query").addEventListener("input",()=>{$("visual-consent").checked=false;window.followCtx=null;invalidateScenario();updateControls();});

// ---------------------------------------------------------------- dashboard
function stat(label,value,sub,href,kind) {
  const card=element("a",undefined,"stat"+(kind?" "+kind:"")); card.href=href;
  card.append(element("div",label,"label"),element("div",String(value),"value"),element("div",sub,"sub")); return card;
}
async function renderDashboard() {
  let cases=[];
  try{ cases=(await api("/api/investigations")).investigations; }catch(e){ notice(e.message); }
  const done=videosCache.filter(v=>v.status==="done").length, failed=videosCache.filter(v=>v.status==="failed"||v.playback?.status==="missing"||v.playback?.changed).length;
  const open=cases.filter(c=>c.status==="open"), unreviewed=cases.reduce((s,c)=>s+c.unreviewed_count,0);
  const tiles=[
    stat("Recordings",videosCache.length,`${time(videosCache.reduce((s,v)=>s+(v.duration_sec||0),0))} of footage`+(waitingFiles.length?` · ${waitingFiles.length} waiting to be added`:""),"#library","primary"),
    canSearch() || !connection
      ? stat("Ready to search",done,done===videosCache.length?"all recordings":`of ${plural(videosCache.length,"recording")}`,"#search")
      : stat("AI search","Off","Connect it in Settings to search footage","#system","attention"),
    stat("Investigations",cases.length,unreviewed?`${plural(unreviewed,"clip")} to review`:`${open.length} open`,"#investigations",unreviewed?"attention":"")];
  if(failed) tiles.push(stat("Problems",failed,failed===1?"recording needs attention":"recordings need attention","#library","alert"));
  $("stats").replaceChildren(...tiles);
  const recent=$("dash-videos"); recent.replaceChildren();
  if(!videosCache.length){ const a=element("a","No recordings yet. Add your first video →","empty"); a.href="#library"; a.onclick=()=>{$("upload-form").hidden=false;}; recent.append(a); }
  if(window.renderCameraWall) window.renderCameraWall(recent, videosCache);
  else for(const v of videosCache.slice(0,6)){
    const b=element("button",undefined,"mini"); b.type="button"; b.title=v.filename; b.append(thumb(v)); b.append(element("strong",displayName(v.filename)),element("span",`${time(v.duration_sec)} · ${v.status==="done"?"ready":v.status}`,"muted"));
    b.onclick=()=>openVideo(v.id); recent.append(b);
  }
  const box=$("dash-cases"); box.replaceChildren();
  if(!cases.length) box.append(element("p","None yet. Create one to collect clips for an incident.","empty"));
  for(const c of cases.slice(0,5)){
    const row=element("button",undefined,"row-link"); row.type="button";
    row.append(element("strong",c.title),element("span",`${c.status==="open"?"Open":"Closed"} · ${plural(c.evidence_count,"clip")}`+(c.unreviewed_count?` · ${c.unreviewed_count} to review`:""),"muted"));
    row.onclick=()=>{ location.hash="#investigations"; if(window.openInvestigation) window.openInvestigation(c.id); }; box.append(row);
  }
  // Only problems are worth dashboard space; the full list lives under Settings.
  const problems=statusItems().filter(([kind])=>kind!=="ok");
  renderStatusList($("dash-status"),problems.length?problems:[["ok","Everything is ready. You can search your footage."]]);
}
$("dash-search").onsubmit=event=>{
  event.preventDefault();
  $("query").value=$("dash-query").value.trim(); $("dash-query").value="";
  invalidateScenario(); $("visual-consent").checked=false;
  location.hash="#search"; updateControls();
  if(!$("search-button").disabled) $("search-form").requestSubmit();
};

// ---------------------------------------------------------------- library
// One status per recording: problems first, then whether it can be searched.
function videoStatus(v) {
  if(v.status==="failed") return ["Problem","failed"];
  if(v.status!=="done") return ["Processing…","pending"];
  if(v.playback?.status==="missing") return ["File missing","failed"];
  if(v.playback?.changed) return ["File changed","failed"];
  if(connection?.demo_mode==="event_index") return ["In the demo library",""];
  if(connection?.offline_demo) return v.search_state==="prepared"?["In the recorded demo",""]:["Not in the recorded demo","neutral"];
  return canSearch() ? ["Ready to search",""] : ["Ready to watch","neutral"];
}
function thumb(video) {
  const box=element("div",undefined,"thumb");
  if(video.thumbnail_url){const img=element("img");img.src=video.thumbnail_url;img.alt=`First frame of ${displayName(video.filename)}`;img.loading="lazy";box.append(img);}
  else box.append(element("span",video.status==="failed"?"No frames (failed)":"No frames yet"));
  if(video.duration_sec) box.append(element("span",time(video.duration_sec),"duration"));
  const play=element("span",undefined,"play"); play.append(icon("play")); box.append(play);
  return box;
}
async function library() {
  const data=await api("/api/videos");
  videosCache=data.videos; waitingFiles=data.waiting_files; unsupportedFiles=data.unsupported_files; libraryLoaded=true;
  cameraNames.clear(); for(const v of videosCache) if(v.camera?.name) cameraNames.set(v.filename,v.camera.name);
  refreshScanVideos(); updateControls();
  renderLibrary();
}
function matchesFilter(v) {
  const text=$("library-filter").value.trim().toLowerCase(), f=$("library-status").value;
  if(text && !v.filename.toLowerCase().includes(text) && !displayName(v.filename).toLowerCase().includes(text)) return false;
  if(f==="done") return v.status==="done";
  if(f==="failed") return v.status==="failed" || v.playback?.status==="missing" || v.playback?.changed;
  if(f==="needs_preparation") return v.search_state===f;
  return true;
}
function renderLibrary() {
  const unsupported=unsupportedFiles;
  const banner=$("waiting"); banner.replaceChildren();
  banner.hidden=!waitingFiles.length && !unsupported.length;
  if(waitingFiles.length){
    banner.append(icon("alert"),element("span",`${plural(waitingFiles.length,"video")} in the video folder ${waitingFiles.length===1?"hasn't":"haven't"} been added yet: ${waitingFiles.slice(0,5).map(displayName).join(", ")}${waitingFiles.length>5?"…":""}.`));
    const b=element("button","Add them now","secondary"); b.type="button"; b.onclick=()=>$("index-button").click(); banner.append(b);
  }
  if(unsupported.length) banner.append(element("span",`Skipped (not a video type we support): ${unsupported.slice(0,5).join(", ")}${unsupported.length>5?"…":""}.`,"muted"));
  const grid=$("videos"), shown=videosCache.filter(matchesFilter); grid.replaceChildren();
  $("library-count").textContent=`${shown.length} of ${videosCache.length}`;
  if(!videosCache.length){ $("upload-form").hidden=false; const e=element("div",undefined,"card empty-state"); e.append(icon("library"),element("h2","No recordings yet"),element("p",waitingFiles.length?"Add the videos waiting in the folder, or upload one above.":"Upload a video above to get started.","muted")); grid.append(e); return; }
  if(!shown.length) grid.append(element("p","No recordings match this filter.","empty"));
  for(const v of shown){
    const card=element("article",undefined,"video-card"), name=displayName(v.filename);
    const open=element("button",undefined,"thumb-button"); open.type="button"; open.setAttribute("aria-label",`Play ${name}`); open.append(thumb(v)); open.onclick=()=>openVideo(v.id);
    const body=element("div",undefined,"video-body");
    const title=element("h3",name); title.title=v.filename;
    body.append(title,element("p",[v.camera?.place,`${time(v.duration_sec)} · ${v.width||"—"} × ${v.height||"—"}`].filter(Boolean).join(" · "),"meta"));
    if(v.camera?.name) body.append(element("p",String(v.filename).replace(/^[0-9a-f]{12}_/,""),"file-name"));
    const [label,kind]=videoStatus(v);
    body.append(element("span",label,"badge "+kind));
    if(v.camera?.hidden){ card.classList.add("is-hidden"); body.append(element("span","Hidden from wall, map and “All recordings”","badge neutral")); }
    if(v.error) body.append(element("p",v.error,"error-text"));
    if(v.playback?.status==="missing") body.append(element("p",v.playback.message,"error-text"));
    if(v.playback?.changed) body.append(element("p",v.playback.changed_message,"error-text"));
    if(window.cameraEditor) body.append(window.cameraEditor(v));
    card.append(open,body); grid.append(card);
  }
}
$("library-filter").addEventListener("input",()=>renderLibrary());
$("library-status").onchange=()=>renderLibrary();
$("toggle-upload").onclick=()=>{ $("upload-form").hidden=!$("upload-form").hidden; };

// ---------------------------------------------------------------- watch
const mediaErrors={1:"Playback was stopped before the video loaded.",2:"A network error stopped the video from loading. Check that the website is still running.",3:"The browser could not decode this video. It may be damaged.",4:"This browser cannot play this video format."};
function overlay(text){ $("player-overlay").hidden=!text; $("player-overlay-text").textContent=text||""; }
function playerError(text){ $("player-error").hidden=!text; $("player-error").textContent=text||""; if(text) overlay(null); }
function resetPlayer(){ const p=$("player"); p.pause(); p.removeAttribute("src"); p.load(); playerError(null); overlay(null); window.clearFollow?.(); }
async function showWatch(id,start,end) {
  end=playbackEnd(start,end);
  const myToken=++watchToken; activeVideo=id; framePage=0; currentMoment=start; watchWindow=end!==null?[start,end]:null;
  resetPlayer(); $("frames").replaceChildren(); $("more-frames").hidden=true; $("player-window").hidden=true; $("replay-window").hidden=true;
  let video=videosCache.find(v=>v.id===id);
  if(!video){ try{await library();}catch(e){} video=videosCache.find(v=>v.id===id); }
  if(myToken!==watchToken) return;
  if(!video){ $("watch-title").textContent="Recording not found"; $("watch-meta").textContent=""; $("watch-details").replaceChildren(); $("download-video").hidden=true; playerError("This video is no longer in the library. Go back to Cameras and choose another recording."); return; }
  $("watch-title").textContent=displayName(video.filename);
  $("watch-meta").textContent=`${time(video.duration_sec)} · ${video.width||"—"} × ${video.height||"—"} · ${video.frame_count} frames`;
  const dl=$("watch-details"); dl.replaceChildren();
  for(const [k,val] of [["File",video.rel_path],["Duration",time(video.duration_sec)],["Frame rate",video.fps?`${video.fps.toFixed(1)} fps`:"—"],["Video codec",video.playback?.codec_name||"—"],["Size",`${(video.size_bytes/1048576).toFixed(1)} MB`],["Content hash",video.sha256.slice(0,16)+"…"],["Indexed",video.status==="done"?"Frames ready":video.status]]) dl.append(element("dt",k),element("dd",val));
  $("download-video").hidden=false; $("download-video").href=video.video_url; $("download-video").download=video.filename;
  $("player-window").hidden=!watchWindow; $("replay-window").hidden=!watchWindow;
  if(watchWindow) $("player-window").textContent=`Result window ${time(watchWindow[0])}–${time(watchWindow[1])}`;
  updateTime(); loadFrames(); fillWatchCases(); loadPeople(id,myToken); window.loadEventTimeline?.(id,myToken);
  overlay("Checking whether this browser can play the recording…");
  try{
    let info=await api(`/api/videos/${id}/playback`);
    if(myToken!==watchToken) return;
    if(info.status==="missing"){ $("download-video").hidden=true; playerError(info.message); return; }
    if(info.changed) notice(info.changed_message);
    if(info.status==="needs_copy"){
      if(!info.ffmpeg_available){ playerError(info.message.replace("can be made on this computer","needs FFmpeg, which was not found")+" Install FFmpeg (or set TANYA_FFMPEG / TANYA_SENTRY_PYTHON) and reload. The frame timeline below still works."); return; }
      overlay(`${info.message} Making it now… This takes a few seconds per minute of footage.`);
      info=await api(`/api/videos/${id}/playback-copy`,{method:"POST"});
      if(myToken!==watchToken) return;
      videosCache.forEach(v=>{ if(v.id===id) v.playback=info; });
    }
    overlay("Loading video…");
    const p=$("player");
    p.onloadedmetadata=()=>{ if(myToken!==watchToken) return; if(start) p.currentTime=Math.min(start,p.duration||start); overlay(null); updateTime(); };
    p.onerror=()=>{ if(myToken!==watchToken||!p.getAttribute("src")) return; playerError((mediaErrors[p.error?.code]||"The video could not be played.")+" The frame timeline below still works."); };
    p.src=info.url;
    if(info.status==="copy_ready") $("watch-meta").textContent+=" · playing a browser copy (original unchanged)";
  }catch(error){ if(myToken===watchToken) playerError(error.message+(serverProblem(error.message)?"":" The frame timeline below still works.")); }
}
function updateTime(){ const p=$("player"); if(p.getAttribute("src")) currentMoment=p.currentTime; $("player-time").textContent=`${time(currentMoment)} / ${time(p.duration||videosCache.find(v=>v.id===activeVideo)?.duration_sec)}`; window.updatePlayhead?.(); }
$("player").addEventListener("timeupdate",updateTime);
$("player").addEventListener("seeked",updateTime);
// Only a real, loading source can buffer; never cover an error message with "Buffering…".
$("player").addEventListener("waiting",()=>{ const p=$("player"); if(p.getAttribute("src") && !p.error && $("player-error").hidden) overlay("Buffering…"); });
$("player").addEventListener("playing",()=>overlay(null));
$("player").addEventListener("canplay",()=>{ if($("player-overlay-text").textContent==="Buffering…") overlay(null); });
$("replay-window").onclick=()=>{ if(!watchWindow) return; const p=$("player"); p.currentTime=watchWindow[0]; p.play().catch(()=>{}); };
$("watch-back").onclick=()=>{ location.hash="#library"; };
// ---------------------------------------------------------------- optional YOLO person detection
function renderPeople(data, id, myToken){
  const panel=$("people-panel"); panel.replaceChildren();
  window.setTimelinePeople?.(data);   // the same detections, drawn on the event timeline as their own lane
  $("people-section").hidden=!data.available && !data.result;
  const r=data.result;
  if(r){
    if(r.stale) panel.append(element("p","These detections were made with different model weights than the ones set up now; run again to refresh them.","warning"));
    if(!r.intervals.length) panel.append(element("p",`No person detected at confidence ≥ ${r.presence_conf}. That does not prove nobody was there (small or overhead people are often missed).`,"muted"));
    const list=element("div",undefined,"actions");
    for(const iv of r.intervals){ const b=element("button",`${time(iv.start_sec)}–${time(iv.end_sec)} · up to ${iv.max_conf.toFixed(2)}`,"secondary small"); b.type="button"; b.onclick=()=>seek(iv.start_sec); list.append(b); }
    if(r.intervals.length) panel.append(element("p",`${plural(r.intervals.length,"time range")} with a person detected (confidence ≥ ${r.presence_conf}). Select one to jump there:`,"muted"),list);
    panel.append(element("p",r.caution,"muted small-note"));
    panel.append(element("p",`Model ${r.model.weights||"unknown"}, ${r.model.imgsz} px${r.runner.device?`, ${r.runner.device}`:""}${r.weights_verified?" (weights hash matches)":""}. Video hash ${r.video.sha256.slice(0,12)}… matches this recording.`+(r.provenance?" "+r.provenance:""),"muted small-note"));
  }
  if(data.available){
    const run=element("button",r?"Run person detection again":"Find people (YOLO, on this computer)","secondary"); run.type="button";
    run.onclick=async()=>{ run.disabled=true; busy(true); notice("Finding people with the local YOLO model… about half a second per second of video.");
      try{ const fresh=await post(`/api/videos/${id}/people`,{}); if(myToken===watchToken) renderPeople(fresh,id,myToken); notice("Person detection finished. Review the time ranges: they are candidates, not events."); }
      catch(error){ notice(error.message); } finally{ run.disabled=false; busy(false); } };
    panel.append(run);
  } else if(data.reason && r) panel.append(element("p","Running it again needs the YOLO environment: "+data.reason,"muted small-note"));
}
async function loadPeople(id, myToken){
  $("people-section").hidden=true; $("people-panel").replaceChildren();
  try{ const data=await api(`/api/videos/${id}/people`); if(myToken===watchToken) renderPeople(data,id,myToken); }catch(e){ window.setTimelinePeople?.(null); /* optional feature: the player still works */ }
}
function seek(t){ currentMoment=t; const p=$("player"); if(p.getAttribute("src")&&!p.error) p.currentTime=t; updateTime(); }
window.seekTo = seek;
async function loadFrames() {
  const id=activeVideo, page=framePage; $("more-frames").disabled=true;
  try{
    const data=await api(`/api/videos/${id}/frames?page=${page}`);
    if(activeVideo!==id) return;
    if(!data.frames.length && page===0) $("frames").append(element("p","No frames were extracted for this recording.","muted"));
    for(const frame of data.frames){
      const b=element("button"); b.type="button"; const img=element("img"); img.src=frame.url; img.alt=`Frame at ${time(frame.timestamp_sec)}`; img.loading="lazy";
      b.append(img,element("span",time(frame.timestamp_sec)));
      b.onclick=()=>{ document.querySelectorAll("#frames button.current").forEach(x=>x.classList.remove("current")); b.classList.add("current"); seek(frame.timestamp_sec); };
      $("frames").append(b);
    }
    $("more-frames").hidden=!data.has_more; framePage++;
  }catch(error){ notice(error.message); }finally{ $("more-frames").disabled=false; }
}
$("more-frames").onclick=loadFrames;
async function fillWatchCases() {
  const select=$("watch-case"), chosen=select.value||$("save-to").value;
  try{
    const {investigations}=await api("/api/investigations"), open=investigations.filter(c=>c.status==="open");
    select.replaceChildren(new Option(open.length?"Choose an open investigation":"No open investigations — create one first",""),...open.map(c=>new Option(c.title,String(c.id))));
    if([...select.options].some(o=>o.value===chosen)) select.value=chosen;
  }catch(error){ notice(error.message); }
}
$("watch-add").onclick=async()=>{
  const id=$("watch-case").value, video=videosCache.find(v=>v.id===activeVideo);
  if(!id){ notice("Choose an open investigation first (create one under Investigations)."); return; }
  if(!video) return;
  const duration=$("player").duration||video.duration_sec||currentMoment+5, start=Math.max(0,currentMoment-5), end=Math.min(duration,Math.max(currentMoment+5,start+1));
  $("watch-add").disabled=true;
  try{
    const inv=await post(`/api/investigations/${id}/evidence`,{video_id:video.id,start_sec:start,end_sec:end,query:"Chosen manually in the video player",search_mode:"manual",rank:null,best_score:null});
    notice(`Added ${video.filename} ${time(start)}–${time(end)} to “${inv.title}” as an unreviewed, manually chosen clip.`);
    if(window.refreshInvestigation) window.refreshInvestigation();
  }catch(error){ notice(error.message); }finally{ $("watch-add").disabled=false; }
};

// ---------------------------------------------------------------- indexing and upload
async function indexVideos() {
  const summary=await post("/api/index");
  const failed=summary.outcomes.filter(item=>item.status==="failed");
  const duplicates=summary.outcomes.filter(item=>item.status==="skipped" && item.message.startsWith("duplicate content of"));
  await Promise.all([library(),status()]);
  $("sync-plan").hidden=true;
  const duplicateNote=duplicates.length ? ` ${plural(duplicates.length,"file")} ${duplicates.length===1?"was":"were"} identical to videos already in the library and were not added again.` : "";
  notice((failed.length ? `${plural(failed.length,"video")} couldn't be added. On the Cameras page, filter by “Problems” to see why.` : (canSearch()?"Done. Your footage is ready to search.":"Done. Your footage is ready to watch. Connect the AI in Settings to search it."))+duplicateNote);
}
$("index-button").onclick=async()=>{ busy(true); notice("Adding videos from the folder… Keep this page open."); try{await indexVideos();}catch(error){notice(error.message);}finally{busy(false);} };
$("upload-form").onsubmit=async event=>{
  event.preventDefault(); const file=$("video-file").files[0];
  if(file && file.size>512*1024*1024){ notice("Choose a video smaller than 512 MB."); return; }
  busy(true); notice("Uploading your video…");
  try{
    const uploaded=await api("/api/upload",{method:"POST",body:new FormData(event.target)});
    if(uploaded.duplicate_of){ notice(`This video is already in your library as ${uploaded.duplicate_of}. No second copy was added.`); event.target.reset(); return; }
    notice("Uploaded. Adding it to your library…"); await indexVideos(); event.target.reset(); $("upload-form").hidden=true;
  }catch(error){ notice(error.message); }finally{ busy(false); }
};

// ---------------------------------------------------------------- quick find
$("quick-find").onsubmit=async event=>{
  event.preventDefault(); const text=$("quick-find-input").value.trim().toLowerCase(); if(!text) return;
  try{ await library(); }catch(e){ notice(e.message); return; }
  const video=videosCache.find(v=>v.filename.toLowerCase().includes(text));
  let cases=[]; try{cases=(await api("/api/investigations")).investigations;}catch(e){}
  const inv=cases.find(c=>c.title.toLowerCase().includes(text));
  if(video){ $("library-filter").value=$("quick-find-input").value.trim(); $("library-status").value="all"; renderLibrary(); location.hash="#library"; notice(inv?`Also matches investigation “${inv.title}”.`:""); }
  else if(inv){ location.hash="#investigations"; if(window.openInvestigation) window.openInvestigation(inv.id); }
  else notice(`No video or investigation name contains “${$("quick-find-input").value.trim()}”. To search inside footage, use Search.`);
};

// ---------------------------------------------------------------- search
document.querySelectorAll("#examples .chip").forEach(chip=>{ chip.onclick=()=>{ $("query").value=chip.textContent; invalidateScenario(); $("visual-consent").checked=false; updateControls(); $("query").focus(); }; });
function saveToId(){ const value=$("save-to").value; return value ? Number(value) : null; }
$("search-form").onsubmit=async event=>{
  event.preventDefault();
  // Thorough search: first the pre-analysed footage notes (instant, no AI); live AI only if nothing matches
  // there, or when the person asks for it.
  if($("search-mode").value==="direct"){ if(!(await notesSearch())) await reviewScenarioPlan(); return; }
  const visual=$("visual-check").checked, approved=$("visual-consent").checked;
  if(visual && !approved){ notice("Approve the sampled-frame check, or uncheck image checking to see rankings only."); return; }
  busy(true);
  const loading=element("div",undefined,"card loading-line"); loading.append(element("div",undefined,"spinner"),element("span",visual?"Searching and double-checking the top results… This can take a few minutes.":"Searching…"));
  $("results").replaceChildren(loading);
  try{
    const filters=window.searchFilters?.()||null;
    // With filters, an empty box means "every event that passes the filters".
    const queryText=$("query").value.trim()||(filters?"all":$("query").value);
    const data=await post("/api/search",{query:queryText,visual_check:visual,approve_frame_upload:approved,...(filters?{filters}:{}),...(saveToId()?{investigation_id:saveToId()}:{})});
    const indexed=data.mode==="event_index";
    $("results").replaceChildren(element("p",indexed?`Events in the preset index for “${data.query}”. Each result says where its label comes from: watch the footage before deciding.`:visual?`Results for “${data.query}”. These are AI suggestions from a few images per clip: always watch before deciding.`:`Closest-looking clips for “${data.query}”. They appear even if what you described never happened: watch to check.`,"results-intro"));
    const active=indexed?window.filterSummary?.(data.applied_filters):null; if(active) $("results").append(active);
    for(const warning of data.warnings) $("results").append(element("p",warning,"warning"));
    if(data.visual_review) $("results").append(element("h3",`${data.visual_review.supported} likely · ${data.visual_review.unclear} maybe · ${data.visual_review.rejected} no match`));
    if(!data.hits.length){ const e=element("div",undefined,"card empty-state"); e.append(icon("search"),element("h2",indexed?"No matching events":"No likely matches"),element("p",indexed?"No annotated event matches. Not finding it doesn't prove it didn't happen.":visual?(data.unclear_hits?.length?"Check the “maybe” clips below. ":"")+"Not finding it doesn't prove it didn't happen.":"No clips came back. Try different wording.","muted")); $("results").append(e); }
    const ranked=[...data.hits,...(data.unclear_hits||[]),...(data.rejected_hits||[])];
    if(data.saved_query) $("results").append(element("p",`Search saved to your investigation.`,"muted"));
    for(const hit of data.hits) $("results").append(resultCard(hit,data.query,visual,ranked.indexOf(hit)+1));
    for(const [key,title] of [["unclear_hits","Maybe: worth a look"],["rejected_hits","Checked: no match"]]){
      if(data[key]?.length){ const details=element("details",undefined,"result-group"); details.open=key==="unclear_hits" && !data.hits.length; details.append(element("summary",`${title} (${data[key].length})`)); for(const hit of data[key]) details.append(resultCard(hit,data.query,visual,ranked.indexOf(hit)+1)); $("results").append(details); }
    }
    $("results").append(element("p",data.note,"muted small-note"));
    if(saveToId() && window.refreshInvestigation) window.refreshInvestigation();
  }catch(error){ const e=element("div",undefined,"banner error"); e.append(icon("alert"),element("span",error.message)); $("results").replaceChildren(e); }
  finally{ $("visual-consent").checked=false; busy(false); }
};
const verdictLabels={supported:["Likely match",""],unclear:["Maybe","pending"],not_supported:["No match","neutral"]};
const answerNames={correct:"Yes",wrong:"No",unsure:"Not sure"};
function resultCard(hit, query, visual, rank){
  const card=element("article",undefined,"result"), review=hit.visual_review, focus=hit.review_focus, span=review?.evidence_span;
  // With the AI's box, the player follows that target from the cited frame (tracked on this computer).
  const box=review?.evidence_boxes?.[0];
  const follow=box?{t:box.timestamp,box:box.box_2d,label:box.label}:null;
  const play=(start,end)=>openVideo(hit.video_id,hit.filename,hit.video_url,start,end,follow);
  // The checker's cited frames give a tighter range than the scanned window (a hint, not a boundary).
  // Event-index results play from a little before the event to a little after it.
  const playBest=()=>span?play(span.start_sec,span.end_sec):ev?play(ev.context_start_sec,ev.context_end_sec):play(hit.start_sec,hit.end_sec);
  const pic=element("button",undefined,"thumb-button result-thumb"); pic.type="button"; pic.setAttribute("aria-label",`Play ${displayName(hit.filename)}`);
  if(hit.thumbnail_url){ const img=element("img"); img.src=hit.thumbnail_url; img.alt=`Frame from ${displayName(hit.filename)}`; pic.append(img); }
  else pic.append(element("div","No frame","video-placeholder"));
  if(review?.evidence_boxes?.length) window.drawEvidenceBoxes?.(pic,review);
  const overlay=element("span",undefined,"play"); overlay.append(icon("play")); pic.append(overlay); pic.onclick=playBest;
  const info=element("div",undefined,"result-info");
  const ev=hit.event;
  const [verdict,kind]=hit.preanalysed?["Pre-analysed match",""]:review?verdictLabels[review.verdict]:ev?[ev.source_label,{provisional_review:"info",publisher_annotation:"info",synthetic_script:"neutral",yolo_person:"pending"}[ev.source]]:["Similar clip","info"];
  const head=element("div",undefined,"result-head");
  head.append(element("span",verdict,"badge "+kind),element("span",`${time(hit.start_sec)} – ${time(hit.end_sec)}`,"when"),element("span",displayName(hit.filename),"muted"));
  info.append(head);
  if(review?.reason) info.append(element("p",review.reason,"reason"));
  if(ev){
    info.append(element("p",ev.needs_human_review?`${ev.label}. Needs human review: a person detection is not an event.`:`${ev.label} (${ev.dataset}${ev.views.length?", "+ev.views.join(", ")+" view":""}).`,"reason"));
    if(ev.detector) info.append(element("p",`Detector confidence up to ${ev.detector.max_conf.toFixed(2)} (mean ${ev.detector.mean_conf.toFixed(2)}) over ${ev.detector.frames} frames at ≥ ${ev.detector.threshold}. A detector score, not the probability of an event.`,"muted"));
  }
  const actions=element("div",undefined,"actions");
  const main=element("button",span?`Play key moment ${time(span.start_sec)}–${time(span.end_sec)}`:ev?`Play event ${time(hit.start_sec)}–${time(hit.end_sec)}`:`Play ${time(hit.start_sec)}–${time(hit.end_sec)}`); main.type="button"; main.prepend(icon("play")); main.onclick=playBest; actions.append(main);
  if(span){ const whole=element("button","Play whole clip","secondary"); whole.type="button"; whole.onclick=()=>play(hit.start_sec,hit.end_sec); actions.append(whole); }
  const hasFocus=focus && (focus.start_sec!==hit.start_sec || focus.end_sec!==hit.end_sec);
  if(hasFocus){ const inspect=element("button",`Play strongest part ${time(focus.start_sec)}–${time(focus.end_sec)}`,"secondary"); inspect.type="button"; inspect.onclick=()=>play(focus.start_sec,focus.end_sec); actions.append(inspect); }
  if(window.investigationClipButton) actions.append(window.investigationClipButton(hit,query,visual,rank));
  if(review?.reason && review.verdict!=="not_supported" && window.followPerson){ const follow=element("button","Follow this person","secondary follow-btn"); follow.type="button"; follow.prepend(icon("pin")); follow.onclick=()=>window.followPerson(hit); actions.append(follow); }
  info.append(actions);
  // Technical detail stays available, but out of the way.
  const more=element("details",undefined,"tech"); more.append(element("summary","Details"));
  if(ev){ more.append(element("p",ev.provenance,"muted")); more.append(element("p",`Exact label times ${hit.start_sec.toFixed(2)}–${hit.end_sec.toFixed(2)} s. Playback includes ${time(ev.context_start_sec)}–${time(ev.context_end_sec)} for context. No similarity score: matched by keywords.`,"muted")); if(ev.detector?.provenance) more.append(element("p",ev.detector.provenance,"muted")); }
  else if(hit.preanalysed) more.append(element("p","From footage notes written in advance by watching this recording, not a live AI check. The square is the noted position; the player then tracks it on this computer.","muted"));
  else more.append(element("p",Number.isFinite(hit.best_score)?`Result #${rank}. Ranking score ${hit.best_score.toFixed(3)}: used for ordering only, not a probability.`:`Found by looking through the footage (part ${hit.scan_window}); no similarity score.`,"muted"));
  if(span) more.append(element("p","The key moment comes from the frames the AI pointed to. The event may run longer.","muted"));
  if(hasFocus) more.append(element("p","This clip combines several shorter pieces. “Strongest part” is the best-scoring piece, not the exact start and end of the event.","muted"));
  if(review){
    more.append(element("p","Images checked at: "+(review.sampled_timestamps.map(time).join(", ")||"none"),"muted"));
    if(review.evidence_timestamps.length){ const jumps=element("div",undefined,"actions"); for(const t of review.evidence_timestamps){ const b=element("button",`Jump to ${time(t)}`,"secondary small"); b.type="button"; b.onclick=()=>play(t,hit.end_sec); jumps.append(b); } more.append(jumps); }
  }
  info.append(more);
  const feedback=element("div",undefined,"review-feedback");
  feedback.append(element("span","Is this what you were looking for?","ask"));
  const saved=element("span",hit.human_review?`You answered “${answerNames[hit.human_review.assessment]}” before. Choose again to change it.`:"","muted"); saved.setAttribute("role","status");
  const buttons=[];
  for(const [value,label] of Object.entries(answerNames)){
    const choice=element("button",label,"secondary small"); choice.type="button"; choice.setAttribute("aria-pressed",String(hit.human_review?.assessment===value)); buttons.push(choice);
    choice.onclick=async()=>{
      buttons.forEach(b=>b.disabled=true); saved.textContent="Saving…";
      try{ await post("/api/feedback",{query,video_id:hit.video_id,start_sec:hit.start_sec,end_sec:hit.end_sec,search_mode:visual?"visual":"ranked",assessment:value});
        buttons.forEach(b=>b.setAttribute("aria-pressed",String(b===choice))); saved.textContent=`Saved: ${label}.`;
      }catch(error){ saved.textContent=error.message; }finally{ buttons.forEach(b=>b.disabled=false); }
    }; feedback.append(choice);
  }
  feedback.append(saved); info.append(feedback); card.append(pic,info); return card;
}

// ---------------------------------------------------------------- pre-analysed footage notes (no AI)
async function notesSearch(){
  const query=$("query").value.trim(); if(!query) return false;
  let data; try{ data=await post("/api/search/notes",{query}); }catch(error){ return false; }
  if(!data.hits.length){ $("results").replaceChildren(element("p",`Nothing in the pre-analysed footage matches “${data.query}”. You can search live with AI below (uses Google).`,"results-intro")); return false; }
  invalidateScenario();
  const intro=element("p",`Found ${data.hits.length} moment(s) for “${data.query}” in pre-analysed footage: described in advance by watching the recordings, so no AI request was needed. Watch each clip to confirm.`,"results-intro");
  const live=element("button","Also search live with AI (uses Google)","secondary small"); live.type="button";
  live.onclick=()=>{ live.disabled=true; reviewScenarioPlan(); };
  const head=element("div",undefined,"notes-head"); head.append(intro,live);
  $("results").replaceChildren(head,element("h3",`Matches (${data.hits.length})`));
  for(const [i,hit] of data.hits.entries()){ const card=resultCard(hit,data.query,true,i+1); window.scanFx?.reveal(card); $("results").append(card); }
  $("scenario-progress").textContent="";
  return true;
}

// ---------------------------------------------------------------- direct scenario scan
function refreshScanVideos(){
  const selected=$("scan-video").value;
  $("scan-video").replaceChildren(new Option("All recordings","all"));
  for(const v of videosCache.filter(v=>v.status==="done" && !v.camera?.hidden)) $("scan-video").append(new Option(displayName(v.filename),String(v.id)));
  if([...$("scan-video").options].some(o=>o.value===selected)) $("scan-video").value=selected;
}
function invalidateScenario(){
  const old=scenarioPlan; scenarioPlan=null; $("scenario-consent").checked=false; $("scenario-plan").hidden=true;
  if(old && !scenarioActive) post("/api/search/scan/cancel",{scan_id:old.scan_id}).catch(()=>{});
}
$("search-mode").onchange=()=>{invalidateScenario();updateControls();};
for(const id of ["scan-video","scan-start","scan-end"]) $(id).onchange=()=>{invalidateScenario();updateControls();};
$("scenario-consent").onchange=updateControls;
$("scenario-cancel").onclick=()=>{invalidateScenario();$("scenario-progress").textContent="";updateControls();};
async function reviewScenarioPlan(){
  invalidateScenario(); busy(true);
  $("scenario-progress").textContent="Getting ready… (nothing has been sent yet)";
  try{
    const selected=$("scan-video").value;
    // "All recordings" means every camera that isn't hidden; null lets the server include everything.
    const visible=videosCache.filter(v=>v.status==="done" && !v.camera?.hidden).map(v=>v.id);
    const all=visible.length<videosCache.filter(v=>v.status==="done").length ? visible : null;
    // Following a person: check every other visible camera, whatever "Search in" says.
    const follow=window.followCtx;
    const nearby=follow?window.followTargets(follow,visible):null;
    const ids=follow?nearby.ids:selected==="all"?all:[Number(selected)];
    if(follow && !ids.length) throw new Error("There are no other cameras to follow this person to.");
    const plan=await post("/api/search/scan/plan",{query:$("query").value,video_ids:ids,
      ...(selected!=="all"&&!follow?{start_sec:Number($("scan-start").value)||0,end_sec:$("scan-end").value===""?null:Number($("scan-end").value)}:{})});
    scenarioPlan=plan;
    $("scenario-plan-summary").textContent=(follow?`Follow this person from ${displayName(follow.source.filename)}: look for them on ${nearby.note(plan.recordings.length)}.`:`Look for “${plan.query}” in ${plural(plan.recordings.length,"recording")}.`)+` This sends up to ${plural(plan.max_images,"image")} in ${plural(plan.max_calls,"request")} to Google Gemini.`;
    $("scenario-plan-files").textContent=plan.recordings.map(v=>{const r=plan.ranges.find(r=>r.video_id===v.video_id);return `${displayName(v.filename)} (${time(r.start_sec)}–${time(r.end_sec)})`;}).join(" · ")+(plan.excluded.length?". Not included: "+plan.excluded.map(v=>displayName(v.filename)+" ("+v.reason+")").join("; "):"");
    $("scenario-plan-note").textContent=plan.note;
    $("scenario-plan").hidden=false;
    $("scenario-progress").textContent=connection?.scan_ready?"":"The AI isn't connected, so this search can't start. See Settings.";
    $("scenario-plan").scrollIntoView({block:"nearest",behavior:"smooth"});
  }catch(error){$("scenario-progress").textContent=error.message;}finally{busy(false);}
}
$("scenario-stop").onclick=()=>{scenarioStop=true;$("scenario-stop").disabled=true;$("scenario-progress").textContent="Stopping after the current step… Nothing more will be sent.";};
$("scenario-run").onclick=async()=>{
  if(!scenarioPlan || !$("scenario-consent").checked) return;
  const plan=scenarioPlan; scenarioStop=false; scenarioActive=true; busy(true);
  $("scenario-plan").hidden=true;
  $("scenario-stop").hidden=false;$("scenario-stop").disabled=false;
  const supported=element("div"),unclear=element("details",undefined,"result-group"),rejected=element("details",undefined,"result-group");
  const supportedTitle=element("h3","Searching…"),unclearTitle=element("summary","Maybe: worth a look"),rejectedTitle=element("summary","Checked: no match");
  unclear.append(unclearTitle);rejected.append(rejectedTitle);unclear.hidden=rejected.hidden=true;
  $("results").replaceChildren(element("p",`Results for “${plan.query}”. These are AI suggestions: always watch the clip before deciding.`,"results-intro"),supportedTitle,supported,unclear,rejected);
  let matches=0,unknown=0,negative=0,images=0,completed=0;
  const startedAt=performance.now();
  window.scanFx?.start(plan,$("results"),window.followCtx);   // visual progress only; it never sends anything
  // Up to three approved batches are checked at once; each is sent once, and a failure stops new ones.
  let nextBatch=0, failure=null;
  const progress=()=>{ $("scenario-progress").textContent=`Searching… ${Math.round(100*completed/Math.max(plan.windows,1))}% done. Keep this page open.`; };
  async function worker(){
    while(!scenarioStop && !failure && nextBatch<plan.max_calls){
      const batch=nextBatch++;
      progress(); window.scanFx?.batchStart(batch);
      let result;
      try{ result=await post("/api/search/scan/batch",{scan_id:plan.scan_id,batch,approve_frame_upload:true}); }
      catch(error){ failure=failure||error; return; }
      completed=Math.max(completed,result.completed_windows);images+=result.visual_review.sampled_frames;
      window.scanFx?.batchDone(batch,result); progress();
      for(const [key,target] of [["hits",supported],["unclear_hits",unclear],["rejected_hits",rejected]]) for(const hit of result[key]){
        const card=resultCard(hit,plan.query,true,hit.scan_window);
        if(key!=="rejected_hits") window.scanFx?.reveal(card);
        target.append(card);
      }
      matches+=result.hits.length;unknown+=result.unclear_hits.length;negative+=result.rejected_hits.length;
      supportedTitle.textContent=matches?`Likely matches (${matches})`:"Searching… no likely match yet";
      unclearTitle.textContent=`Maybe: worth a look (${unknown})`;unclear.hidden=!unknown;unclear.open=matches===0 && unknown>0;
      rejectedTitle.textContent=`Checked: no match (${negative})`;rejected.hidden=!negative;
    }
  }
  try{
    await Promise.all(Array.from({length:Math.min(3,plan.max_calls)},worker));
    if(failure) throw failure;
    if(!matches) supportedTitle.textContent=unknown?"No likely matches. Check the “maybe” clips below.":"No likely matches";
    $("scenario-progress").textContent=`${scenarioStop?"Stopped early":"Done"}: ${matches} likely, ${unknown} maybe (${images} images checked${scenarioStop?`, ${completed} of ${plan.windows} parts`:""}). The same event can show up in two neighbouring clips. Not finding something doesn't prove it didn't happen.`;
    window.scanFx?.finish({seconds:(performance.now()-startedAt)/1000,images,completed,stopped:scenarioStop});
  }catch(error){if(!matches) supportedTitle.textContent="Search didn't finish";
    // Make a refused request unmistakable: nothing was checked, so "no match" would be misleading.
    const refused=/usage limit|quota|HTTP 429|HTTP 503|could not finish|did not finish/i.test(error.message);
    if(refused){ const b=element("div",undefined,"banner error search-refused"); b.append(icon("alert"),element("span",/usage limit|quota|429/i.test(error.message)
      ?"Google refused this search: your API key's daily limit is used up, so the AI did not look at the footage. Enable billing for the key in Google AI Studio (aistudio.google.com → API keys), or try again after the limit resets."
      :"Google did not answer, so the AI did not look at the footage. Check the internet connection and try again.")); $("results").prepend(b); }$("scenario-progress").textContent=`Search stopped after ${completed} of ${plan.windows} parts: ${error.message} Results so far are shown below. Only “Google is busy” replies are retried (up to 3 tries); nothing else was resent.`;
    window.scanFx?.finish({seconds:(performance.now()-startedAt)/1000,images,completed,error:error.message});}
  finally{
    await post("/api/search/scan/cancel",{scan_id:plan.scan_id}).catch(()=>{});
    scenarioActive=false;scenarioPlan=null;window.followCtx=null;$("scenario-consent").checked=false;$("scenario-plan").hidden=true;$("scenario-stop").hidden=true;busy(false);
  }
};

// ---------------------------------------------------------------- AI preparation (paid, explicit)
$("plan-button").onclick=async()=>{
  busy(true); $("sync-plan").hidden=true;
  try{
    const plan=await post("/api/search/plan");
    planHasChanges=plan.to_index.length>0 || plan.removals>0;
    $("sync-approval").hidden=!planHasChanges;
    $("plan-summary").textContent=planHasChanges?`${plural(plan.to_index.length,"video")} to upload · ${plan.removals} old entries to remove · ${plan.up_to_date} already set up. Estimated cost: about US$${plan.estimated_cost_usd.toFixed(4)} (an estimate, not a limit).`:`Everything is already set up (${plural(plan.up_to_date,"video")}). Nothing to upload.`;
    $("plan-files").textContent=(plan.to_index.map(displayName).join(", "))+(plan.not_searchable.length?` Can't be used with quick search: ${plan.not_searchable.map(displayName).join(", ")}.`:"");
    $("sync-consent").checked=false; $("sync-plan").hidden=false;
  }catch(error){ notice(error.message); }finally{ busy(false); }
};
$("sync-button").onclick=async()=>{
  if(!planHasChanges || !$("sync-consent").checked){ notice("Please review the plan and tick the approval box first."); return; }
  busy(true); notice("Setting up quick search. This can take several minutes. Keep this page open.");
  try{
    const result=await post("/api/search/sync",{confirmed:true});
    $("sync-plan").hidden=true; notice(result.ok?"Quick search is set up.":"Some videos couldn't be set up. See the messages below.");
    $("sync-messages").replaceChildren(...result.messages.map(message=>element("p",message,"muted")));
    await Promise.all([library(),status()]);
  }catch(error){ notice(error.message); }finally{ busy(false); }
};

status().catch(error=>notice(error.message));
route();
