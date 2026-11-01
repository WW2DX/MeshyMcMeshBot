# MeshyMcMeshBot

A community bot for a MeshCore public channel. It posts weather, local news,
and events on a schedule, and it warns the channel about severe weather,
flooding, earthquakes, and bad air. It also welcomes new nodes, watches local
repeaters, and offers a store-and-forward mailbox, a bulletin board, and
handy utility commands.

All data sources are free public services, and only AirNow needs a key
(optional): NWS, USGS, NOAA NWPS, Open-Meteo, and any RSS or iCal feeds you
choose. Weather, flood, and earthquake data cover the US only.

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

Plug the L1 into the Pi, then:

```bash
git clone https://github.com/WW2DX/MeshyMcMeshBot.git && cd MeshyMcMeshBot
sudo ./deploy/install.sh
```

That's the only thing you do on the Pi. The installer finds the L1 on any USB
serial port and starts the bot. It ends by printing a one-time **setup code**:

```
>> Setup code: 046-773
>> 1. From your phone, send an advert so the bot learns your node.
>> 2. When the bot appears in your contacts, DM it:  claim 046773
>> 3. Then DM it:  set channel #yourchannel   (the bot never posts on Public)
>> 4. Then DM it:  zip <your ZIP code>
```

To update later, `git pull && sudo ./deploy/install.sh`. Settings are kept.

## Set it up from the mesh

1. **Find it.** The bot advertises itself when it starts. It doesn't post on
   any channel yet, and it never posts on Public.
2. **Claim it.** Send an advert from your phone. MeshCore nodes can only
   read DMs from nodes they know, so this step is required. Once the bot shows
   up in your contacts, DM it `claim 046773`. You're now its admin. The code
   works once, and after 5 wrong guesses in an hour the bot refuses more tries.
   Everything from here on is sent in that same private chat. Commands sent
   on a channel are ignored.
3. **Pick its channel.** DM `set channel #mycounty`. If the radio doesn't
   have that #hashtag channel yet, the bot adds it. After a restart it posts
   `👋 Hello world!` there. (`set botname <name>` renames the node too.)
4. **Set the area.** DM `zip 68102`. The bot looks up the coordinates,
   timezone, and county, restarts itself, and posts `📍 Now serving Douglas
   County!` Weather, flood, quake, and air-quality features switch on at this
   point.
5. **Optional extras,** all by DM:

| Command | Does |
|---|---|
| `setup` | checklist of what's configured and what's next |
| `add feed <name> <rss url>` | local news feed |
| `add cal <ical url or Google Calendar ID>` | community calendar (a bare `...@group.calendar.google.com` ID works, since full URLs barely fit in a DM) |
| `add gauge <id>` | river gauge for flood alerts (IDs from https://water.noaa.gov, e.g. `OMHN1`) |
| `add repeater <name or key prefix>` | repeater to watch for outages |
| `add admin <name or @keyprefix>` | another admin (the node must have advertised) |
| `list <kind>`, `del <kind> <n>` | review or remove items in those lists |
| `settings` | everything you can `set` |
| `set <name> <value>` / `set <name>` / `unset <name>` | change, show, or reset one setting, e.g. `set quiet 23:00-06:00`, `set wxtimes 7,12,17`, `set area Riverbend Mesh`, `set quakes off`, `set botname CountyBot` |
| `restart` | restart the bot |

Changes are saved in the bot's database. Most of them restart the bot about
15 seconds after your last change; adding or removing an admin takes effect
right away. Repeated restarts don't flood the mesh with adverts.

**Recovery (on the Pi):**
- Lost the setup code: `sudo cat /var/lib/meshbot/setup-code.txt`
- Lost admin access: `sudo meshbot --reset-admins && sudo systemctl restart
  meshbot`, then claim again with the new code.
- Change a setting without the mesh: `sudo meshbot --set channel
  '#mycounty' --set botname CountyBot && sudo systemctl restart meshbot`.
  (Quote `#` names, or the shell treats them as a comment.)
- Advertise now: `sudo meshbot --advert && sudo systemctl restart meshbot`.

**Prefer a config file?** It's optional. Put any of the settings from
`config.example.yaml` in `/etc/meshbot/config.yaml`. Values set over the mesh
take precedence over the file. ZIP codes are US-only. Elsewhere, set
`location.lat`, `lon`, `timezone`, and `name` in the file. To preview what a ZIP
resolves to: `python -m meshymcmeshbot --lookup 68102`.

## Try it without a radio

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
STATE_DIRECTORY=./data ./venv/bin/python -m meshymcmeshbot --console
```

The setup code is in the log (and in `data/setup-code.txt`). Type
`dm Me: claim <code>`, then `dm Me: zip 68102`, to walk through the real setup.
Type `Alice: !wx` to post on the channel, `dm Alice: mail Bob hi` to DM the
bot, and `advert Bob` to simulate Bob's node showing up. `repeater Hilltop`
simulates a repeater advert, and `relay Hilltop` simulates a packet relayed
through it.

## Commands

On the channel, prefix commands with `!`. In a DM, the prefix is optional.

| Command | Where | What |
|---|---|---|
| `help [cmd]` | both | list commands |
| `ping` / `test` | both | hops + SNR of your message |
| `wx`, `alerts` | both | NWS forecast; active alerts |
| `news`, `events` | both | headlines; upcoming events |
| `sun`, `moon`, `time` | both | sunrise/set, moon phase, local time |
| `aqi`, `river`, `quakes` | both | air quality; river levels; nearby earthquakes |
| `seen <name>`, `stats`, `repeaters` | both | last heard; 24h mesh activity; repeaters heard |
| `mail <name> <msg>` | DM | leave mail (names with spaces work; `@a1b2c3` = key prefix) |
| `inbox`, `read` | DM | check / receive mail |
| `post <text>`, `bbs`, `unpost <id>` | DM | bulletin board |
| `say`, `wxnow`, `newsnow`, `addevent`, `delevent`, `status` | DM, admin | admin tools |
| `claim`, `zip`, `setup`, `set`, `add`, `del`, `list`, `restart` | DM, admin | configuration (see above) |

**Scheduled posts** (all times are configurable):

| Post | Default times |
|---|---|
| Forecast | 06, 10, 14, 18, 22 |
| Headlines | 08:00 and 17:00 (only new ones) |
| Events digest | 07:30 |
| Mesh stats | 21:00 |

**Automatic alerts:**

| Alert | Source | During quiet hours? |
|---|---|---|
| Severe and Extreme weather | NWS, polled every 5 min | always posts |
| River at or forecast to reach flood stage, and when it recedes | NOAA NWPS gauges added with `add gauge`, polled every 30 min | always posts |
| Nearby earthquakes | USGS, polled every 5 min | posts only M5+ |
| AQI at or above `set aqi` (151), and when it improves | AirNow or Open-Meteo, polled hourly | held until morning |
| A watched repeater is quiet for 24 h, and when it's back | RX log | DMs admins (or posts, after `set rptnotify channel`) |

## Welcomes and repeater watching

Both rely on the companion's **RX log**, which reports every packet the radio
hears, decoded:

- **Welcome DMs.** When a chat node advertises and the bot has never heard
  it, the bot DMs a welcome. On a fresh install it waits `welcome.settle_days`
  (3) first, so it learns who's already around instead of greeting everyone.
  It can only DM nodes in the radio's contact list. If the radio is in
  manual-add mode, the bot adds new chat nodes itself. On a busy mesh, keep an
  eye on the contact table limit (`status` shows the count).
- **Repeater health.** A repeater counts as alive when the bot hears its
  advert, or sees its path hash in a flood packet it relayed. Path hashes are
  short (often 1 byte), so two repeaters can share one. In that case either
  repeater's traffic keeps both looking alive. Alerts go to admins by DM, and
  each admin's node must be in the radio's contacts. If it isn't, the bot logs
  a warning instead.

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
  bot.py          command routing, send queue, scheduler, watchdog, restarts
  transport.py    MeshCore serial companion + console simulator
  text.py         byte-safe chunking for ~140-byte payloads
  db.py           SQLite (nodes, mail, bbs, events, settings, dedupe)
  settings.py     settings admins can change over the mesh
  location.py     ZIP -> coordinates, timezone, county
  features/       admin (claim/setup/settings), weather, news, events, mailbox,
                  fun (utility + bbs + admin tools), welcome, repeaters,
                  quakes, rivers, airquality
```

To add a feature, create `features/foo.py` with `setup(bot)`, register
commands with `@bot.command(...)` and jobs with `bot.schedule(...)`, then add
it to `features/__init__.py`. To make a value changeable over the mesh, add it
to `SETTINGS` (or `LISTS`) in `settings.py`.
