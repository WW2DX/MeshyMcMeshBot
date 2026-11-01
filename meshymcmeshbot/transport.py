"""Radio transports.

MeshCoreTransport talks to a MeshCore *USB companion* node over serial.
ConsoleTransport fakes a mesh on stdin/stdout so the bot can be tried
without a radio.
"""

import asyncio
import hashlib
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

# MeshCore advert node types.
NODE_CHAT, NODE_REPEATER, NODE_ROOM, NODE_SENSOR = 1, 2, 3, 4
NODE_TYPE_NAMES = {NODE_CHAT: "chat", NODE_REPEATER: "repeater", NODE_ROOM: "room", NODE_SENSOR: "sensor"}

# Ignore a second report of the same advert (RX log + push) within this window.
ADVERT_DEDUPE_SECONDS = 30


@dataclass
class Incoming:
    kind: str  # "chan" or "dm"
    sender_name: str
    text: str
    sender_key: str | None = None  # full pubkey hex when known (DMs only)
    hops: int | None = None  # None = unknown / direct route
    snr: float | None = None
    ts: int = 0


@dataclass
class Advert:
    pubkey: str
    name: str = ""
    node_type: int | None = None
    lat: float | None = None
    lon: float | None = None


Handler = Callable[[Incoming], Awaitable[None]]
AdvertHandler = Callable[[Advert], Awaitable[None]]
# Called with the hex path hashes of repeaters a received packet passed through.
RelayHandler = Callable[[list[str]], Awaitable[None]]


class Transport:
    on_message: Handler
    on_advert: AdvertHandler
    on_relay: RelayHandler
    self_name: str = "bot"
    self_key: str = ""

    async def start(self): ...
    async def close(self): ...
    async def send_channel(self, text: str) -> bool: ...
    async def send_dm(self, pubkey: str, text: str) -> bool: ...
    async def advert(self): ...
    async def status(self) -> str:
        return ""

    def contacts(self) -> dict[str, dict]:
        """pubkey -> {"name", "last_advert", "lat", "lon", "type"}"""
        return {}

    def find_contact_by_prefix(self, prefix: str) -> str | None:
        prefix = prefix.lower()
        for key in self.contacts():
            if key.startswith(prefix):
                return key
        return None

    def is_connected(self) -> bool:
        return True


def candidate_ports() -> list[str]:
    """USB serial devices that could be the companion, most likely first."""
    from serial.tools import list_ports

    ports = ["/dev/meshbot"] if Path("/dev/meshbot").exists() else []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        if p.vid is not None and p.device not in ports:  # skip non-USB (e.g. Pi UART)
            ports.append(p.device)
    return ports


def split_path(path_hex: str, hash_size: int) -> list[str]:
    step = hash_size * 2
    return [path_hex[i:i + step] for i in range(0, len(path_hex) - step + 1, step)]


class MeshCoreTransport(Transport):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mc = None
        self.channel_idx = cfg["bot"]["channel_idx"]
        self._recent_adverts: dict[str, float] = {}

    async def start(self):
        from meshcore import EventType, MeshCore

        port = self.cfg["radio"]["port"]
        candidates = candidate_ports() if port == "auto" else [port]
        for dev in candidates:
            log.info("Trying MeshCore companion on %s", dev)
            self.mc = await MeshCore.create_serial(
                dev,
                self.cfg["radio"]["baudrate"],
                auto_reconnect=True,
                max_reconnect_attempts=10,
            )
            if self.mc is not None:
                break
        if self.mc is None:
            raise RuntimeError(
                f"No MeshCore companion answered on {', '.join(candidates) or 'any USB serial port'}. "
                "Is the L1 plugged in and flashed with *USB Companion* firmware?"
            )

        info = self.mc.self_info or {}
        self.self_name = info.get("name", "bot")
        self.self_key = info.get("public_key", "").lower()
        want = self.cfg["bot"]["name"]
        if want and want != self.self_name:
            await self.mc.commands.set_name(want)
            self.self_name = want
        log.info("Connected as %r (%s)", self.self_name, info.get("public_key", "")[:12])

        # The Pi has NTP; the radio may not. Message timestamps come from the radio.
        await self.mc.commands.set_time(int(time.time()))

        chan = await self.mc.commands.get_channel(self.channel_idx)
        if chan.type != EventType.ERROR:
            log.info("Bot channel %d is %r", self.channel_idx, chan.payload.get("channel_name"))

        self.mc.auto_update_contacts = True
        await self.mc.ensure_contacts()

        self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._on_channel)
        self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_dm)
        self.mc.subscribe(EventType.ADVERTISEMENT, self._on_advert_push)
        self.mc.subscribe(EventType.NEW_CONTACT, self._on_new_contact)
        self.mc.subscribe(EventType.RX_LOG_DATA, self._on_rx_log)
        await self.mc.start_auto_message_fetching()

    @staticmethod
    def _hops(p: dict) -> int | None:
        # path_hash_mode -1 means a direct (non-flood) route; hop count isn't meaningful.
        if p.get("path_hash_mode", 0) < 0:
            return None
        return p.get("path_len")

    async def _on_channel(self, event):
        p = event.payload
        if p.get("channel_idx") != self.channel_idx:
            return
        raw = p.get("text", "")
        # The firmware sends group text as "<sender name>: <message>".
        name, sep, text = raw.partition(": ")
        if not sep:
            name, text = "?", raw
        await self.on_message(Incoming(
            kind="chan", sender_name=name.strip(), text=text.strip(),
            hops=self._hops(p), snr=p.get("SNR"), ts=p.get("sender_timestamp", 0),
        ))

    async def _on_dm(self, event):
        p = event.payload
        if p.get("txt_type", 0) != 0:  # skip CLI/signed-data replies
            return
        prefix = p.get("pubkey_prefix", "")
        contact = self.mc.get_contact_by_key_prefix(prefix)
        if contact is None:
            await self.mc.ensure_contacts(follow=True)
            contact = self.mc.get_contact_by_key_prefix(prefix)
        await self.on_message(Incoming(
            kind="dm",
            sender_name=contact["adv_name"] if contact else prefix,
            sender_key=contact["public_key"] if contact else prefix,
            text=p.get("text", "").strip(),
            hops=self._hops(p), snr=p.get("SNR"), ts=p.get("sender_timestamp", 0),
        ))

    async def _emit_advert(self, adv: Advert):
        if adv.pubkey.lower() == self.self_key:  # our own advert, echoed back by a repeater
            return
        now = time.monotonic()
        if now - self._recent_adverts.get(adv.pubkey, 0) < ADVERT_DEDUPE_SECONDS:
            return
        self._recent_adverts[adv.pubkey] = now
        await self.on_advert(adv)

    async def _on_advert_push(self, event):
        # Let the library pull the updated contact list first so names are fresh.
        await self.mc.ensure_contacts(follow=True)
        key = event.payload["public_key"]
        c = (self.mc.contacts or {}).get(key, {})
        await self._emit_advert(Advert(
            key, c.get("adv_name", ""), c.get("type"), c.get("adv_lat") or None, c.get("adv_lon") or None,
        ))

    async def _on_new_contact(self, event):
        # The radio is in manual-add mode and heard a new node. The bot can only
        # DM contacts (mail notices, welcomes), so add chat nodes.
        c = event.payload
        if c.get("type") == NODE_CHAT:
            await self.mc.commands.add_contact(c)
            await self.mc.ensure_contacts(follow=True)
        await self._emit_advert(Advert(
            c["public_key"], c.get("adv_name", ""), c.get("type"), c.get("adv_lat") or None, c.get("adv_lon") or None,
        ))

    async def _on_rx_log(self, event):
        # Every packet the radio hears, decoded. Two things matter here:
        # adverts (even from nodes not in contacts) and the path of repeaters
        # each flood packet travelled through.
        p = event.payload
        if p.get("adv_key"):
            await self._emit_advert(Advert(
                p["adv_key"], p.get("adv_name", ""), p.get("adv_type"),
                p.get("adv_lat") or None, p.get("adv_lon") or None,
            ))
        if p.get("path") and p.get("route_typename", "").upper().startswith(("FLOOD", "TC_FLOOD")):
            await self.on_relay(split_path(p["path"], p.get("path_hash_size", 1)))

    async def close(self):
        if self.mc is not None:
            await self.mc.disconnect()

    def contacts(self) -> dict[str, dict]:
        out = {}
        for key, c in (self.mc.contacts or {}).items():
            out[key] = {
                "name": c.get("adv_name", ""),
                "last_advert": c.get("last_advert", 0),
                "lat": c.get("adv_lat") or None,
                "lon": c.get("adv_lon") or None,
                "type": c.get("type"),
            }
        return out

    async def send_channel(self, text: str) -> bool:
        res = await self.mc.commands.send_chan_msg(self.channel_idx, text)
        if res.is_error():
            log.warning("Channel send failed: %s", res.payload)
            return False
        return True

    async def send_dm(self, pubkey: str, text: str) -> bool:
        contact = self.mc.get_contact_by_key_prefix(pubkey)
        if contact is None:
            log.warning("Can't DM %s: not in the radio's contact list", pubkey[:12])
            return False
        res = await self.mc.commands.send_msg_with_retry(contact, text)
        if res is None:
            log.info("DM to %s not acknowledged", contact.get("adv_name"))
            return False
        return True

    async def advert(self):
        await self.mc.commands.send_advert(flood=True)

    async def status(self) -> str:
        from meshcore import EventType

        res = await self.mc.commands.get_bat()
        if res.type == EventType.ERROR:
            return ""
        mv = res.payload.get("level", 0)
        return f"batt {mv / 1000:.2f}V"

    def is_connected(self) -> bool:
        return self.mc is not None and self.mc.is_connected


class ConsoleTransport(Transport):
    """Type lines to simulate the mesh:

        Alice: !wx              Alice posts on the channel
        dm Alice: mail Bob hi   Alice DMs the bot
        advert Bob              Bob's node advertises (new names get a welcome)
        repeater Hilltop        a repeater named Hilltop advertises
        relay Hilltop           a packet arrives that Hilltop repeated
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.self_name = cfg["bot"]["name"] or "MeshyMcMeshBot"
        self._contacts: dict[str, dict] = {}

    def _key_for(self, name: str, node_type: int = NODE_CHAT) -> str:
        key = hashlib.sha256(name.lower().encode()).hexdigest()
        if key not in self._contacts:
            self._contacts[key] = {"name": name, "last_advert": int(time.time()),
                                   "lat": None, "lon": None, "type": node_type}
        return key

    async def start(self):
        print(self.__doc__)
        asyncio.get_running_loop().create_task(self._read_stdin())

    async def _read_stdin(self):
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                await asyncio.sleep(3600)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                await self._handle_line(line)
            except Exception:
                log.exception("Error handling console input")

    async def _handle_line(self, line: str):
        word, _, rest = line.partition(" ")
        if word in ("advert", "repeater"):
            node_type = NODE_REPEATER if word == "repeater" else NODE_CHAT
            name = rest.strip()
            key = self._key_for(name, node_type)
            self._contacts[key]["last_advert"] = int(time.time())
            await self.on_advert(Advert(key, name, node_type))
            return
        if word == "relay":
            await self.on_relay([self._key_for(rest.strip(), NODE_REPEATER)[:2]])
            return
        kind = "chan"
        if line.startswith("dm "):
            kind, line = "dm", line[3:]
        name, sep, text = line.partition(": ")
        if not sep:
            print("  (format is 'Name: message' or 'dm Name: message')")
            return
        key = self._key_for(name.strip())
        await self.on_message(Incoming(
            kind=kind, sender_name=name.strip(), text=text.strip(),
            sender_key=key if kind == "dm" else None,
            hops=1, snr=7.5, ts=int(time.time()),
        ))

    def contacts(self) -> dict[str, dict]:
        return self._contacts

    async def send_channel(self, text: str) -> bool:
        print(f"[CHAN] {self.self_name}: {text}", flush=True)
        return True

    async def send_dm(self, pubkey: str, text: str) -> bool:
        name = self._contacts.get(pubkey, {}).get("name", pubkey[:12])
        print(f"[DM -> {name}] {text}", flush=True)
        return True

    async def advert(self):
        print("[ADVERT]", flush=True)
