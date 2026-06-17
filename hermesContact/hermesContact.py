"""Trusted bridge for staff-initiated Modmail contact from bot-authored messages.

KyB3r Modmail intentionally ignores commands authored by bots/webhooks in
Bot.process_commands(). Hermes sends Discord messages as a bot/webhook, so normal
`?contact` will be posted but never executed. This local plugin listens directly
for a restricted bridge command in explicitly allowed channels and creates the
thread via Modmail internals.
"""

import re
from typing import Optional, Tuple

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


USER_RE = re.compile(r"^<@!?(\d+)>$|^(\d+)$")


class HermesContact(commands.Cog):
    """Create Modmail threads from trusted bridge messages and optional initial text."""

    COMMAND = "?hcontact"
    CHANNEL_KEY = "hermes_contact_channel_ids"
    SENDER_KEY = "hermes_contact_sender_user_id"
    DEFAULT_SENDER_USER_ID = 1507060361327673414  # Dr. Phil personality

    def __init__(self, bot):
        self.bot = bot

    def _allowed_channels(self):
        raw = self.bot.config.get(self.CHANNEL_KEY, []) or []
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.replace(",", " ").split() if x.strip()]
        return {str(x) for x in raw}

    def _sender_user_id(self):
        raw = self.bot.config.get(self.SENDER_KEY, self.DEFAULT_SENDER_USER_ID)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return self.DEFAULT_SENDER_USER_ID

    async def _save_allowed_channels(self, channel_ids):
        self.bot.config[self.CHANNEL_KEY] = sorted({str(x) for x in channel_ids})
        await self.bot.config.update()

    async def _save_sender_user_id(self, user_id: int):
        self.bot.config[self.SENDER_KEY] = int(user_id)
        await self.bot.config.update()

    async def _message_as_sender(self, message: discord.Message, content: str):
        """Return a light proxy message whose author is the configured personality.

        Thread.reply()/Thread.send() use message-like objects by attribute. This
        keeps the original bridge message as the timestamp/source while changing
        the displayed/logged author for the initial user-facing message.
        """
        sender = await self.bot.get_or_fetch_user(self._sender_user_id())

        class MessageProxy:
            def __init__(self, original, author, content_override):
                self._original = original
                self.author = author
                self.content = content_override
                self.attachments = []
                self.stickers = []
                self.embeds = []
                self.channel = original.channel
                self.created_at = original.created_at
                self.id = original.id
                self.reference = getattr(original, "reference", None)
                self.message_snapshots = []

            def __getattr__(self, item):
                return getattr(self._original, item)

        return MessageProxy(message, sender, content)

    def _parse(self, content: str) -> Tuple[Optional[int], bool, Optional[str], Optional[str]]:
        """Return (user_id, silent, initial_message, error)."""
        content = content.strip()
        if not content.startswith(self.COMMAND):
            return None, False, None, "not-command"

        rest = content[len(self.COMMAND):].strip()
        if not rest:
            return None, False, None, "Usage: ?hcontact <user-id-or-mention> [silent] -- optional initial message"

        if " -- " in rest:
            head, initial = rest.split(" -- ", 1)
            initial = initial.strip() or None
        elif rest.startswith("-- "):
            return None, False, None, "Missing user before `--`."
        else:
            head, initial = rest, None

        parts = head.split()
        if not parts:
            return None, False, None, "Missing user."

        user_token = parts[0]
        match = USER_RE.match(user_token)
        if not match:
            return None, False, None, "First argument must be a user ID or mention."
        user_id = int(match.group(1) or match.group(2))

        opts = {p.lower() for p in parts[1:]}
        unknown = opts - {"silent", "silently"}
        if unknown:
            return None, False, None, f"Unknown option(s): {', '.join(sorted(unknown))}"

        return user_id, bool(opts & {"silent", "silently"}), initial, None

    async def _create_contact(self, message: discord.Message, user_id: int, silent: bool, initial: Optional[str]):
        allowed = self._allowed_channels()
        if str(message.channel.id) not in allowed:
            return await message.channel.send(
                f"Hermes contact bridge is not enabled in this channel. "
                f"An Owner can run `?hcontactallow {message.channel.id}` first."
            )

        try:
            user = await self.bot.get_or_fetch_user(user_id)
        except discord.NotFound:
            return await message.channel.send(f"Could not find user `{user_id}`.")

        if getattr(user, "bot", False):
            return await message.channel.send(f"{user} is a bot; not creating a Modmail thread.")

        existing = await self.bot.threads.find(recipient=user)
        if existing:
            if getattr(existing, "snoozed", False):
                await existing.restore_from_snooze()
                self.bot.threads.cache[existing.id] = existing
                thread = existing
                await message.channel.send(f"Unsnoozed existing thread for {user.mention}.")
            else:
                where = f" in {existing.channel.mention}" if existing.channel else ""
                return await message.channel.send(f"A thread for {user.mention} already exists{where}.")
        elif await self.bot.is_blocked(user):
            return await message.channel.send(f"{user.mention} is currently blocked from contacting {self.bot.user.name}.")
        else:
            thread = await self.bot.threads.create(
                recipient=user,
                creator=message.author,
                category=None,
                manual_trigger=True,
            )
            if thread.cancelled:
                return
            await thread.wait_until_ready()

            embed = discord.Embed(
                title="Created Thread",
                description=f"Thread started by {message.author.mention} for {user.mention} via Hermes bridge.",
                color=self.bot.main_color,
            )
            await thread.channel.send(embed=embed)

            if not silent and not self.bot.config.get("thread_contact_silently"):
                try:
                    description = self.bot.formatter.format(
                        self.bot.config["thread_creation_contact_response"], creator=message.author
                    )
                    em = discord.Embed(
                        title=self.bot.config["thread_creation_contact_title"],
                        description=description,
                        color=self.bot.main_color,
                    )
                    if self.bot.config["show_timestamp"]:
                        em.timestamp = discord.utils.utcnow()
                    em.set_footer(
                        text=f"{message.author}",
                        icon_url=message.author.display_avatar.url if message.author.display_avatar else None,
                    )
                    await user.send(embed=em)
                except discord.Forbidden:
                    await thread.channel.send("⚠️ Contact DM could not be delivered; user may have DMs closed.")

        if initial:
            try:
                sender_message = await self._message_as_sender(message, initial)
                await thread.reply(sender_message, content=initial)
            except Exception as exc:  # keep bridge failure visible to staff
                await thread.channel.send(f"⚠️ Thread created, but initial message failed: `{type(exc).__name__}: {exc}`")
                raise

        await message.channel.send(f"Created/updated Modmail thread for {user.mention}: {thread.channel.mention}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # This intentionally does NOT ignore bot/webhook authors; that is the point of the bridge.
        if message.guild is None or message.guild != self.bot.modmail_guild:
            return
        if not message.content.strip().startswith(self.COMMAND):
            return
        if message.author == self.bot.user:
            # Avoid loops if this Modmail bot itself ever echoes the bridge command.
            return

        user_id, silent, initial, error = self._parse(message.content)
        if error == "not-command":
            return
        if error:
            return await message.channel.send(error)
        if user_id is None:
            return await message.channel.send("Missing user.")
        await self._create_contact(message, user_id, silent, initial)

    @commands.command(name="hcontactallow", usage="[channel_id]")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def hcontactallow(self, ctx, channel_id: Optional[int] = None):
        """Allow Hermes bridge contact commands in a channel."""
        channel_id = channel_id or ctx.channel.id
        allowed = self._allowed_channels()
        allowed.add(str(channel_id))
        await self._save_allowed_channels(allowed)
        await ctx.send(f"Hermes contact bridge enabled in channel `{channel_id}`.")

    @commands.command(name="hcontactdeny", usage="[channel_id]")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def hcontactdeny(self, ctx, channel_id: Optional[int] = None):
        """Remove a channel from Hermes bridge contact commands."""
        channel_id = channel_id or ctx.channel.id
        allowed = self._allowed_channels()
        allowed.discard(str(channel_id))
        await self._save_allowed_channels(allowed)
        await ctx.send(f"Hermes contact bridge disabled in channel `{channel_id}`.")

    @commands.command(name="hcontactchannels")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def hcontactchannels(self, ctx):
        """List channels allowed to use the Hermes contact bridge."""
        allowed = self._allowed_channels()
        if not allowed:
            return await ctx.send("No Hermes contact bridge channels are configured.")
        mentions = []
        for channel_id in sorted(allowed):
            channel = self.bot.modmail_guild.get_channel(int(channel_id))
            mentions.append(channel.mention if channel else f"`{channel_id}`")
        await ctx.send("Hermes contact bridge channels: " + ", ".join(mentions))

    @commands.command(name="hcontactsender", usage="[user_id]")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def hcontactsender(self, ctx, user_id: Optional[int] = None):
        """Get or set the user/personality displayed for initial hcontact messages."""
        if user_id is None:
            return await ctx.send(f"Hermes contact bridge sender is `{self._sender_user_id()}`.")
        try:
            user = await self.bot.get_or_fetch_user(user_id)
        except discord.NotFound:
            return await ctx.send(f"Could not find user `{user_id}`.")
        await self._save_sender_user_id(user_id)
        await ctx.send(f"Hermes contact bridge sender set to {user} (`{user_id}`).")


async def setup(bot):
    await bot.add_cog(HermesContact(bot))
