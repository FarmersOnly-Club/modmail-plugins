from datetime import datetime, timezone
import re

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class AiTopicControl(commands.Cog):
    """Track whether AI ticket replies are disabled in the Modmail thread topic."""

    MARKER_RE = re.compile(r"(?:^|\n)AI:\s*(?:enabled|disabled)\b.*", re.IGNORECASE)
    MAX_TOPIC_LEN = 1024

    def __init__(self, bot):
        self.bot = bot

    def _prefixes(self):
        prefix = getattr(self.bot, "prefix", "?")
        if isinstance(prefix, (list, tuple, set)):
            return tuple(str(p) for p in prefix)
        return (str(prefix),)

    def _is_staff_reply_command(self, content: str) -> bool:
        """Return True only for a normal staff reply command, not impersonation."""
        if not content:
            return False

        stripped = content.strip()
        for prefix in self._prefixes():
            if not stripped.startswith(prefix):
                continue

            without_prefix = stripped[len(prefix):].lstrip()
            if not without_prefix:
                continue

            command = without_prefix.split(maxsplit=1)[0].lower()

            # Staff asked for ?r to disable AI. Keep impersonation separate because
            # AI/personality replies use ?impersonate and should not disable AI.
            return command == "r"

        return False

    def _clean_topic(self, topic: str) -> str:
        topic = topic or ""
        topic = self.MARKER_RE.sub("", topic)
        # Clean up blank lines left by marker removal while preserving the rest.
        lines = [line.rstrip() for line in topic.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines).strip()

    def _marker(self, enabled: bool, actor: discord.abc.User) -> str:
        state = "enabled" if enabled else "disabled"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        name = getattr(actor, "display_name", None) or getattr(actor, "name", "staff")
        return f"AI: {state} by {name} ({actor.id}) at {now}"

    async def _set_ai_state(self, channel: discord.TextChannel, enabled: bool, actor: discord.abc.User) -> bool:
        base = self._clean_topic(channel.topic)
        marker = self._marker(enabled, actor)
        new_topic = f"{base}\n{marker}" if base else marker

        if len(new_topic) > self.MAX_TOPIC_LEN:
            # Preserve the AI marker and keep the tail of the existing topic, which
            # usually contains the Modmail user id.
            remaining = self.MAX_TOPIC_LEN - len(marker) - 1
            base = base[-remaining:].lstrip() if remaining > 0 else ""
            new_topic = f"{base}\n{marker}" if base else marker

        if (channel.topic or "") == new_topic:
            return False

        await channel.edit(topic=new_topic, reason=f"AI {'enabled' if enabled else 'disabled'} by {actor}")
        return True

    async def _disable_for_staff_reply(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        if not self._is_staff_reply_command(message.content):
            return

        ctx = await self.bot.get_context(message)
        if not ctx.valid:
            return

        # Only act in Modmail threads and only after the sender passes normal support perms.
        try:
            is_thread = await checks.thread_only().predicate(ctx)
            has_perms = await checks.has_permissions(PermissionLevel.SUPPORTER).predicate(ctx)
        except Exception:
            return

        if not is_thread or not has_perms:
            return

        try:
            changed = await self._set_ai_state(message.channel, enabled=False, actor=message.author)
            if changed:
                await message.add_reaction("🔇")
        except discord.Forbidden:
            try:
                await message.add_reaction("⚠️")
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            try:
                await message.add_reaction("⚠️")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._disable_for_staff_reply(message)

    @commands.group(name="ai", aliases=["aitopic"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    async def ai(self, ctx):
        """Show or change this thread's AI reply state."""
        topic = ctx.channel.topic or ""
        disabled = "ai: disabled" in topic.lower()
        enabled = "ai: enabled" in topic.lower()
        if disabled:
            state = "disabled"
        elif enabled:
            state = "enabled"
        else:
            state = "not set"
        await ctx.send(f"AI reply state for this thread: `{state}`.")

    @ai.command(name="disable")
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    async def ai_disable(self, ctx):
        """Disable AI user-facing replies in this thread."""
        await self._set_ai_state(ctx.channel, enabled=False, actor=ctx.author)
        await ctx.message.add_reaction("🔇")
        await ctx.send("AI replies disabled for this thread.", delete_after=10)

    @ai.command(name="enable")
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    @checks.thread_only()
    async def ai_enable(self, ctx):
        """Enable AI user-facing replies in this thread."""
        await self._set_ai_state(ctx.channel, enabled=True, actor=ctx.author)
        await ctx.message.add_reaction("🔊")
        await ctx.send("AI replies enabled for this thread.", delete_after=10)

    @ai.command(name="clear")
    @checks.has_permissions(PermissionLevel.ADMIN)
    @checks.thread_only()
    async def ai_clear(self, ctx):
        """Remove the AI state marker from this thread topic."""
        clean = self._clean_topic(ctx.channel.topic)
        await ctx.channel.edit(topic=clean or None, reason=f"AI state cleared by {ctx.author}")
        await ctx.message.add_reaction("✅")
        await ctx.send("AI reply state marker cleared for this thread.", delete_after=10)


async def setup(bot):
    await bot.add_cog(AiTopicControl(bot))
