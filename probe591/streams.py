"""591's probe: what speech-dispatcher's stream looks like to the app's own
pulse.PulseServer.streams() while a word is said - its app, binary, corked
- and to pactl, beside the tour's watcher (tools/app_tour.VoiceStream)."""

import subprocess
import threading
import time

from polyglotic_desktop.platform.linux import pulse
from polyglotic_desktop.platform.linux.sound import PulseOutput
from polyglotic_desktop.platform.linux.voices import DispatcherVoices
from polyglotic_desktop.platform.recorded_voices import RecordedVoices, Recordings
from polyglotic_desktop.platform.speaking import SpeakerThread
from polyglotic_desktop.ui_next.views.speech import voice_for
from tools.app_tour import VoiceStream

seen: list[tuple[float, object]] = []
stop = threading.Event()


def watch() -> None:
    server = pulse.PulseServer("probe streams")
    t0 = time.perf_counter()
    while not stop.is_set():
        for s in server.streams():
            seen.append((round(time.perf_counter() - t0, 3), s))
        server.run(0.01)
    server.close()


speaker = SpeakerThread(RecordedVoices(DispatcherVoices(), Recordings()), PulseOutput)
speaker.look_for_voices()
while not speaker.listed:
    time.sleep(0.05)
for text, language in (("The", "en"), ("Hello, this is a longer one.", "en")):
    voice = voice_for(speaker.voices(), language)
    assert voice is not None
    seen.clear()
    stop.clear()
    watcher = threading.Thread(target=watch)
    watcher.start()
    tour = VoiceStream()
    done = threading.Event()
    ended: list[bool] = []
    time.sleep(0.3)
    speaker.say(text, voice, 1.0, lambda *_: None, lambda h: (ended.append(h), done.set()))
    time.sleep(0.15)
    print("pactl during:", subprocess.run(["pactl", "list", "short", "sink-inputs"], capture_output=True,
                                          text=True).stdout.strip())
    done.wait(10)
    time.sleep(0.3)
    tour.stop()
    stop.set()
    watcher.join()
    print(f"== {text!r}: ended {ended}; tour watcher first={tour.first} peak={tour.peak:.1f} error={tour.error!r}")
    kinds = {(s.app_name, s.binary, s.corked) for _, s in seen}
    print("   streams seen:", sorted(map(str, kinds)))
    print("   times:", [t for t, s in seen if (s.app_name or "").startswith("speech")][:5], "...")
speaker.close()
