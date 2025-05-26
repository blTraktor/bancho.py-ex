# app/bot.py
import disnake
from disnake.ext import commands
from disnake.ext import commands
from disnake import ButtonStyle, Permissions
from disnake.ui import Button, View

from app.discord.config import DISCORD_TICKETS_ALLOWED_USER_IDS, DISCORD_TICKETS_AUTHORIZED_ROLE_IDS

bot = commands.Bot(command_prefix="t!", intents=disnake.Intents.all(), sync_commands_debug=True, help_command=None)

@bot.event
async def on_ready():
    activity = disnake.Game(name="osu!")
    await bot.change_presence(activity=activity)
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print(f"Synced commands: {[cmd.name for cmd in bot.application_commands]}")

class TicketCreateView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="♻️ Appeal", custom_id="create_ticket", style=disnake.ButtonStyle.green)
    async def create_ticket_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        guild = inter.guild
        author = inter.author
        channel_name = f"⌜ticket-{author.name}⌟"

        for channel in guild.text_channels:
            if channel.name == channel_name:
                await inter.response.send_message("✅ You already have an open ticket!", ephemeral=True)
                return

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            author: disnake.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )
        }

        for role_id in DISCORD_TICKETS_AUTHORIZED_ROLE_IDS:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                )

        owner = guild.get_member(guild.owner_id)
        if owner:
            overwrites[owner] = disnake.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

        channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=str(author.id),
        )

        mention_roles = " ".join(f"<@&{role_id}>" for role_id in DISCORD_TICKETS_AUTHORIZED_ROLE_IDS)

        embed = disnake.Embed(
            title="💼 Ticket",
            description=f"|| {mention_roles} || \nTicket created by {author.mention}",
            color=disnake.Color.blue()
        )
        await channel.send(embed=embed, view=TicketCloseView())

class TicketCloseView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="🗑️ Close", custom_id="close_ticket", style=disnake.ButtonStyle.red)
    async def close_ticket_button(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        creator_id = inter.channel.topic
        has_access = (
            inter.author.id == inter.guild.owner_id or
            any(role.id in DISCORD_TICKETS_AUTHORIZED_ROLE_IDS for role in inter.author.roles) or
            (creator_id and str(inter.author.id) == creator_id)
        )

        if not has_access:
            return await inter.response.send_message("🔒 You do not have permission to close this ticket!", ephemeral=True)

        await inter.response.send_message("✏️ Closing the ticket...")
        await inter.channel.delete()

@bot.event
async def on_ready():
    print(f"Bot is ready. Logged in as {bot.user}")
    bot.add_view(TicketCreateView())

@bot.command()
async def send_ticket_message(ctx, channel: disnake.TextChannel = None):
    """Send a ticket message with button (only server owner)."""
    if ctx.author.id != ctx.guild.owner_id and ctx.author.id not in DISCORD_TICKETS_ALLOWED_USER_IDS:
        return await ctx.send("⛔ Only the server owner can use this command.")

    target_channel = channel or ctx.channel
    embed_ru = disnake.Embed(
        title="[RU] Получили рестрикт? Обжалуйте.",
        description=(
            "Если вы считаете что мы не правы в данной ситуации, "
            "и рестрикт был выдан некорректно, нажмите на кнопку "
            "снизу `♻️ Appeal`.\n\n"
            "И заполните анкету которая предоставлена снизу:\n"
            "```"
            "1. Ваш никнейм:\n"
            "2. На какой карте был выдан рестрикт? (Предоставьте ссылку на карту):\n"
            "3. (Если имеется) Аккаунт на osu!bancho:\n"
            "4. Доказательство:\n"
            "```\n"
            "**При предоставлении доказательства, вы должны записать лайфплей, который должен состоять по такой схеме:**\n"
            "___Выйти из osu!___ → ___Начать запись всего экрана___ → ___Открыть диспетчер задач___ и ___показать все процессы___ → "
            "__Зайти в osu!__ → __Сыграть эту же карту либо карту с таким-же количеством PP__.\n\n"
            "❗ Реплей либо запись не с момента входа в osu! — **НЕ ПРИНИМАЮТСЯ!!** ❗\n"
            "❗Если мы оказались не правы, с нас - 🌟 **supporter!**❗"
        ),
        color=disnake.Color.red()
    )

    embed_en = disnake.Embed(
        title="[EN] Got restricted? Submit an appeal.",
        description=(
            "If you believe this was a mistake and the restriction was issued incorrectly, "
            "click the button below `♻️ Appeal`.\n\n"
            "Please fill out the following form:\n"
            "```"
            "1. Your username:\n"
            "2. On which map did the restriction occur? (Provide the map link):\n"
            "3. (If applicable) osu!bancho account:\n"
            "4. Proof:\n"
            "```\n"
            "**When providing proof, you must record a liveplay, following this sequence:**\n"
            "___Exit osu!___ → ___Start recording the full screen___ → ___Open Task Manager___ and ___show all processes___ → "
            "___Launch osu!___ → ___Play the same map or a map with a similar PP value___.\n\n"
            "❗ Replays or recordings not starting from osu! launch — **WILL NOT BE ACCEPTED!!** ❗\n"
            "❗If we're wrong, we're done - 🌟 **supporter!**❗"
        ),
        color=disnake.Color.red()
    )
    embed_en.set_image(url="https://media.discordapp.net/attachments/711952596507557948/1367616422280167565/restricted.png?ex=68168d0c&is=68153b8c&hm=70f1f834152a09f1e6f48acc22b70a3d86609e7157971aa149f86312d09530ee&")

    await target_channel.send(embed=embed_ru)
    await target_channel.send(embed=embed_en, view=TicketCreateView())

    # Удалить командное сообщение после отправки панели
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command()
async def close_ticket(ctx):
    """Close (delete) the ticket channel."""
    if not ctx.channel.name.startswith("⌜ticket-"):
        return await ctx.send("🗑️ This command can only be used in a ticket channel.")

    if ctx.author.id != ctx.guild.owner_id and not any(role.id in DISCORD_TICKETS_AUTHORIZED_ROLE_IDS for role in ctx.author.roles):
        return await ctx.send("🔒 You do not have permission to close this ticket!")

    await ctx.send("✏️ Closing the ticket...")
    await ctx.channel.delete()
