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
    source = (Path(__file__).resolve().parents[1]/'tanya/static/dashboard.js').read_text()
    helper = re.search(r'function playbackEnd\(start,end\) \{[^}]+\}',source).group()
    subprocess.run([node,'-e',helper+'''
const assert = require('node:assert/strict');
assert.equal(playbackEnd(12,12),null);
assert.equal(playbackEnd(12,11),null);
assert.equal(playbackEnd(12,15.56),15.56);
for (const value of [null,undefined,NaN,Infinity,'15']) assert.equal(playbackEnd(12,value),null);
'''],check=True,capture_output=True,text=True)
