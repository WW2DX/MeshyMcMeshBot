# MeshyMcMeshBot User Guide

MeshyMcMeshBot is a community bot on our county's MeshCore public channel. It
posts weather, severe-weather alerts, local news and events, and it can hold
mail for you until your node is back on the mesh.

This guide is for people *using* the bot from the MeshCore app. To run your
own copy, see the [README](../README.md).

> The numbers below (times, limits, counts) are the defaults. Your bot's
> operator can change them.

## Getting started

1. **Join the public channel.** Scheduled posts and channel commands happen there.
2. **Add the bot as a contact.** It advertises about every 12 hours. When it
   shows up in your Contacts list, you can DM it. If you don't see it, ask in
   the channel or wait for the next advert.
3. **Say hi.** Post `!help` in the channel, or DM the bot `help`.

### Channel vs. DM

| | On the channel | In a DM to the bot |
|---|---|---|
| Command format | Starts with `!`, e.g. `!wx` | Just the word, e.g. `wx` (`!` is optional) |
| Who sees the reply | Everyone | Only you |
| Reply length | Short, at most 2 messages | Longer, with more detail |
| Mail & bulletin board | ✗ (the bot tells you to DM it) | ✓ |

Normal conversation on the channel is ignored. The bot only responds to
messages that start with `!`.

## Commands

### Weather

| Command | What you get |
|---|---|
| `wx` | Forecast for the next 2 periods (4 in a DM) |
| `alerts` | Active National Weather Service alerts for our area |

```
!wx
WX Today: Sunny, Hi 68°F, E 7mph | Tonight: Sl chc T-storms, Lo 52°F, E 6mph, 61% precip
```

The forecast uses some abbreviations: *Sl chc* = slight chance,
*Chc* = chance, *Ptly* = partly, *Lt/Hvy* = light/heavy.

### News & events

| Command | What you get |
|---|---|
| `news` | Latest local headlines (2 on the channel, 5 in a DM) |
| `events` (or `cal`) | Community events in the next 7 days |

### Mesh tools

| Command | What you get |
|---|---|
| `ping` (or `test`) | Checks that the bot hears you, with your hop count and signal (SNR) |
| `seen <name>` | When a node was last heard, e.g. `!seen Bob K` |
| `stats` (or `nodes`) | Nodes heard and channel activity over the last 24 hours |

```
!ping
🏓 pong @[Alice] (2 hops, SNR 5.5dB)
```

### Handy extras

| Command | What you get |
|---|---|
| `sun` | Sunrise, sunset, hours of daylight |
| `moon` | Moon phase and days until the next full moon |
| `time` | Local date and time |
| `about` (or `info`) | What the bot is and how long it's been up |
| `help [command]` | All commands, or help for one, e.g. `help mail` |

## Mailbox (DM only)

You can leave a message for anyone the bot has heard on the mesh, even if
they're offline right now.

| Command | What it does |
|---|---|
| `mail <name> <message>` | Leave a message, e.g. `mail Bob K see you at the net` |
| `mail @<key> <message>` | Address by public-key prefix if two nodes share a name, e.g. `mail @a1b2c3 hi` |
| `inbox` | How many messages are waiting, and from whom |
| `read` (or `r`) | Deliver your messages (3 at a time; send `read` again for more) |

**How you find out you have mail:** when your node is heard (it advertises,
DMs the bot, or posts on the channel), the bot sends you a private DM:
`📬 You have 2 msg(s) from Alice. Reply 'read'.` It doesn't nag. You'll get at
most one reminder every 6 hours unless new mail arrives.

**Privacy:** mail is tied to your node's public key, not its name, and it's
only delivered by encrypted DM. Someone who changes their name to match yours
can't read your mail. The bot never announces mail on the channel.

**Limits:** up to 15 messages sent per person per day, 20 waiting per
mailbox, and unread mail expires after 30 days.

## Bulletin board (DM only)

A shared notice board for things like swaps, lost and found, or meetups.

| Command | What it does |
|---|---|
| `post <text>` | Pin a note (up to 300 characters) |
| `bbs` | Read the 5 newest notes |
| `unpost <id>` | Remove your own note, e.g. `unpost 12` |

Notes expire after 14 days, and the board keeps the 50 newest.

## Scheduled posts on the channel

| What | When |
|---|---|
| Weather forecast | 6am, 10am, 2pm, 6pm, 10pm |
| New local headlines | 8am, 5pm (only if there's something new) |
| Upcoming events | 7:30am |
| Mesh stats for the day | 9pm |
| ⚠️ Severe weather alerts | As soon as NWS issues them, any time of day |

Between 10:30pm and 5:30am, scheduled posts are paused. Severe weather alerts
still go out.

## Etiquette & limits

LoRa airtime is shared by everyone, so the bot keeps itself in check:

- Each person can run one channel command every 30 seconds. Extra commands
  are silently ignored.
- Channel replies are at most 2 messages. For the full version, DM the bot.
- The bot waits a few seconds between its own transmissions.

Please use DMs for anything long or personal.

## Troubleshooting

| Problem | Try this |
|---|---|
| The bot didn't answer on the channel | Start the message with `!`. Wait 30 s between commands. Check whether you reach the bot with `!ping`. |
| I can't DM the bot | Add it as a contact first (see Getting started). |
| `mail` says it doesn't know the name | The bot only knows nodes it has heard. Check the spelling, or ask them to send an advert. |
| "Several nodes are named that" | Use the `@key` form the bot suggests. |
| I never got my "you have mail" notice | Your node must be heard by the bot. Send `inbox` by DM to check directly. |

## Admin commands

Admin commands only work by DM from an operator's node.

| Command | What it does |
|---|---|
| `say <text>` | Broadcast an announcement on the channel |
| `wxnow` / `newsnow` | Post the forecast / new headlines right now |
| `addevent YYYY-MM-DD [HH:MM] <title>` | Add a community event |
| `delevent <id>` | Remove an event |
| `unpost <id>` | Remove any bulletin board note |
| `status` | Bot health: uptime, contacts, queue, undelivered mail, radio battery |
