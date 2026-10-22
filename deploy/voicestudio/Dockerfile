# Tested upstream release, pinned to its multi-platform manifest digest.
FROM ghcr.io/debpalash/voicestudio:0.5.6@sha256:588fe119082bb97e722f5e53fe7b0fe1a406885bf72a4c60889d3d03376d7768

# Kitten 0.8 creates a default ONNX pool sized to the physical host (44 CPUs),
# ignoring our one-CPU cgroup quota. Spinning workers then consume that quota
# and affinity fails inside Incus. Patch only Kitten's session construction.
# Fail the build if upstream changes this code, rather than silently losing caps.
RUN python3 - <<'PY'
import importlib.util
from pathlib import Path
path = Path(importlib.util.find_spec('kittentts').origin).parent / 'onnx_model.py'
source = path.read_text()
old = '        self.session = ort.InferenceSession(model_path)'
assert source.count(old) == 1, 'Revalidate Kitten ONNX thread configuration'
new = '''        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.session = ort.InferenceSession(model_path, sess_options=options)'''
path.write_text(source.replace(old, new))
compile(path.read_text(), str(path), 'exec')
PY

# On the shared A2, cached OmniVoice weights must not preload at every restart.
# Keep normal lazy request loading and the upstream idle-unload worker intact.
RUN python3 - <<'PY'
from pathlib import Path
path = Path('/app/backend/services/model_manager.py')
source = path.read_text()
start = source.index('async def preload_model():')
prefix, body = source[:start], source[start:]
old = '    global model, _last_used\n'
assert old in body, 'Revalidate OmniVoice lazy startup patch'
body = body.replace(old, old + '    if os.environ.get("STROOM_TTS_LAZY_START") == "1":\n        return\n', 1)
path.write_text(prefix + body)
compile(path.read_text(), str(path), 'exec')
PY
