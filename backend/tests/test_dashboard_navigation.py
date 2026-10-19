"""The evidence-at-window-end regression must not create a zero-length playback range."""
import re
import shutil
import subprocess
from pathlib import Path
import pytest


def test_evidence_timestamp_at_window_end_does_not_stop_playback_immediately():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is optional; browser navigation was manually verified')
    source = (Path(__file__).resolve().parents[1]/'tanya/static/dashboard.js').read_text(encoding="utf-8")
    helper = re.search(r'function playbackEnd\(start,end\) \{[^}]+\}',source).group()
    subprocess.run([node,'-e',helper+'''
const assert = require('node:assert/strict');
assert.equal(playbackEnd(12,12),null);
assert.equal(playbackEnd(12,11),null);
assert.equal(playbackEnd(12,15.56),15.56);
for (const value of [null,undefined,NaN,Infinity,'15']) assert.equal(playbackEnd(12,value),null);
'''],check=True,capture_output=True,text=True)


def test_buffering_overlay_never_covers_a_playback_error():
    """Pressing play after a playback error (no source) must not show "Buffering…" over the message."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is optional; browser behaviour was manually verified')
    source = (Path(__file__).resolve().parents[1]/'tanya/static/dashboard.js').read_text(encoding="utf-8")
    handler = re.search(r'addEventListener\("waiting",(\(\)=>\{.*?\})\);', source).group(1)
    subprocess.run([node, '-e', '''
const assert = require('node:assert/strict');
let shown = null; const overlay = t => { shown = t; };
const els = {player: null, "player-error": {hidden: true}};
const $ = id => els[id];
const waiting = ''' + handler + ''';
function check(src, error, bannerHidden, expected) {
  shown = null;
  els.player = {getAttribute: k => (k === "src" ? src : null), error};
  els["player-error"].hidden = bannerHidden;
  waiting();
  assert.equal(shown, expected);
}
check(null, null, true, null);              // no source loaded: nothing can buffer
check("/media/videos/1", null, false, null); // an error message is showing
check("/media/videos/1", {code: 4}, true, null);
check("/media/videos/1", null, true, "Buffering…");
'''], check=True, capture_output=True, text=True)
