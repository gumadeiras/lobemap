# Upgrading from 0.1

This page lists what changed for users of lobemap 0.1, and how to do the same things in 0.2.

## The data is a separate download

The data no longer ships in the package. After you upgrade, download it once:

```bash
lobemap fetch
```

[Data](data.md) explains the download and where the data goes.

## Open a brain, not an atlas

`lobemap view <space>` replaces `lobemap --atlas <name>`. A space holds every atlas drawn in one brain volume, so one command opens all of them. `lobemap spaces` lists the spaces:

```bash
lobemap spaces
lobemap view GRABE
```

`lobemap --atlas` now stops with a message that names the replacement. `lobemap` with no command opens FAFB14, not Grabe 2015.

## The view controls

The two 0.1 mirrors and the three 0.1 rotation axes map onto new controls in the **View** dock. [Controls from 0.1](viewer.md#controls-from-01) has the table.

## What was removed

lobemap 0.1, with its atlas selector, DoOR and Potter maps, and BANC and Virtual Fly Brain browsers, remains at tag [`v0.1.4`](https://github.com/gumadeiras/lobemap/tree/v0.1.4).

[CHANGELOG.md](../CHANGELOG.md) lists everything that changed since 0.1.4, including what was removed.
