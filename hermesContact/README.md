# Hermes Contact Bridge

Local KyB3r Modmail plugin that lets trusted bot/webhook-authored Hermes messages create staff-initiated Modmail threads. KyB3r's core `process_commands()` intentionally ignores bot-authored messages, so normal `?contact` posted by Hermes is visible in Discord but does not execute.

## Install / enable

1. Ensure plugins are enabled (`ENABLE_PLUGINS=true` / `enable_plugins`).
2. Load the local plugin:

```text
?plugin add @local/hermes_contact
```

or add `@local/hermes_contact` to the Modmail `plugins` config and restart/reload.

3. As a Modmail Owner, allow the command channel:

```text
?hcontactallow 1503774146725679274
```

`1503774146725679274` is the current `#test` channel ID used during development; use the real command channel in production.

## Usage

From an allowed channel, Hermes can post:

```text
?hcontact <user-id-or-mention> -- initial message
```

Examples:

```text
?hcontact 170389710034829313 -- Hey there — Kharkiv Farm on EU 19 is showing 6 bee houses. The current limit is 5, so please remove or sell one bee house to come back into compliance.
```

Silent contact without the standard Modmail contact DM:

```text
?hcontact 170389710034829313 silent -- Initial message only.
```

## Initial message sender/personality

The bridge sends the optional initial message as a configured personality user. The default is Dr. Phil:

```text
1507060361327673414
```

Check the current sender:

```text
?hcontactsender
```

Set a different sender/personality:

```text
?hcontactsender <user-id>
```

The selected sender is saved in Modmail config under:

```text
hermes_contact_sender_user_id
```

## Admin commands

```text
?hcontactallow [channel_id]
?hcontactdeny [channel_id]
?hcontactchannels
?hcontactsender [user_id]
```

## Safety

- The listener intentionally does **not** ignore bot/webhook authors.
- To avoid turning every channel into a bot-command bridge, it only executes in explicitly allowed channel IDs stored under `hermes_contact_channel_ids`.
- It ignores messages from the Modmail bot itself to avoid loops.
- It refuses bot recipients and blocked users, and reports existing open threads instead of creating duplicates.
- The initial message sender defaults to Dr. Phil but is configurable.
