# Changelog

All notable changes to MeshyMcMeshBot are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/).

Add new entries under **[Unreleased]**, grouped as Added / Changed / Fixed /
Removed. When cutting a release, rename that heading to the version and date.

## [Unreleased]

### Added
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
