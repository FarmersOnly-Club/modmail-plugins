import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel


class AutoSubscribe(commands.Cog):
    """Automatically subscribes a configured user when a Modmail thread opens."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self.user_id = 1503770714598281276
        self.bump_message = "^"
        bot.loop.create_task(self._set_val())

    async def _update_db(self):
        await self.db.find_one_and_update(
            {"_id": "config"},
            {"$set": {"user_id": self.user_id, "bump_message": self.bump_message}},
            upsert=True,
        )

    async def _set_val(self):
        config = await self.db.find_one({"_id": "config"})

        if config is None:
            await self._update_db()
            return

        self.user_id = int(config.get("user_id", self.user_id))
        self.bump_message = config.get("bump_message", self.bump_message)

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, creator, category, initial_message):
        thread_id = str(thread.id)
        mention = f"<@{self.user_id}>"
        subscriptions = self.bot.config.setdefault("subscriptions", {})
        thread_subscriptions = subscriptions.setdefault(thread_id, [])

        if mention not in thread_subscriptions:
            thread_subscriptions.append(mention)
            await self.bot.config.update()

        if self.bump_message:
            await thread.channel.send(
                f"{mention} {self.bump_message}",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

    @commands.group(name="autosubscribe", invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def autosubscribe(self, ctx):
        """Show AutoSubscribe configuration."""
        embed = discord.Embed(title="AutoSubscribe Configuration", color=self.bot.main_color)
        embed.add_field(name="User", value=f"<@{self.user_id}> (`{self.user_id}`)", inline=False)
        embed.add_field(name="Bump Message", value=f"`{self.bump_message}`" if self.bump_message else "Disabled", inline=False)
        embed.set_footer(text=f"Use {self.bot.prefix}autosubscribe user <user ID> to change the subscribed user.")
        await ctx.send(embed=embed)

    @autosubscribe.command(name="user")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def set_user(self, ctx, user_id: int):
        """Set the user ID to subscribe to new threads."""
        self.user_id = user_id
        await self._update_db()
        await ctx.send(f"AutoSubscribe user set to <@{self.user_id}> (`{self.user_id}`).")

    @autosubscribe.command(name="bump")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def set_bump(self, ctx, *, message: str = ""):
        """Set the follow-up message. Use no message to disable it."""
        self.bump_message = message
        await self._update_db()
        await ctx.send(f"AutoSubscribe bump message set to `{self.bump_message}`." if self.bump_message else "AutoSubscribe bump message disabled.")


async def setup(bot):
    await bot.add_cog(AutoSubscribe(bot))
