from app.discord import bot
from disnake import Embed, Colour
from typing import Optional
from app.settings import DOMAIN
from app.discord.config import DISCORD_NOTIFY_NEW_MAP_STATUS_CHANNEL_ID, DISCORD_NOTIFY_NEW_SCORE_CHANNEL_ID

mods_emoji = {
    'DT': '<:DT:1367603164538212514>',
    'NC': '<:NC:1367603171496820756>',
    'HT': '<:HT:1367603100562751529>',
    'FL': '<:FL:1367603193864781904>',
    'NF': '<:NF:1367603110356324353>',
    'PF': '<:PF:1367603154560090245>',
    'SD': '<:SD:1367603145345073325>',
    'EZ': '<:EZ:1367603089292398663>',
    'HD': '<:HD:1367603185057005718>',
    'HR': '<:HR:1367603121295069357>',
    'RX': '<:RX:1367603290598146118>',
    'MR': '<:MR:1367602761348157440>',
    'V2': '<:SV2:1367603312559521893>',
    "4K": "<:4K:1367601780468355172>",
    "5K": "<:5K:1367601785707167765>",
    "6K": "<:6K:1367601791704895598>",
    "7K": "<:7K:1367601803864182794>",
    "8K": "<:8K:1367601805759877243>",
    "Coop": "<:Coop:1367602729966375033>",
}

ranking_emoji = {
    "XH": '<:SSH:1367600764901523508>',
    "SH": '<:SH:1367600782979109026>',
    "X": '<:SS:1367600791573106836>',
    'S': '<:S_:1367600797923283164>',
    'A': '<:A_:1367600805292671026>',
    'B': '<:B_:1367600811135340694>',
    'C': '<:C_:1367600818664247516>',
    'D': '<:D_:1367600826415059014>',
}

async def extract_mods_emojis(mod_string: str) -> str:
    if not mod_string:
        return ''

    mods = []
    i = 0
    while i < len(mod_string):
        mod = mod_string[i:i+2]
        if mod in mods_emoji:
            mods.append(mod)
            i += 2
        else:
            i += 1  # skip unknown pair

    # Приоритеты (если есть более специфичный мод, убираем общий)
    if 'NC' in mods and 'DT' in mods:
        mods.remove('DT')
    if 'PF' in mods and 'SD' in mods:
        mods.remove('SD')

    # Удаляем дубликаты, сохраняем порядок
    seen = set()
    unique_mods = [m for m in mods if not (m in seen or seen.add(m))]

    return ''.join(mods_emoji.get(mod, mod) for mod in unique_mods)

async def extract_bmap_status_emoji(status: str=None) -> str:
    if status == 'Ranked':
        return '<:Rank:1368008278042218607>'
    elif status == 'Loved':
        return '<:Loved:1368008285336109192>'
    else:
        return '<:Unrank:1368008291179040768>'

async def notify_new_score(player: str, player_id: int, map_id: int, map_set_id: int, map_name: str, accuracy: str, pp: int, max_combo: int, n300: int, n100: int, n50: int, nmiss: int, is_perfect: bool, bmap_status: str=None, rank: int=None, mods: str=None, grade: str=None) -> None:

    if player:
        channel = bot.get_channel(DISCORD_NOTIFY_NEW_SCORE_CHANNEL_ID)
        if channel:
            if grade != 'F':
                print("Mods: ", mods)
                embed = Embed(
                    title="New score",
                    description=f"[**{map_name}**](https://{DOMAIN}/b/{map_id})",
                    color=Colour.green()
                )
                embed.set_thumbnail(url=f"https://a.{DOMAIN}/{player_id}")
                embed.add_field(name="Player", value=f'{player}', inline=True)
                embed.add_field(name="Accuracy", value=f'{accuracy}', inline=True)
                embed.add_field(name="PP", value=f'{pp}', inline=True)
                embed.add_field(name="Grade", value=ranking_emoji.get(grade, grade), inline=True)
                embed.add_field(name="Max Combo", value=f'{max_combo}x {"<:Perfect1:1368006633157824543><:Perfect2:1368006640196128829>" if is_perfect else ""}', inline=True)
                if rank is None:
                    pass
                else:
                    embed.add_field(name="Rank", value=f"#{rank}", inline=True)
                embed.add_field(name="<:300:1367603996025421935>/<:100:1367604002308493433>/<:50:1367604007996227807>/<:Miss:1368004591102332949>", value=f'{n300}x/{n100}x/{n50}x/{nmiss}x', inline=True)
                embed.add_field(name="Status", value=await extract_bmap_status_emoji(bmap_status), inline=True)
                embed.add_field(name="Mods", value=await extract_mods_emojis(mods), inline=True)
                embed.set_image(url=f"https://assets.ppy.sh/beatmaps/{map_set_id}/covers/card@2x.jpg")
                await channel.send(embed=embed)
            else:
                pass

async def notify_change_map_status(name: str, status: str, accepted_by: str, map_id: int, map_set_id: int, requester: str = None) -> None:
    channel = bot.get_channel(DISCORD_NOTIFY_NEW_MAP_STATUS_CHANNEL_ID)
    print(f"channel: {channel}")
    if channel:
        embed = None
        if status == 'rank':
            status = 'Ranked'
            embed = Embed(
                title="New map status",
                description=f"[**{name}**](https://{DOMAIN}/b/{map_id})",
                color=Colour.blue()
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1166976760424964126.png")
        elif status == 'love':
            status = 'Loved'
            embed = Embed(
                title="New map status",
                description=f"[**{name}**](https://{DOMAIN}/b/{map_id})",
                color=Colour.red()
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1166976753869279272.png")

        else:
            status = "Unranked"
            embed = Embed(
                title="New map status",
                description=f"[**{name}**](https://{DOMAIN}/b/{map_id})",
                color=Colour.dark_gray()
            )
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1166976756230651934.png")
        if requester is None:
            embed.add_field(name="Nominator", value=accepted_by, inline=True)
            embed.add_field(name="Status", value=f'{status}', inline=True)
            embed.set_image(url=f"https://assets.ppy.sh/beatmaps/{map_set_id}/covers/cover.jpg")
            await channel.send(embed=embed)
        else:
            embed.add_field(name="Requester", value=requester, inline=True)
            embed.add_field(name="Nominator", value=accepted_by, inline=True)
            embed.add_field(name="Status", value=f'{status}', inline=True)
            embed.set_image(url=f"https://assets.ppy.sh/beatmaps/{map_set_id}/covers/cover.jpg")
            await channel.send(embed=embed)

