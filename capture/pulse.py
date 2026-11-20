"""libpulse through ctypes: the few calls the capture probe needs.

pa_mainloop driven by hand (prepare, poll, dispatch), so every callback
runs on the probe's own thread.
"""

from __future__ import annotations

import ctypes as C
import time

LIB = C.CDLL("libpulse.so.0")
vp = C.c_void_p

PA_SAMPLE_S16LE = 3
PA_STREAM_DONT_MOVE = 0x0200
PA_STREAM_ADJUST_LATENCY = 0x2000
PA_INVALID_INDEX = 0xFFFFFFFF
CTX_READY, CTX_FAILED, CTX_TERMINATED = 4, 5, 6
ST_NAMES = {0: "UNCONNECTED", 1: "CREATING", 2: "READY", 3: "FAILED", 4: "TERMINATED"}
SUB_SINK_INPUT, SUB_SOURCE_OUTPUT = 0x0004, 0x0008
FACILITY = {0: "sink", 1: "source", 2: "sink-input", 3: "source-output", 4: "module", 5: "client"}
EVENT = {0x00: "new", 0x10: "change", 0x20: "remove"}


class SampleSpec(C.Structure):
    _fields_ = [("format", C.c_int), ("rate", C.c_uint32), ("channels", C.c_uint8)]


class ChannelMap(C.Structure):
    _fields_ = [("channels", C.c_uint8), ("map", C.c_int * 32)]


class CVolume(C.Structure):
    _fields_ = [("channels", C.c_uint8), ("values", C.c_uint32 * 32)]


class BufferAttr(C.Structure):
    _fields_ = [(n, C.c_uint32) for n in ("maxlength", "tlength", "prebuf", "minreq", "fragsize")]


class ServerInfo(C.Structure):
    _fields_ = [
        ("user_name", C.c_char_p), ("host_name", C.c_char_p),
        ("server_version", C.c_char_p), ("server_name", C.c_char_p),
        ("sample_spec", SampleSpec), ("default_sink_name", C.c_char_p),
        ("default_source_name", C.c_char_p), ("cookie", C.c_uint32),
        ("channel_map", ChannelMap),
    ]


class SinkInfo(C.Structure):  # the leading fields only: read through a pointer
    _fields_ = [
        ("name", C.c_char_p), ("index", C.c_uint32), ("description", C.c_char_p),
        ("sample_spec", SampleSpec), ("channel_map", ChannelMap),
        ("owner_module", C.c_uint32), ("volume", CVolume), ("mute", C.c_int),
        ("monitor_source", C.c_uint32), ("monitor_source_name", C.c_char_p),
        ("latency", C.c_uint64), ("driver", C.c_char_p), ("flags", C.c_int),
        ("proplist", vp), ("configured_latency", C.c_uint64),
        ("base_volume", C.c_uint32), ("state", C.c_int),
    ]


class SourceInfo(C.Structure):
    _fields_ = [
        ("name", C.c_char_p), ("index", C.c_uint32), ("description", C.c_char_p),
        ("sample_spec", SampleSpec), ("channel_map", ChannelMap),
        ("owner_module", C.c_uint32), ("volume", CVolume), ("mute", C.c_int),
        ("monitor_of_sink", C.c_uint32), ("monitor_of_sink_name", C.c_char_p),
        ("latency", C.c_uint64), ("driver", C.c_char_p), ("flags", C.c_int),
        ("proplist", vp), ("configured_latency", C.c_uint64),
        ("base_volume", C.c_uint32), ("state", C.c_int),
    ]


class SinkInputInfo(C.Structure):
    _fields_ = [
        ("index", C.c_uint32), ("name", C.c_char_p), ("owner_module", C.c_uint32),
        ("client", C.c_uint32), ("sink", C.c_uint32), ("sample_spec", SampleSpec),
        ("channel_map", ChannelMap), ("volume", CVolume), ("buffer_usec", C.c_uint64),
        ("sink_usec", C.c_uint64), ("resample_method", C.c_char_p),
        ("driver", C.c_char_p), ("mute", C.c_int), ("proplist", vp),
        ("corked", C.c_int), ("has_volume", C.c_int), ("volume_writable", C.c_int),
        ("format", vp),
    ]


class ClientInfo(C.Structure):
    _fields_ = [
        ("index", C.c_uint32), ("name", C.c_char_p), ("owner_module", C.c_uint32),
        ("driver", C.c_char_p), ("proplist", vp),
    ]


SERVER_CB = C.CFUNCTYPE(None, vp, C.POINTER(ServerInfo), vp)
SINK_CB = C.CFUNCTYPE(None, vp, C.POINTER(SinkInfo), C.c_int, vp)
SOURCE_CB = C.CFUNCTYPE(None, vp, C.POINTER(SourceInfo), C.c_int, vp)
SI_CB = C.CFUNCTYPE(None, vp, C.POINTER(SinkInputInfo), C.c_int, vp)
CLIENT_CB = C.CFUNCTYPE(None, vp, C.POINTER(ClientInfo), C.c_int, vp)
SUCCESS_CB = C.CFUNCTYPE(None, vp, C.c_int, vp)
INDEX_CB = C.CFUNCTYPE(None, vp, C.c_uint32, vp)
SUB_CB = C.CFUNCTYPE(None, vp, C.c_int, C.c_uint32, vp)
STREAM_NOTIFY = C.CFUNCTYPE(None, vp, vp)
STREAM_REQ = C.CFUNCTYPE(None, vp, C.c_size_t, vp)


def _f(name, res, *args):
    fn = getattr(LIB, name)
    fn.restype = res
    fn.argtypes = list(args)
    return fn


mainloop_new = _f("pa_mainloop_new", vp)
mainloop_get_api = _f("pa_mainloop_get_api", vp, vp)
mainloop_prepare = _f("pa_mainloop_prepare", C.c_int, vp, C.c_int)
mainloop_poll = _f("pa_mainloop_poll", C.c_int, vp)
mainloop_dispatch = _f("pa_mainloop_dispatch", C.c_int, vp)
get_library_version = _f("pa_get_library_version", C.c_char_p)
proplist_new = _f("pa_proplist_new", vp)
proplist_sets = _f("pa_proplist_sets", C.c_int, vp, C.c_char_p, C.c_char_p)
proplist_gets = _f("pa_proplist_gets", C.c_char_p, vp, C.c_char_p)
proplist_iterate = _f("pa_proplist_iterate", C.c_char_p, vp, C.POINTER(vp))
context_new_with_proplist = _f("pa_context_new_with_proplist", vp, vp, C.c_char_p, vp)
context_connect = _f("pa_context_connect", C.c_int, vp, C.c_char_p, C.c_int, vp)
context_get_state = _f("pa_context_get_state", C.c_int, vp)
context_errno = _f("pa_context_errno", C.c_int, vp)
strerror = _f("pa_strerror", C.c_char_p, C.c_int)
context_get_server_info = _f("pa_context_get_server_info", vp, vp, SERVER_CB, vp)
context_get_sink_info_list = _f("pa_context_get_sink_info_list", vp, vp, SINK_CB, vp)
context_get_sink_info_by_name = _f("pa_context_get_sink_info_by_name", vp, vp, C.c_char_p, SINK_CB, vp)
context_get_source_info_list = _f("pa_context_get_source_info_list", vp, vp, SOURCE_CB, vp)
context_get_sink_input_info_list = _f("pa_context_get_sink_input_info_list", vp, vp, SI_CB, vp)
context_get_client_info_list = _f("pa_context_get_client_info_list", vp, vp, CLIENT_CB, vp)
context_load_module = _f("pa_context_load_module", vp, vp, C.c_char_p, C.c_char_p, INDEX_CB, vp)
context_set_default_sink = _f("pa_context_set_default_sink", vp, vp, C.c_char_p, SUCCESS_CB, vp)
context_set_default_source = _f("pa_context_set_default_source", vp, vp, C.c_char_p, SUCCESS_CB, vp)
context_set_subscribe_callback = _f("pa_context_set_subscribe_callback", None, vp, SUB_CB, vp)
context_subscribe = _f("pa_context_subscribe", vp, vp, C.c_int, SUCCESS_CB, vp)
operation_get_state = _f("pa_operation_get_state", C.c_int, vp)
operation_unref = _f("pa_operation_unref", None, vp)
stream_new = _f("pa_stream_new", vp, vp, C.c_char_p, C.POINTER(SampleSpec), vp)
stream_set_monitor_stream = _f("pa_stream_set_monitor_stream", C.c_int, vp, C.c_uint32)
stream_set_state_callback = _f("pa_stream_set_state_callback", None, vp, STREAM_NOTIFY, vp)
stream_set_read_callback = _f("pa_stream_set_read_callback", None, vp, STREAM_REQ, vp)
stream_set_moved_callback = _f("pa_stream_set_moved_callback", None, vp, STREAM_NOTIFY, vp)
stream_set_suspended_callback = _f("pa_stream_set_suspended_callback", None, vp, STREAM_NOTIFY, vp)
stream_connect_record = _f("pa_stream_connect_record", C.c_int, vp, C.c_char_p, C.POINTER(BufferAttr), C.c_int)
stream_peek = _f("pa_stream_peek", C.c_int, vp, C.POINTER(vp), C.POINTER(C.c_size_t))
stream_drop = _f("pa_stream_drop", C.c_int, vp)
stream_readable_size = _f("pa_stream_readable_size", C.c_size_t, vp)
stream_get_state = _f("pa_stream_get_state", C.c_int, vp)
stream_get_device_name = _f("pa_stream_get_device_name", C.c_char_p, vp)
stream_get_index = _f("pa_stream_get_index", C.c_uint32, vp)
stream_get_buffer_attr = _f("pa_stream_get_buffer_attr", C.POINTER(BufferAttr), vp)
stream_disconnect = _f("pa_stream_disconnect", C.c_int, vp)
stream_unref = _f("pa_stream_unref", None, vp)


def s(b: bytes | None) -> str | None:
    return b.decode("utf-8", "replace") if b is not None else None


def props(pl) -> dict[str, str]:
    out: dict[str, str] = {}
    if not pl:
        return out
    state = vp(None)
    while True:
        key = proplist_iterate(pl, C.byref(state))
        if key is None:
            break
        val = proplist_gets(pl, key)
        out[s(key)] = s(val) if val is not None else "<non-string>"
    return out


class Pulse:
    """One context on a hand-driven pa_mainloop."""

    def __init__(self, name: str) -> None:
        self.ml = mainloop_new()
        self.api = mainloop_get_api(self.ml)
        pl = proplist_new()
        proplist_sets(pl, b"application.name", name.encode())
        self.ctx = context_new_with_proplist(self.api, name.encode(), pl)
        self.keep: list = []  # callbacks kept alive
        self.events: list[tuple[float, str]] = []
        self.t0 = time.monotonic()
        if context_connect(self.ctx, None, 0, None) < 0:
            raise RuntimeError(f"connect: {s(strerror(context_errno(self.ctx)))}")
        self.run_until(lambda: context_get_state(self.ctx) in (CTX_READY, CTX_FAILED, CTX_TERMINATED), 10)
        if context_get_state(self.ctx) != CTX_READY:
            raise RuntimeError(f"context not ready: {s(strerror(context_errno(self.ctx)))}")

    def now(self) -> float:
        return time.monotonic() - self.t0

    def once(self, timeout_us: int = 10_000) -> None:
        mainloop_prepare(self.ml, timeout_us)
        mainloop_poll(self.ml)
        mainloop_dispatch(self.ml)

    def run_until(self, pred, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while not pred():
            if time.monotonic() > end:
                return False
            self.once()
        return True

    def run_for(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.once(min(10_000, max(1, int((end - time.monotonic()) * 1e6))))

    def wait_op(self, op) -> None:
        if not op:
            raise RuntimeError(f"operation: {s(strerror(context_errno(self.ctx)))}")
        self.run_until(lambda: operation_get_state(op) != 0, 10)
        operation_unref(op)

    def _list(self, getter, cbtype, conv, *args):
        out: list = []

        def cb(_c, info, eol, _u):
            if eol or not info:
                return
            out.append(conv(info.contents))

        f = cbtype(cb)
        self.keep.append(f)
        self.wait_op(getter(self.ctx, *args, f, None))
        return out

    def server_info(self) -> dict:
        out: dict = {}

        def cb(_c, info, _u):
            i = info.contents
            out.update(
                server_name=s(i.server_name), server_version=s(i.server_version),
                default_sink_name=s(i.default_sink_name),
                default_source_name=s(i.default_source_name),
                sample_rate=i.sample_spec.rate, channels=i.sample_spec.channels,
            )

        f = SERVER_CB(cb)
        self.keep.append(f)
        self.wait_op(context_get_server_info(self.ctx, f, None))
        return out

    def sinks(self) -> list[dict]:
        return self._list(context_get_sink_info_list, SINK_CB, lambda i: dict(
            index=i.index, name=s(i.name), description=s(i.description),
            monitor_source_name=s(i.monitor_source_name), state=i.state,
            rate=i.sample_spec.rate, channels=i.sample_spec.channels))

    def sink_by_name(self, name: str) -> dict | None:
        found = self._list(context_get_sink_info_by_name, SINK_CB, lambda i: dict(
            index=i.index, name=s(i.name), monitor_source_name=s(i.monitor_source_name)), name.encode())
        return found[0] if found else None

    def sources(self) -> list[dict]:
        return self._list(context_get_source_info_list, SOURCE_CB, lambda i: dict(
            index=i.index, name=s(i.name), description=s(i.description),
            monitor_of_sink=None if i.monitor_of_sink == PA_INVALID_INDEX else i.monitor_of_sink,
            state=i.state, rate=i.sample_spec.rate, channels=i.sample_spec.channels,
            media_class=props(i.proplist).get("media.class")))

    def sink_inputs(self) -> list[dict]:
        return self._list(context_get_sink_input_info_list, SI_CB, lambda i: dict(
            index=i.index, name=s(i.name), client=i.client, sink=i.sink,
            corked=i.corked, driver=s(i.driver), rate=i.sample_spec.rate,
            channels=i.sample_spec.channels, props=props(i.proplist)))

    def clients(self) -> list[dict]:
        return self._list(context_get_client_info_list, CLIENT_CB, lambda i: dict(
            index=i.index, name=s(i.name), driver=s(i.driver), props=props(i.proplist)))

    def load_module(self, name: str, args: str) -> int:
        out = [PA_INVALID_INDEX]

        def cb(_c, idx, _u):
            out[0] = idx

        f = INDEX_CB(cb)
        self.keep.append(f)
        self.wait_op(context_load_module(self.ctx, name.encode(), args.encode(), f, None))
        return out[0]

    def _set_default(self, setter, name: str) -> bool:
        out = [0]

        def cb(_c, ok, _u):
            out[0] = ok

        f = SUCCESS_CB(cb)
        self.keep.append(f)
        self.wait_op(setter(self.ctx, name.encode(), f, None))
        return bool(out[0])

    def set_default_sink(self, name: str) -> bool:
        return self._set_default(context_set_default_sink, name)

    def set_default_source(self, name: str) -> bool:
        return self._set_default(context_set_default_source, name)

    def subscribe(self) -> None:
        def cb(_c, t, idx, _u):
            what = f"{FACILITY.get(t & 0x0F, t & 0x0F)} #{idx} {EVENT.get(t & 0x30, t & 0x30)}"
            self.events.append((round(self.now(), 3), what))

        f = SUB_CB(cb)
        self.keep.append(f)
        context_set_subscribe_callback(self.ctx, f, None)
        self.wait_op(context_subscribe(self.ctx, SUB_SINK_INPUT | SUB_SOURCE_OUTPUT, SUCCESS_CB(), None))


class Recorder:
    """A record stream, 16 kHz mono s16le, fragments of about 20 ms."""

    def __init__(self, pulse: Pulse, label: str, dev: str | None, *,
                 monitor_of: int | None = None, dont_move: bool = False,
                 frag_bytes: int = 640) -> None:
        self.p = pulse
        self.label = label
        self.data = bytearray()
        self.chunks: list[tuple[float, int]] = []
        self.events: list[tuple[float, str]] = []
        self.t_connect = 0.0
        ss = SampleSpec(PA_SAMPLE_S16LE, 16000, 1)
        self.s = stream_new(pulse.ctx, label.encode(), C.byref(ss), None)
        if not self.s:
            raise RuntimeError("pa_stream_new failed")
        if monitor_of is not None:
            rc = stream_set_monitor_stream(self.s, monitor_of)
            self.events.append((0.0, f"set_monitor_stream({monitor_of}) -> {rc}"))
        self._cbs = [STREAM_NOTIFY(self._on_state), STREAM_REQ(self._on_read),
                     STREAM_NOTIFY(self._on_moved), STREAM_NOTIFY(self._on_suspended)]
        stream_set_state_callback(self.s, self._cbs[0], None)
        stream_set_read_callback(self.s, self._cbs[1], None)
        stream_set_moved_callback(self.s, self._cbs[2], None)
        stream_set_suspended_callback(self.s, self._cbs[3], None)
        attr = BufferAttr(0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, frag_bytes)
        flags = PA_STREAM_ADJUST_LATENCY | (PA_STREAM_DONT_MOVE if dont_move else 0)
        self.t_connect = pulse.now()
        rc = stream_connect_record(self.s, dev.encode() if dev else None, C.byref(attr), flags)
        self.events.append((round(self.t_connect, 3), f"connect_record(dev={dev}, flags=0x{flags:x}) -> {rc}"))

    def _ev(self, what: str) -> None:
        self.events.append((round(self.p.now(), 3), what))

    def state(self) -> str:
        return ST_NAMES.get(stream_get_state(self.s), "?")

    def _on_state(self, s_, _u):
        st = self.state()
        extra = ""
        if st == "READY":
            a = stream_get_buffer_attr(self.s)
            if a:
                extra = f" fragsize={a.contents.fragsize} maxlength={a.contents.maxlength}"
            extra += f" device={s(stream_get_device_name(self.s))} index={stream_get_index(self.s)}"
        if st == "FAILED":
            extra = f" error={s(strerror(context_errno(self.p.ctx)))}"
        self._ev(f"state {st}{extra}")

    def _on_moved(self, s_, _u):
        self._ev(f"moved to {s(stream_get_device_name(self.s))}")

    def _on_suspended(self, s_, _u):
        self._ev("suspended changed")

    def _on_read(self, s_, _n, _u):
        while True:
            n = stream_readable_size(self.s)
            if n == 0 or n >= 1 << 40:
                break
            p = vp(None)
            nb = C.c_size_t(0)
            if stream_peek(self.s, C.byref(p), C.byref(nb)) < 0 or nb.value == 0:
                break
            chunk = C.string_at(p.value, nb.value) if p.value else bytes(nb.value)
            self.data += chunk
            self.chunks.append((self.p.now(), nb.value))
            stream_drop(self.s)

    def device(self) -> str | None:
        if self.state() != "READY":
            return None
        return s(stream_get_device_name(self.s))

    def close(self) -> None:
        if self.state() in ("READY", "CREATING"):
            stream_disconnect(self.s)
        stream_unref(self.s)
