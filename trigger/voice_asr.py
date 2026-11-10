"""Offline WeChat SILK to text helper, run as the unprivileged WeChat user."""
import json
from pathlib import Path
import sys
import tempfile

from .voice_input import MAX_AUDIO_BYTES


def transcribe(data, model):
    import numpy as np
    import pilk
    import sherpa_onnx

    rate = 16000
    if not data.startswith((b'\x02#!SILK_V3', b'#!SILK_V3')):
        raise ValueError('Unsupported original voice codec.')
    with tempfile.TemporaryDirectory(prefix='rsi-voice-') as tmp:
        silk, pcm = Path(tmp) / 'voice.silk', Path(tmp) / 'voice.pcm'
        silk.write_bytes(data)
        duration = pilk.get_duration(str(silk))
        if not 0 < duration <= 65000:
            raise ValueError('Original voice exceeds duration limit.')
        pilk.decode(str(silk), str(pcm), pcm_rate=rate)
        if not 0 < pcm.stat().st_size <= 2 * rate * 65:
            raise ValueError('Decoded voice exceeds sample limit.')
        samples = np.frombuffer(pcm.read_bytes(), dtype='<i2').astype(np.float32) / 32768
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model / 'model.int8.onnx'), tokens=str(model / 'tokens.txt'),
        language='auto', use_itn=True, num_threads=2,
    )
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


if __name__ == '__main__':
    voice = sys.stdin.buffer.read(MAX_AUDIO_BYTES + 1)
    if not 0 < len(voice) <= MAX_AUDIO_BYTES:
        raise SystemExit('Invalid voice size.')
    print(json.dumps({'text': transcribe(voice, Path(sys.argv[1]))}, ensure_ascii=True))
