"use strict";
// Hash-routed pages: #dashboard, #library, #watch/<id>?t=&end=, #search, #investigations, #system.
// All server and user text is inserted with textContent; nothing is inserted as HTML.
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="csrf-token"]').content;
let connection = null, operationRunning = false, planHasChanges = false;
let videosCache = [], waitingFiles = [], unsupportedFiles = [], activeVideo = null, framePage = 0, watchToken = 0, currentMoment = 0, watchWindow = null;
const time = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.floor((seconds || 0) % 60)).padStart(2,"0")}`;
function element(tag, text, className) { const node=document.createElement(tag); if(text !== undefined) node.textContent=text; if(className) node.className=className; return node; }
function icon(name) { const ns="http://www.w3.org/2000/svg", svg=document.createElementNS(ns,"svg"), use=document.createElementNS(ns,"use"); use.setAttribute("href","#i-"+name); svg.append(use); return svg; }
let noticeTimer=null;
function notice(text) { $("notice").textContent=text; clearTimeout(noticeTimer); if(text) noticeTimer=setTimeout(()=>{$("notice").textContent="";},9000); }
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{"X-CSRF-Token":token,...options.headers}});
  let data; try{data=await response.json();}catch(e){throw new Error(`The server returned an unexpected response (${response.status}).`);}
  if(!response.ok) throw new Error(data.error || "The request failed. Please try again.");
  return data;
}
function post(path, payload) { return api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload||{})}); }

// ---------------------------------------------------------------- routing
const titles={dashboard:"Dashboard",library:"Video Library",watch:"Video player",search:"Search",investigations:"Investigations",system:"System & AI setup"};
function route() {
  const hash=location.hash.slice(1)||"dashboard", [path,query=""]=hash.split("?"), [view,arg]=path.split("/");
  const page=titles[view] ? view : "dashboard";
  document.querySelectorAll(".page").forEach(p=>{p.hidden=p.dataset.page!==page;});
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.view===(page==="watch"?"library":page)));
  $("page-title").textContent=titles[page];
  if(page!=="watch"){ $("player").pause(); activeVideo=null; }
  if(page==="watch"){ const params=new URLSearchParams(query); showWatch(Number(arg),Number(params.get("t"))||0,params.has("end")?Number(params.get("end")):null); }
  if(page==="dashboard") library().catch(error=>notice(error.message)).finally(renderDashboard);
  if(page==="library") library().catch(error=>notice(error.message));
  if(page==="system") Promise.all([library(),status()]).catch(error=>notice(error.message));
  window.scrollTo(0,0);
}
window.addEventListener("hashchange",route);
function openVideo(id,name,url,start=0,end=null) {
  const hash=`#watch/${id}?t=${start||0}`+(end!==null&&end!==undefined?`&end=${end}`:"");
  if(location.hash===hash) route(); else location.hash=hash;
}

// ---------------------------------------------------------------- status
async function status() {
  const data=await api("/api/status"); connection=data;
  const prepared=data.coverage.prepared.length, pending=data.coverage.needs_preparation.length;
  $("ai-pill").textContent=data.search_ready ? `AI search: ${prepared} video(s) prepared` : "AI search: setup needed";
  $("ai-pill").classList.toggle("ready",data.search_ready);
  $("setup").textContent=data.search_ready ? (prepared ? `Search covers ${prepared} prepared video(s). New uploads need AI preparation (System & AI setup) before they can be searched.` : "Your AI connection is configured, but no videos are prepared for search yet. Open System & AI setup to review the AI indexing plan.") : "Local indexing and playback work now. AI search needs "+(!data.engine_ready?"the SentrySearch environment":"")+(!data.engine_ready&&!data.key_ready?" and ":"")+(!data.key_ready?"a Gemini API key":"")+" (see System & AI setup).";
  $("coverage").textContent=pending ? `${pending} video(s) still need AI preparation: ${data.coverage.needs_preparation.join(", ")}.` : "";
  $("setup-details").open=!data.search_ready;
  renderStatusList($("system-status")); updateControls();
}
function statusItems() {
  if(!connection) return [["warn","Checking…"]];
  const c=connection.coverage, items=[];
  items.push(["ok","Local library, frame extraction and playback work offline."]);
  items.push([connection.engine_ready?"ok":"warn",connection.engine_ready?"SentrySearch environment found.":"SentrySearch environment not configured (TANYA_SENTRY_PYTHON)."]);
  items.push([connection.key_ready?"ok":"warn",connection.key_ready?"Gemini API key is set for this window.":"No Gemini API key set: AI search is unavailable."]);
  items.push([c.needs_preparation.length?"warn":"ok",`${c.prepared.length} video(s) prepared for AI search, ${c.needs_preparation.length} waiting for preparation.`]);
  if(c.unsupported.length) items.push(["warn",`${c.unsupported.length} video(s) cannot be AI-searched (MP4 / MOV only).`]);
  if(waitingFiles.length) items.push(["warn",`${waitingFiles.length} file(s) in the video folder are not indexed yet.`]);
  return items;
}
function renderStatusList(list) {
  list.replaceChildren(...statusItems().map(([kind,text])=>{const li=element("li",undefined,kind);li.append(icon(kind==="ok"?"check":"alert"),element("span",text));return li;}));
}
function updateControls() {
  const visual=$("visual-check").checked;
  $("search-button").disabled=operationRunning || !connection?.search_ready || !connection?.coverage.prepared.length || (visual && !$("visual-consent").checked);
  $("search-button").textContent=visual ? "Search & check matches" : "Search ranked clips";
  $("visual-consent-panel").hidden=!visual;
  for(const id of ["visual-check","visual-consent","query","index-button","upload-button"]) $(id).disabled=operationRunning;
  $("plan-button").disabled=operationRunning || !connection?.engine_ready;
  $("sync-button").disabled=operationRunning || !planHasChanges;
  $("busy-pill").hidden=!operationRunning;
}
function busy(value) { operationRunning=value; updateControls(); }
$("visual-check").onchange=()=>{$("visual-consent").checked=false;updateControls();};
$("visual-consent").onchange=updateControls;
$("query").addEventListener("input",()=>{$("visual-consent").checked=false;updateControls();});

// ---------------------------------------------------------------- dashboard
function stat(label,value,sub,href,kind) {
  const card=element("a",undefined,"stat"+(kind?" "+kind:"")); card.href=href;
  card.append(element("div",label,"label"),element("div",String(value),"value"),element("div",sub,"sub")); return card;
}
async function renderDashboard() {
  let cases=[];
  try{ cases=(await api("/api/investigations")).investigations; }catch(e){ notice(e.message); }
  const done=videosCache.filter(v=>v.status==="done").length, failed=videosCache.filter(v=>v.status==="failed"||v.playback?.status==="missing").length;
  const prepared=videosCache.filter(v=>v.search_state==="prepared").length, open=cases.filter(c=>c.status==="open");
  const unreviewed=cases.reduce((s,c)=>s+c.unreviewed_count,0);
  $("stats").replaceChildren(
    stat("Videos",videosCache.length,`${time(videosCache.reduce((s,v)=>s+(v.duration_sec||0),0))} of footage`+(waitingFiles.length?` · ${waitingFiles.length} waiting to index`:""),"#library","primary"),
    stat("Frames ready",done,`${videosCache.reduce((s,v)=>s+v.frame_count,0).toLocaleString()} frames extracted`,"#library"),
    stat("Problems",failed,failed?"failed or missing originals":"none","#library",failed?"alert":""),
    stat("AI-prepared",prepared,`of ${videosCache.length} video(s) searchable`,"#system"),
    stat("Investigations",cases.length,`${open.length} open · ${unreviewed} unreviewed clip(s)`,"#investigations",unreviewed?"attention":""));
  const recent=$("dash-videos"); recent.replaceChildren();
  if(!videosCache.length) recent.append(element("p","No recordings yet. Add footage in the Video Library.","empty"));
  for(const v of videosCache.slice(0,6)){
    const b=element("button",undefined,"mini"); b.type="button"; b.append(thumb(v)); b.append(element("strong",v.filename),element("span",`${time(v.duration_sec)} · ${v.status==="done"?"frames ready":v.status}`,"muted"));
    b.onclick=()=>openVideo(v.id); recent.append(b);
  }
  const box=$("dash-cases"); box.replaceChildren();
  if(!cases.length) box.append(element("p","No investigations yet.","empty"));
  for(const c of cases.slice(0,6)){
    const row=element("button",undefined,"row-link"); row.type="button";
    row.append(element("strong",c.title),element("span",`${c.status==="open"?"Open":"Closed"} · ${c.evidence_count} clip(s) · ${c.unreviewed_count} unreviewed`,"muted"));
    row.onclick=()=>{ location.hash="#investigations"; if(window.openInvestigation) window.openInvestigation(c.id); }; box.append(row);
  }
  renderStatusList($("dash-status"));
}

// ---------------------------------------------------------------- library
const searchLabels={prepared:["AI prepared",""],needs_preparation:["Needs AI preparation","pending"],unsupported:["AI search: MP4 / MOV only","neutral"],local_index_needed:["Local indexing needed","pending"]};
const playLabels={playable:["Plays in browser","info"],copy_ready:["Browser copy ready","info"],needs_copy:["Needs browser copy","pending"],missing:["Original missing","failed"]};
function thumb(video) {
  const box=element("div",undefined,"thumb");
  if(video.thumbnail_url){const img=element("img");img.src=video.thumbnail_url;img.alt=`First frame of ${video.filename}`;img.loading="lazy";box.append(img);}
  else box.append(element("span",video.status==="failed"?"No frames (failed)":"No frames yet"));
  if(video.duration_sec) box.append(element("span",time(video.duration_sec),"duration"));
  const play=element("span",undefined,"play"); play.append(icon("play")); box.append(play);
  return box;
}
async function library() {
  const data=await api("/api/videos");
  videosCache=data.videos; waitingFiles=data.waiting_files; unsupportedFiles=data.unsupported_files;
  renderLibrary();
}
function matchesFilter(v) {
  const text=$("library-filter").value.trim().toLowerCase(), f=$("library-status").value;
  if(text && !v.filename.toLowerCase().includes(text)) return false;
  if(f==="done") return v.status==="done";
  if(f==="failed") return v.status==="failed" || v.playback?.status==="missing";
  if(f==="prepared"||f==="needs_preparation") return v.search_state===f;
  if(f==="browser_copy") return v.playback?.status==="needs_copy";
  return true;
}
function renderLibrary() {
  const unsupported=unsupportedFiles;
  const banner=$("waiting"); banner.replaceChildren();
  banner.hidden=!waitingFiles.length && !unsupported.length;
  if(waitingFiles.length){
    banner.append(icon("alert"),element("span",`${waitingFiles.length} file(s) in the video folder are not in the library yet: ${waitingFiles.slice(0,5).join(", ")}${waitingFiles.length>5?"…":""}.`));
    const b=element("button","Index now","secondary"); b.type="button"; b.onclick=()=>$("index-button").click(); banner.append(b);
  }
  if(unsupported.length) banner.append(element("span",`Ignored (not a supported video type): ${unsupported.slice(0,5).join(", ")}${unsupported.length>5?"…":""}.`,"muted"));
  const grid=$("videos"), shown=videosCache.filter(matchesFilter); grid.replaceChildren();
  $("library-count").textContent=`${shown.length} of ${videosCache.length} recording(s)`;
  if(!videosCache.length){ const e=element("div",undefined,"card empty-state"); e.append(icon("library"),element("h2","Your library is empty"),element("p",waitingFiles.length?"Index the files waiting in the video folder, or add footage.":"Add authorised footage to start.","muted")); grid.append(e); return; }
  if(!shown.length) grid.append(element("p","No recordings match this filter.","empty"));
  for(const v of shown){
    const card=element("article",undefined,"video-card");
    const open=element("button",undefined,"thumb-button"); open.type="button"; open.setAttribute("aria-label",`Play ${v.filename}`); open.append(thumb(v)); open.onclick=()=>openVideo(v.id);
    const body=element("div",undefined,"video-body");
    body.append(element("h3",v.filename),element("p",`${time(v.duration_sec)} · ${v.frame_count} frames · ${v.width||"—"} × ${v.height||"—"}${v.playback?.codec_name?` · ${v.playback.codec_name}`:""}`,"meta"));
    const badges=element("div");
    badges.append(element("span",v.status==="done"?"Frames ready":v.status==="failed"?"Indexing failed":"Processing","badge"+(v.status==="done"?"":v.status==="failed"?" failed":" pending")));
    const [pl,pk]=playLabels[v.playback?.status]||["Playback unknown","neutral"]; badges.append(element("span",pl,"badge "+pk));
    const [sl,sk]=searchLabels[v.search_state]; badges.append(element("span",sl,"badge "+sk));
    body.append(badges);
    if(v.error) body.append(element("p",v.error,"error-text"));
    if(v.playback?.status==="missing") body.append(element("p",v.playback.message,"error-text"));
    const actions=element("div",undefined,"card-actions"), play=element("button","Play"); play.type="button"; play.prepend(icon("play")); play.onclick=()=>openVideo(v.id);
    actions.append(play); body.append(actions); card.append(open,body); grid.append(card);
  }
}
$("library-filter").addEventListener("input",()=>renderLibrary());
$("library-status").onchange=()=>renderLibrary();
$("toggle-upload").onclick=()=>{ $("upload-form").hidden=!$("upload-form").hidden; };

// ---------------------------------------------------------------- watch
const mediaErrors={1:"Playback was stopped before the video loaded.",2:"A network error stopped the video from loading. Check that the website is still running.",3:"The browser could not decode this video. It may be damaged.",4:"This browser cannot play this video format."};
function overlay(text){ $("player-overlay").hidden=!text; $("player-overlay-text").textContent=text||""; }
function playerError(text){ $("player-error").hidden=!text; $("player-error").textContent=text||""; if(text) overlay(null); }
function resetPlayer(){ const p=$("player"); p.pause(); p.removeAttribute("src"); p.load(); playerError(null); overlay(null); }
async function showWatch(id,start,end) {
  const myToken=++watchToken; activeVideo=id; framePage=0; currentMoment=start; watchWindow=end!==null?[start,end]:null;
  resetPlayer(); $("frames").replaceChildren(); $("more-frames").hidden=true; $("player-window").hidden=true; $("replay-window").hidden=true;
  let video=videosCache.find(v=>v.id===id);
  if(!video){ try{await library();}catch(e){} video=videosCache.find(v=>v.id===id); }
  if(myToken!==watchToken) return;
  if(!video){ $("watch-title").textContent="Recording not found"; $("watch-meta").textContent=""; $("watch-details").replaceChildren(); $("download-video").hidden=true; playerError("This video is no longer in the library. Go back to the library and choose another recording."); return; }
  $("watch-title").textContent=video.filename;
  $("watch-meta").textContent=`${time(video.duration_sec)} · ${video.width||"—"} × ${video.height||"—"} · ${video.frame_count} frames`;
  const dl=$("watch-details"); dl.replaceChildren();
  for(const [k,val] of [["File",video.rel_path],["Duration",time(video.duration_sec)],["Frame rate",video.fps?`${video.fps.toFixed(1)} fps`:"—"],["Video codec",video.playback?.codec_name||"—"],["Size",`${(video.size_bytes/1048576).toFixed(1)} MB`],["Content hash",video.sha256.slice(0,16)+"…"],["Indexed",video.status==="done"?"Frames ready":video.status]]) dl.append(element("dt",k),element("dd",val));
  $("download-video").hidden=false; $("download-video").href=video.video_url; $("download-video").download=video.filename;
  $("player-window").hidden=!watchWindow; $("replay-window").hidden=!watchWindow;
  if(watchWindow) $("player-window").textContent=`Result window ${time(watchWindow[0])}–${time(watchWindow[1])}`;
  updateTime(); loadFrames(); fillWatchCases();
  overlay("Checking whether this browser can play the recording…");
  try{
    let info=await api(`/api/videos/${id}/playback`);
    if(myToken!==watchToken) return;
    if(info.status==="missing"){ $("download-video").hidden=true; playerError(info.message); return; }
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
  }catch(error){ if(myToken===watchToken) playerError(error.message+" The frame timeline below still works."); }
}
function updateTime(){ const p=$("player"); if(p.getAttribute("src")) currentMoment=p.currentTime; $("player-time").textContent=`${time(currentMoment)} / ${time(p.duration||videosCache.find(v=>v.id===activeVideo)?.duration_sec)}`; }
$("player").addEventListener("timeupdate",updateTime);
$("player").addEventListener("seeked",updateTime);
$("player").addEventListener("waiting",()=>{ if(!$("player").error) overlay("Buffering…"); });
$("player").addEventListener("playing",()=>overlay(null));
$("player").addEventListener("canplay",()=>{ if($("player-overlay-text").textContent==="Buffering…") overlay(null); });
$("replay-window").onclick=()=>{ if(!watchWindow) return; const p=$("player"); p.currentTime=watchWindow[0]; p.play().catch(()=>{}); };
$("watch-back").onclick=()=>{ location.hash="#library"; };
function seek(t){ currentMoment=t; const p=$("player"); if(p.getAttribute("src")&&!p.error) p.currentTime=t; updateTime(); }
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
  const duplicateNote=duplicates.length ? ` ${duplicates.length} file(s) were identical to videos already in the library and were not added again.` : "";
  notice((failed.length ? `Indexing finished with ${failed.length} failed video(s). Filter the library by “Problems” for details.` : "Frames are ready. To make new videos searchable, review the AI indexing plan under System & AI setup.")+duplicateNote);
}
$("index-button").onclick=async()=>{ busy(true); notice("Extracting frames… Keep this page open."); try{await indexVideos();}catch(error){notice(error.message);}finally{busy(false);} };
$("upload-form").onsubmit=async event=>{
  event.preventDefault(); const file=$("video-file").files[0];
  if(file && file.size>512*1024*1024){ notice("Choose a video smaller than 512 MB."); return; }
  busy(true); notice("Uploading your video…");
  try{
    const uploaded=await api("/api/upload",{method:"POST",body:new FormData(event.target)});
    if(uploaded.duplicate_of){ notice(`This video is already in your library as ${uploaded.duplicate_of}. No second copy was added.`); event.target.reset(); return; }
    notice("Upload complete. Extracting frames…"); await indexVideos(); event.target.reset(); $("upload-form").hidden=true;
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
document.querySelectorAll("#examples .chip").forEach(chip=>{ chip.onclick=()=>{ $("query").value=chip.textContent; $("visual-consent").checked=false; updateControls(); $("query").focus(); }; });
function saveToId(){ const value=$("save-to").value; return value ? Number(value) : null; }
$("search-form").onsubmit=async event=>{
  event.preventDefault();
  const visual=$("visual-check").checked, approved=$("visual-consent").checked;
  if(visual && !approved){ notice("Approve the sampled-frame check, or uncheck image checking to see rankings only."); return; }
  busy(true);
  const loading=element("div",undefined,"card loading-line"); loading.append(element("div",undefined,"spinner"),element("span",visual?"Retrieving candidates and checking their sampled images… This can take a few minutes.":"Searching prepared videos…"));
  $("results").replaceChildren(loading);
  try{
    const data=await post("/api/search",{query:$("query").value,visual_check:visual,approve_frame_upload:approved,...(saveToId()?{investigation_id:saveToId()}:{})});
    $("results").replaceChildren(element("p",data.note,"muted"));
    $("results").append(element("p",visual?"AI-supported candidates are based only on sampled images. They can be wrong and are not confirmed detections.":"Rankings only: nearest clips can appear even when the described event is absent. No image matching check was performed.","warning"));
    for(const warning of data.warnings) $("results").append(element("p",warning,"warning"));
    if(data.visual_review){
      $("results").append(element("h3",`${data.visual_review.supported} supported · ${data.visual_review.unclear} unclear · ${data.visual_review.rejected} not supported`));
      $("results").append(element("p",`${data.visual_review.sampled_frames} images checked from ${data.visual_review.checked_candidates} retrieved windows.`,"muted"));
    }
    if(!data.hits.length){ const e=element("div",undefined,"card empty-state"); e.append(icon("search"),element("h2","No matching clips"),element("p",visual?"No visually supported match in the checked samples. "+(data.unclear_hits?.length?"Review unclear candidates below. ":"")+"This does not prove the event is absent.":"No ranked clips were returned from your prepared videos. Try different wording.","muted")); $("results").append(e); }
    const ranked=[...data.hits,...(data.unclear_hits||[]),...(data.rejected_hits||[])];
    if(data.saved_query) $("results").append(element("p",`Saved to the selected investigation as “${data.saved_query.query}”.`,"muted"));
    for(const hit of data.hits) $("results").append(resultCard(hit,data.query,visual,ranked.indexOf(hit)+1));
    for(const [key,title] of [["unclear_hits","Unclear or not checked — review manually"],["rejected_hits","Not supported by sampled images"]]){
      if(data[key]?.length){ const details=element("details"); details.append(element("summary",`${title} (${data[key].length})`)); for(const hit of data[key]) details.append(resultCard(hit,data.query,visual,ranked.indexOf(hit)+1)); $("results").append(details); }
    }
    if(saveToId() && window.refreshInvestigation) window.refreshInvestigation();
  }catch(error){ const e=element("div",undefined,"banner error"); e.append(icon("alert"),element("span",error.message+" No visual result was confirmed.")); $("results").replaceChildren(e); }
  finally{ $("visual-consent").checked=false; busy(false); }
};
function resultCard(hit, query, visual, rank){
  const card=element("article",undefined,"result");
  if(hit.thumbnail_url){ const img=element("img"); img.src=hit.thumbnail_url; img.alt=`Candidate frame from ${hit.filename}`; card.append(img); }
  else card.append(element("div","No frame","video-placeholder"));
  const info=element("div"), review=hit.visual_review;
  const labels={supported:"AI-supported candidate · human review required",not_supported:"Not supported in samples",unclear:"Unclear · manual review needed"};
  info.append(element("h3",`#${rank} · ${hit.filename}`),element("span",review?labels[review.verdict]:"Ranked candidate · not visually checked","badge info"));
  const reviewNames={correct:"Correct",wrong:"Wrong",unsure:"Unsure"};
  const humanBadge=element("span",hit.human_review?`Your earlier review: ${reviewNames[hit.human_review.assessment]}`:"Not yet reviewed by a person","badge "+(hit.human_review?"":"pending"));
  info.append(humanBadge);
  info.append(element("p",`${time(hit.start_sec)} – ${time(hit.end_sec)}`,"when"),element("p",`Ranking score ${hit.best_score.toFixed(3)} — a similarity signal for ordering, not a probability.`,"muted"));
  if(review){
    info.append(element("p",review.reason),element("p","Sampled times: "+(review.sampled_timestamps.map(time).join(", ")||"none"),"muted"));
    for(const t of review.evidence_timestamps){ const b=element("button",`Review evidence at ${time(t)}`,"secondary"); b.type="button"; b.onclick=()=>openVideo(hit.video_id,hit.filename,hit.video_url,t,hit.end_sec); info.append(b); }
  }
  const actions=element("div",undefined,"actions"), watch=element("button",`Play from ${time(hit.start_sec)}`); watch.type="button"; watch.prepend(icon("play"));
  watch.onclick=()=>openVideo(hit.video_id,hit.filename,hit.video_url,hit.start_sec,hit.end_sec); actions.append(watch);
  if(window.investigationClipButton) actions.append(window.investigationClipButton(hit,query,visual,rank));
  info.append(actions);
  const feedback=element("div",undefined,"review-feedback");
  feedback.append(element("p","Does this clip match your search? Your review stays on this computer."));
  const saved=element("span",hit.human_review?`Earlier review saved ${new Date(hit.human_review.reviewed_at).toLocaleString()}. Choose again to change it.`:"","muted"); saved.setAttribute("role","status");
  const buttons=[];
  for(const [value,label] of [["correct","Correct"],["wrong","Wrong"],["unsure","Unsure"]]){
    const choice=element("button",label,"secondary"); choice.type="button"; choice.setAttribute("aria-pressed",String(hit.human_review?.assessment===value)); buttons.push(choice);
    choice.onclick=async()=>{
      buttons.forEach(b=>b.disabled=true); saved.textContent="Saving…";
      try{ await post("/api/feedback",{query,video_id:hit.video_id,start_sec:hit.start_sec,end_sec:hit.end_sec,search_mode:visual?"visual":"ranked",assessment:value});
        buttons.forEach(b=>b.setAttribute("aria-pressed",String(b===choice))); saved.textContent=`Saved: ${label}.`; humanBadge.textContent=`Your review: ${label}`; humanBadge.className="badge";
      }catch(error){ saved.textContent=error.message; }finally{ buttons.forEach(b=>b.disabled=false); }
    }; feedback.append(choice);
  }
  feedback.append(saved); info.append(feedback); card.append(info); return card;
}

// ---------------------------------------------------------------- AI preparation (paid, explicit)
$("plan-button").onclick=async()=>{
  busy(true); $("sync-plan").hidden=true;
  try{
    const plan=await post("/api/search/plan");
    planHasChanges=plan.to_index.length>0 || plan.removals>0;
    $("sync-approval").hidden=!planHasChanges;
    $("plan-summary").textContent=`${plan.to_index.length} video(s) to prepare · ${plan.removals} stale search entries to remove · ${plan.up_to_date} already prepared. Estimated paid-tier cost: US$${plan.estimated_cost_usd.toFixed(4)} (estimate, not a spending cap).`;
    $("plan-files").textContent=(plan.to_index.join(", ")||"No new videos to prepare.")+(plan.not_searchable.length?` Unsupported for AI search: ${plan.not_searchable.join(", ")}.`:"");
    $("sync-consent").checked=false; $("sync-plan").hidden=false;
  }catch(error){ notice(error.message); }finally{ busy(false); }
};
$("sync-button").onclick=async()=>{
  if(!planHasChanges || !$("sync-consent").checked){ notice("Please review the plan and tick the approval box first."); return; }
  busy(true); notice("Preparing the AI index. This can take several minutes. Keep this page open.");
  try{
    const result=await post("/api/search/sync",{confirmed:true});
    $("sync-plan").hidden=true; notice(result.ok?"AI indexing complete. You can now search your prepared footage.":"Some videos could not be prepared. Review the messages below.");
    $("sync-messages").replaceChildren(...result.messages.map(message=>element("p",message,"muted")));
    await Promise.all([library(),status()]);
  }catch(error){ notice(error.message); }finally{ busy(false); }
};

status().catch(error=>notice(error.message));
route();
