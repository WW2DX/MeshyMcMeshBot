# Changelog

All notable changes to MeshyMcMeshBot are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

Add new entries under **[Unreleased]**, grouped as Added / Changed / Fixed /
Removed. When cutting a release, rename that heading to the version and date.

## [Unreleased]

### Added
- `set channel #name` picks the bot's channel by name, and a #hashtag channel
  missing from the radio is added automatically.
- `sudo meshbot --set <name> <value>` changes a setting from the Pi, and
  `sudo meshbot` runs other maintenance options as the service user.
- Initial bot for a MeshCore public channel, connected to a USB Companion
  node (Wio Tracker L1) over serial.
- Weather: NWS forecast posted at 06/10/14/18/22, compacted to fit one packet;
  `wx` and `alerts` commands; Severe/Extreme NWS alerts posted within 5 minutes,
  even during quiet hours, without reposting updates.
- News: headlines from configured RSS/Atom feeds, posted twice daily (new items
  only); `news` command.
- Events: iCal calendar feeds plus admin-added events (`addevent`, `delevent`),
  a morning digest, and the `events` command.
- Mailbox: `mail`, `inbox`, `read` over DM. Mail is addressed by public key, and
  recipients get a private "you have mail" DM when their node is heard.
- Bulletin board: `post`, `bbs`, `unpost`.
- Utility commands: `help`, `ping`, `sun`, `moon`, `time`, `seen`, `stats`,
  `about`; nightly mesh stats digest.
- Admin commands: `say`, `wxnow`, `newsnow`, `status`.
- Airtime protection: single send queue with a 4 s gap, a 2-packet cap on
  channel replies, a 30 s per-person cooldown, quiet hours for scheduled posts.
- Console mode (`--console`) to simulate the mesh without a radio.
- Raspberry Pi deployment: systemd service, udev rule, `install.sh`.
- User guide (`docs/USER_GUIDE.md`) and this changelog.
- Welcome DM the first time the bot hears a new chat node. It waits 3 days
  after a fresh install, and sends at most 6 welcomes an hour.
- Repeater health: `repeaters` command, plus a DM to admins (or a channel post)
  when a watched repeater goes quiet for 24 h and when it comes back. Liveness
  comes from its adverts and from its path hash in relayed traffic.
- Earthquakes: nearby USGS quakes posted within minutes; `quakes` command.
  During quiet hours only M5+ quakes are posted.
- River flooding: NOAA NWPS gauges with official flood stages; alerts on
  observed or forecast flooding and when it recedes; `river` command.
- Air quality: `aqi` command; alert when the US AQI reaches the configured
  level, then a notice when it improves. Uses AirNow with an API key, otherwise
  Open-Meteo.
- The bot now reads the radio's RX log, so it sees adverts from every node,
  including ones not in the radio's contact list, along with relay paths.
- In manual-add mode, the bot adds new chat nodes to the radio's contacts so
  it can DM them.

- Set the bot's area with just a US ZIP code (`location.zip`). Lat/lon,
  timezone, and the area name (county) are looked up from free services and
  cached, and explicit config values override the lookup. `--lookup ZIP`
  previews the result.

- Zero-config setup: install on the Pi, then configure everything over the
  mesh. On first connect the bot posts "👋 Hello world!". The installer prints
  a one-time setup code, and the first node to DM `claim <code>` becomes admin
  (5 wrong guesses per hour, then lockout). `zip <code>` sets the area and
  announces "📍 Now serving <county>!" once.
- Admin configuration over DM: `setup` checklist, `settings`, `set`/`unset`
  (30 settings), and `add`/`del`/`list` for news feeds, calendars (a bare
  Google Calendar ID works), river gauges, watched repeaters, and admins.
  Settings are stored in the database and applied by an automatic restart
  about 15 s after the last change.
- The radio port is auto-detected (`/dev/meshbot` first, then any USB serial
  device).
- `--setup-code` and `--reset-admins` command-line options for recovery.

### Changed
- The bot never posts on the Public channel. Until an admin sets a channel,
  it only talks by DM. It says hello world once on each new channel.
- Renaming the bot sends an advert so contact lists pick up the new name.
- The config file is optional. Mesh-set values override it. The data
  directory defaults to systemd's `STATE_DIRECTORY` (`/var/lib/meshbot`).
- Weather, quake, river, and air features stay off until a location is set,
  instead of failing at startup.
- The bot advertises every `advert_hours` even across restarts, instead of on
  every start.
- The installer no longer creates a config file, and it prints the setup code.
- `location.timezone` no longer defaults to America/Chicago. It's looked up
  from the ZIP or coordinates unless set.
- "Last heard" times use the bot's own clock. Syncing the radio's contact
  list no longer trusts the advert timestamps of nodes with wrong clocks.
- Made docs and examples general-purpose, not ham-radio specific.

### Fixed
- The bot no longer counts its own advert, echoed back by a repeater, as a
  new node in `stats`/`seen` or the welcome DM.
