# MeshyMcMeshBot

A community bot for a MeshCore public channel. It posts weather, severe-weather
alerts, local news, and events on a schedule, and it offers a store-and-forward
mailbox, a bulletin board, and handy utility commands.

```
Pi (runs the bot) ──USB──> Wio Tracker L1 (MeshCore USB Companion) ~~LoRa~~> county mesh
```

- **Using the bot from the mesh?** Read the [User Guide](docs/USER_GUIDE.md).
- **What's changed:** see the [CHANGELOG](CHANGELOG.md).

## Hardware & hosting

- **Radio:** flash the L1 with **MeshCore Companion – USB (serial)** firmware
  from the MeshCore web flasher (https://flasher.meshcore.co.uk). Repeater or
  BLE companion firmware won't work. Use the same radio settings and channel as
  your county mesh. While the bot is connected, the L1 is the bot and you can't
  pair your phone to it. It also won't repeat, so if your area needs coverage,
  set up a spare board as a separate repeater.
- **Pi:** a Pi 3B+, 4, or Zero 2 W is plenty (the bot uses about 60 MB of RAM).
  Use Raspberry Pi OS Lite (Bookworm, 64-bit) and keep NTP on, because the bot
  sets the radio's clock from the Pi.
- **Placement matters more than anything else.** Put the L1 and its antenna as
  high as you can (attic, mast, window), on a USB extension or with the Pi up
  there too, powered over PoE. A better antenna beats any software tweak.

## Install on the Pi

```bash
git clone <this repo> meshbot && cd meshbot
sudo ./deploy/install.sh
sudo nano /etc/meshbot/config.yaml     # location, admins, feeds, calendar
sudo systemctl restart meshbot
journalctl -u meshbot -f
```

The udev rule creates `/dev/meshbot`. If your L1 reports a different USB
vendor ID, check `udevadm info -a -n /dev/ttyACM0 | grep idVendor`, or set
`radio.port: /dev/ttyACM0` instead.

**Finding your admin key:** in the MeshCore phone app, open your own node's
details and copy the first 12+ hex characters of the public key into
`bot.admins`.

## Try it without a radio

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml     # set location + db_path: meshbot.sqlite3
./venv/bin/python -m meshymcmeshbot --console
```

Type `Alice: !wx` to post on the channel, `dm Alice: mail Bob hi` to DM the
bot, and `advert Bob` to simulate Bob's node showing up.

## Commands

On the channel, prefix commands with `!`. In a DM, the prefix is optional.

| Command | Where | What |
|---|---|---|
| `help [cmd]` | both | list commands |
| `ping` / `test` | both | hops + SNR of your message |
| `wx`, `alerts` | both | NWS forecast; active alerts |
| `news`, `events` | both | headlines; upcoming events |
| `sun`, `moon`, `time` | both | sunrise/set, moon phase, local time |
| `seen <name>`, `stats` | both | last heard; 24h mesh activity |
| `mail <name> <msg>` | DM | leave mail (names with spaces work; `@a1b2c3` = key prefix) |
| `inbox`, `read` | DM | check / receive mail |
| `post <text>`, `bbs`, `unpost <id>` | DM | bulletin board |
| `say`, `wxnow`, `newsnow`, `addevent`, `delevent`, `status` | DM, admin | admin tools |

**Scheduled posts** (all times are configurable):

| Post | Default times |
|---|---|
| Forecast | 06, 10, 14, 18, 22 |
| Headlines | 08:00 and 17:00 (only new ones) |
| Events digest | 07:30 |
| Mesh stats | 21:00 |

Severe and Extreme NWS alerts post within 5 minutes, even during quiet hours.

## How the mailbox stays private

Mail is addressed to the recipient's **public key**, and it can only be read
over a DM, which MeshCore encrypts and authenticates. Someone who copies
another person's node name can't read their mail. When the recipient's node
advertises, DMs the bot, or posts on the channel, the bot sends it a private
"📬 you have mail" DM. The bot never announces mail on the channel. Messages
expire after 30 days.

## Being a good neighbor on the channel

- Every transmission goes through one queue with a 4 s gap between sends.
- A channel reply is capped at 2 packets; longer output says "DM me for more".
- Each person has a 30 s cooldown on channel commands.
- Only `!`-prefixed messages are treated as commands. The bot ignores normal chatter.

## Layout

```
meshymcmeshbot/
  bot.py          command routing, send queue, scheduler, watchdog
  transport.py    MeshCore serial companion + console simulator
  text.py         byte-safe chunking for ~140-byte payloads
  db.py           SQLite (nodes, mail, bbs, events, dedupe)
  features/       weather, news, events, mailbox, fun (utility + bbs + admin)
```

To add a feature, create `features/foo.py` with `setup(bot)`, register
commands with `@bot.command(...)` and jobs with `bot.schedule(...)`, then add
it to `features/__init__.py`.
