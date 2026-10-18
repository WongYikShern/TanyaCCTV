"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="csrf-token"]').content;
let activeVideo = null, framePage = 0;
let connection = null, operationRunning = false;
let planHasChanges = false;
const time = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.floor((seconds || 0) % 60)).padStart(2,"0")}`;
function element(tag, text, className) { const node=document.createElement(tag); if(text !== undefined) node.textContent=text; if(className) node.className=className; return node; }
function notice(text) { $("notice").textContent=text; }
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{"X-CSRF-Token":token,...options.headers}});
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || "The request failed. Please try again.");
  return data;
}
async function status() {
  const data=await api("/api/status");
  connection=data;
  const prepared=data.coverage.prepared.length, pending=data.coverage.needs_preparation.length;
  $("search-state").textContent=data.search_ready ? `${prepared} video(s) prepared` : "Setup needed";
  $("setup").textContent=data.search_ready ? (prepared ? `Search covers ${prepared} prepared video(s). New uploads need AI preparation before they can be searched.` : "Your AI connection is configured, but no videos are prepared for search yet. Review the AI indexing plan below to get started.") : "Local indexing works now. AI search needs " + (!data.engine_ready ? "the SentrySearch environment" : "") + (!data.engine_ready && !data.key_ready ? " and " : "") + (!data.key_ready ? "a Gemini API key" : "") + ".";
  $("coverage").textContent=pending ? `${pending} video(s) still need AI preparation: ${data.coverage.needs_preparation.join(", ")}. Click ‘Review AI indexing plan’ to include them in search.` : "";
  $("setup-details").open=!data.search_ready;
  updateControls();
}
function updateControls() {
  const visual=$("visual-check").checked;
  $("search-button").disabled=operationRunning || !connection?.search_ready || !connection?.coverage.prepared.length || (visual && !$("visual-consent").checked);
  $("search-button").textContent=visual ? "Search & check matches ↗" : "Search ranked clips ↗";
  $("visual-consent-panel").hidden=!visual;
  $("visual-check").disabled=operationRunning;$("visual-consent").disabled=operationRunning;$("query").disabled=operationRunning;
  $("plan-button").disabled=operationRunning || !connection?.engine_ready;
  $("sync-button").disabled=operationRunning || !planHasChanges;
  $("index-button").disabled=operationRunning;
  $("upload-button").disabled=operationRunning;
}
function busy(value) { operationRunning=value;updateControls(); }
$("visual-check").onchange=()=>{$("visual-consent").checked=false;updateControls();};
$("visual-consent").onchange=updateControls;
$("query").addEventListener("input",()=>{$("visual-consent").checked=false;updateControls();});
async function library() {
  const {videos}=await api("/api/videos");
  $("video-count").textContent=videos.length;
  $("frame-count").textContent=videos.reduce((sum,v)=>sum+v.frame_count,0).toLocaleString();
  $("duration-count").textContent=time(videos.reduce((sum,v)=>sum+(v.duration_sec||0),0));
  $("videos").replaceChildren();
  if(!videos.length) $("videos").append(element("div","Your library is empty. Upload your first video to start exploring.","empty"));
  for(const video of videos) {
    const card=element("button",undefined,"video-card");card.type="button";
    if(video.thumbnail_url){const img=element("img");img.src=video.thumbnail_url;img.alt=`First frame of ${video.filename}`;img.loading="lazy";card.append(img);}
    else card.append(element("div","No frames yet","video-placeholder"));
    const info=element("div",undefined,"video-info");info.append(element("h3",video.filename));
    info.append(element("p",`${time(video.duration_sec)} · ${video.frame_count} frames · ${video.width||"—"} × ${video.height||"—"}`));
    info.append(element("span",video.status==="done"?"Frames ready":video.status,"badge "+video.status));
    const labels={prepared:"AI prepared",needs_preparation:"AI preparation needed",unsupported:"AI search: MP4 / MOV only",local_index_needed:"Local indexing needed"};
    info.append(element("span",labels[video.search_state],"badge "+(video.search_state==="prepared"?"":"pending")));
    if(video.error)info.append(element("p",video.error));
    card.append(info);card.onclick=()=>openVideo(video.id,video.filename,video.video_url);$("videos").append(card);
  }
}
async function loadFrames() {
  const id=activeVideo, page=framePage;
  $("more-frames").disabled=true;
  try {
    const data=await api(`/api/videos/${id}/frames?page=${page}`);
    if(activeVideo!==id)return;
    for(const frame of data.frames) {
      const button=element("button");button.type="button";
      const img=element("img");img.src=frame.url;img.alt=`Frame at ${time(frame.timestamp_sec)}`;img.loading="lazy";
      button.append(img,element("span",time(frame.timestamp_sec)));
      button.onclick=()=>{$("player").currentTime=frame.timestamp_sec;};$("frames").append(button);
    }
    $("more-frames").hidden=!data.has_more;framePage++;
  } catch(error){notice(error.message);} finally{$("more-frames").disabled=false;}
}
async function openVideo(id,name,url,start=0,end=null) {
  activeVideo=id;framePage=0;$("viewer-title").textContent=name;$("frames").replaceChildren();
  $("player").src=url+(end!==null?`#t=${start},${end}`:"");
  $("download-video").href=url;$("download-video").download=name;
  if(!$("viewer").open)$("viewer").showModal();
  await loadFrames();
}
$("close-viewer").onclick=()=>$("viewer").close();
$("viewer").addEventListener("close",()=>{$("player").pause();activeVideo=null;});
$("more-frames").onclick=loadFrames;
async function indexVideos() {
  const summary=await api("/api/index",{method:"POST"});
  const failed=summary.outcomes.filter(item=>item.status==="failed");
  await Promise.all([library(),status()]);
  $("sync-plan").hidden=true;$("results").replaceChildren();
  notice(failed.length ? `Indexing finished with ${failed.length} failed video(s). Check the library for details.` : "Frames are ready. For new uploads, the next step is ‘Review AI indexing plan’, then approve preparation before searching.");
}
$("index-button").onclick=async()=>{
  busy(true);notice("Extracting frames… Keep this page open.");
  try{await indexVideos();}catch(error){notice(error.message);}finally{busy(false);}
};
$("upload-form").onsubmit=async event=>{
  event.preventDefault();const file=$("video-file").files[0];
  if(file && file.size>512*1024*1024){notice("Choose a video smaller than 512 MB.");return;}
  busy(true);notice("Uploading your video…");
  try{await api("/api/upload",{method:"POST",body:new FormData(event.target)});notice("Upload complete. Extracting frames…");await indexVideos();event.target.reset();}
  catch(error){notice(error.message);}finally{busy(false);}
};
$("search-form").onsubmit=async event=>{
  event.preventDefault();
  const visual=$("visual-check").checked, approved=$("visual-consent").checked;
  if(visual && !approved){notice("Approve the sampled-frame check, or uncheck image checking to see rankings only.");return;}
  busy(true);$("results").replaceChildren(element("p",visual ? "Retrieving candidates and checking their sampled images… This can take a few minutes." : "Searching prepared videos only…","muted"));
  try{
    const data=await api("/api/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:$("query").value,visual_check:visual,approve_frame_upload:approved})});
    $("results").replaceChildren(element("p",data.note,"muted"));
    $("results").append(element("p",visual ? "AI-supported candidates are based only on sampled images. They can be wrong and are not confirmed detections." : "Rankings only: nearest clips can appear even when the described event is absent. No image matching check was performed.","warning"));
    for(const warning of data.warnings)$("results").append(element("p",warning,"warning"));
    if(data.visual_review){
      $("results").append(element("h3",`${data.visual_review.supported} supported · ${data.visual_review.unclear} unclear · ${data.visual_review.rejected} not supported`));
      $("results").append(element("p",`${data.visual_review.sampled_frames} images checked from ${data.visual_review.checked_candidates} retrieved windows.`,"muted"));
    }
    if(!data.hits.length)$("results").append(element("p",visual ? "No visually supported match in the checked samples. Review unclear candidates below; this does not prove the event is absent from the recording." : "No ranked clips returned from your indexed library.","muted"));
    for(const hit of data.hits)$("results").append(resultCard(hit));
    for(const [key,title] of [["unclear_hits","Unclear or not checked — review manually"],["rejected_hits","Not supported by sampled images"]]){
      if(data[key]?.length){const details=element("details");details.append(element("summary",`${title} (${data[key].length})`));for(const hit of data[key])details.append(resultCard(hit));$("results").append(details);}
    }
  }catch(error){$("results").replaceChildren(element("p",error.message+" No visual result was confirmed.","warning"));}finally{$("visual-consent").checked=false;busy(false);}
};
function resultCard(hit){
  const card=element("article",undefined,"result");
  if(hit.thumbnail_url){const img=element("img");img.src=hit.thumbnail_url;img.alt=`Candidate frame from ${hit.filename}`;card.append(img);}
  const info=element("div"),review=hit.visual_review;
  const labels={supported:"AI-supported candidate · human review required",not_supported:"Not supported in samples",unclear:"Unclear · manual review needed"};
  info.append(element("h3",hit.filename),element("span",review ? labels[review.verdict] : "Ranked candidate · not visually checked","badge"));
  info.append(element("p",`${time(hit.start_sec)}–${time(hit.end_sec)} · Ranking score ${hit.best_score.toFixed(3)} (not a probability)`));
  if(review){
    info.append(element("p",review.reason));
    info.append(element("p","Sampled times: "+(review.sampled_timestamps.map(time).join(", ") || "none"),"muted"));
    for(const t of review.evidence_timestamps){const button=element("button",`Review evidence at ${time(t)}`);button.className="secondary evidence";button.onclick=()=>openVideo(hit.video_id,hit.filename,hit.video_url,t,hit.end_sec);info.append(button);}
  }
  const button=element("button","Review clip →");button.onclick=()=>openVideo(hit.video_id,hit.filename,hit.video_url,hit.start_sec,hit.end_sec);info.append(button);card.append(info);return card;
}
Promise.all([library(),status()]).catch(error=>notice(error.message));

$("plan-button").onclick=async()=>{
  busy(true);$("sync-plan").hidden=true;
  try {
    const plan=await api("/api/search/plan",{method:"POST"});
    planHasChanges=plan.to_index.length>0 || plan.removals>0;
    $("sync-approval").hidden=!planHasChanges;
    $("plan-summary").textContent=`${plan.to_index.length} video(s) to prepare · ${plan.removals} stale search entries to remove · ${plan.up_to_date} already prepared. Estimated paid-tier cost: US$${plan.estimated_cost_usd.toFixed(4)} (estimate, not a spending cap).`;
    $("plan-files").textContent=(plan.to_index.join(", ") || "No new videos to prepare.")+(plan.not_searchable.length ? ` Unsupported for AI search: ${plan.not_searchable.join(", ")}.` : "");
    $("sync-consent").checked=false;$("sync-plan").hidden=false;
    $("sync-plan").scrollIntoView({behavior:"smooth",block:"center"});
  }catch(error){notice(error.message);}finally{busy(false);}
};
$("sync-button").onclick=async()=>{
  if(!planHasChanges || !$("sync-consent").checked){notice("Please review the plan and tick the approval box first.");return;}
  busy(true);notice("Preparing the AI index. This can take several minutes. Keep this page open.");
  try {
    const result=await api("/api/search/sync",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({confirmed:true})});
    $("sync-plan").hidden=true;notice(result.ok ? "AI indexing complete. You can now search your prepared footage." : "Some videos could not be prepared. Review the messages below.");
    $("results").replaceChildren(...result.messages.map(message=>element("p",message,"muted")));
    await Promise.all([library(),status()]);
  }catch(error){notice(error.message);}finally{busy(false);}
};
