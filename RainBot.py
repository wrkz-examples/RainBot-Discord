import discord
from discord.ext import commands
from discord.ext.commands import Bot, AutoShardedBot, when_mentioned_or, CheckFailure
from discord.utils import get

import os
import time, timeago
from datetime import datetime
from config import config
import click
import sys, traceback
import asyncio
import aiohttp

# numpy
import numpy as np 

import uuid, json
import re, redis

# MySQL
import pymysql, pymysqlpool
import pymysql.cursors

# Emoji
import emoji

# For random string
import random
import string

from typing import List, Dict
intents = discord.Intents.default()
intents.members = True
intents.presences = True

redis_pool = None
redis_conn = None
redis_expired = 600

EMOJI_ERROR = "\u274C"
EMOJI_OK_BOX = "\U0001F197"
EMOJI_MONEYBAG = "\U0001F4B0"
EMOJI_ALARMCLOCK = "\u23F0"
EMOJI_REFRESH = "\U0001F504"
PREFIX_BOT_REDIS = "RainBot"
COIN_NAME = "BTIPZ"

pymysqlpool.logger.setLevel('DEBUG')
myconfig = {
    'host': config.mysql.host,
    'user':config.mysql.user,
    'password':config.mysql.password,
    'database':config.mysql.db,
    'charset':'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit':True
    }

connPool = pymysqlpool.ConnectionPool(size=4, name='connPool', **myconfig)
conn = connPool.get_connection(timeout=5, retry_num=2)

rain_channel = [int(chan_id) for chan_id in config.discord.rain_channel.split(",")]

# Steal from https://github.com/cree-py/RemixBot/blob/master/bot.py#L49
async def get_prefix(bot, message):
    """Gets the prefix for the guild"""
    pre_cmd = config.discord.prefixCmd
    if isinstance(message.channel, discord.DMChannel):
        pre_cmd = config.discord.prefixCmd
        extras = [pre_cmd, 'rain!', '?', '.', '+', '!', '-']
        return when_mentioned_or(*extras)(bot, message)
    extras = [pre_cmd, 'rain!']
    return when_mentioned_or(*extras)(bot, message)


bot = AutoShardedBot(command_prefix=get_prefix, owner_id = config.discord.ownerID, case_insensitive=True, intents=intents)
bot.remove_command('help')


def init():
    global redis_pool
    print("PID %d: initializing redis pool..." % os.getpid())
    redis_pool = redis.ConnectionPool(host='localhost', port=6379, decode_responses=True, db=69)


def openRedis():
    global redis_pool, redis_conn
    if redis_conn is None:
        try:
            redis_conn = redis.Redis(connection_pool=redis_pool)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)


# connPool 
def openConnection():
    global conn, connPool
    try:
        if conn is None:
            conn = connPool.get_connection(timeout=5, retry_num=2)
        conn.ping(reconnect=True)  # reconnecting mysql
    except:
        print("ERROR: Unexpected error: Could not connect to MySql instance.")
        sys.exit()


@bot.event
async def on_shard_ready(shard_id):
    print(f'Shard {shard_id} connected')

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    game = discord.Game(name=config.discord.status)
    await bot.change_presence(status=discord.Status.online, activity=game)


def find_url(string: str): 
    # Thanks to: https://www.geeksforgeeks.org/python-check-url-string/
    # findall() has been used  
    # with valid conditions for urls in string 
    regex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"
    url = re.findall(regex,string)       
    return [x[0] for x in url] 


def count_emoji(msg: str):
    custom_emojis = re.findall(r'<:\w*:\d*>', msg)
    return custom_emojis
    # From now, `custom_emojis` is `list` of `discord.Emoji` that `msg` contains.

@bot.event
async def on_message(message):
    # Record message for rain
    if isinstance(message.channel, discord.DMChannel) == True:
        return
    len_emoji = 0
    len_custom_emoji = 0
    len_url = 0
    if message.author.bot == True or message.webhook_id:
        # user is a bot, ignore
        print('Ignored bot message userid: {}'.format(message.author.id))
        return
    try:
        list_str_emoji = emoji.emoji_lis(message.content)
        if list_str_emoji and len(list_str_emoji) > 0:
            len_emoji = len(list_str_emoji)
            print('messaged by user id {} contains: {} emoji(s).'.format(message.author.id, len_emoji))
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    try:
        custom_emoji = count_emoji(message.content)
        if custom_emoji and len(custom_emoji) > 0:
            len_custom_emoji = len(custom_emoji)
            print('messaged by user id {} contains: {} customed emoji(s).'.format(message.author.id, len_custom_emoji))
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    try:
        list_url = find_url(message.content)
        if list_url and len(list_url) > 0:
            len_url = len(list_url)
            print('messaged by user id {} contains: {} urls.'.format(message.author.id, len_url))
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    total_message_len = len(message.content)
    if message.channel.id in rain_channel:
        await add_msg_redis(json.dumps([str(message.author.id), str(message.id), message.content, 
                                        str(message.guild.id), str(message.channel.id), int(time.time()), len_emoji, 
                                        len_custom_emoji, len_url, total_message_len]), False)
    # Do not remove this, otherwise, command not working.
    ctx = await bot.get_context(message)
    await bot.invoke(ctx)


@bot.event
async def on_message_delete(message):
    # If a user delete a message
    delete = sql_add_delete_msg(str(message.id), message.content, str(message.author.id), str(message.channel.id))
    return


async def is_owner(ctx):
    return ctx.author.id in config.discord.ownerID.split(",")


# function to return if input string is ascii
def is_ascii(s):
    return all(ord(c) < 128 for c in s)


@bot.command(pass_context=True)
async def say(ctx, *, msg):
    if isinstance(ctx.message.channel, discord.DMChannel) == True:
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} This can not be in DM.')
        return
    if str(ctx.message.author.id) not in config.discord.ownerID.split(","):
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} You have no permission.')
        return
    else:
        msg = await ctx.send(msg)
        return


@bot.command(pass_context=True)
async def setting(ctx):
    if isinstance(ctx.message.channel, discord.DMChannel) == True:
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} This can not be in DM.')
        return
    if str(ctx.message.author.id) not in config.discord.ownerID.split(","):
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} You have no permission.')
        return
    if ctx.message.channel.id not in rain_channel:
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} Channel <#{ctx.message.channel.id}> is not active for rain.')
        return
    else:
        rain_duration = config.rain.duration_each
        rain_amount = config.rain.default_rain_amount_total
        try:
            openRedis()
            if redis_conn and redis_conn.exists(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Amount'):
                rain_amount = float(redis_conn.get(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Amount').decode())
            if redis_conn and redis_conn.exists(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Duration'):
                rain_duration = int(redis_conn.get(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Duration').decode())
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        rain_amount = '{:,.4f}'.format(rain_amount)
        msg = await ctx.send(f'{ctx.author.mention} current setting:\n'
                             '```'
                             f'Duration of each rain: {seconds_str(rain_duration)}\n'
                             f'Total amount to split: {rain_amount}{config.rain.coin_name}\n'
                             f'Re-act: {EMOJI_MONEYBAG}: adjust total amount, {EMOJI_ALARMCLOCK}: duration, {EMOJI_REFRESH}: restart bot (after you made change)\n'
                             f'Timeout: {config.rain.setting_timeout}s'
                             '```')
        await msg.add_reaction(EMOJI_MONEYBAG)
        await msg.add_reaction(EMOJI_ALARMCLOCK)
        await msg.add_reaction(EMOJI_REFRESH)

        def check(reaction, user):
            return user == ctx.message.author and reaction.message.author == bot.user and reaction.message.id == msg.id \
            and str(reaction.emoji) in (EMOJI_REFRESH, EMOJI_ALARMCLOCK, EMOJI_MONEYBAG)
        try:
            reaction, user = await bot.wait_for('reaction_add', timeout=config.rain.setting_timeout, check=check)
        except asyncio.TimeoutError:
            await ctx.send(f'{ctx.author.mention} too long. You can try again later.')
            return
        else:
            if str(reaction.emoji) == EMOJI_MONEYBAG:
                await ctx.send(f'{ctx.author.mention} Please input amount (timeout: {config.rain.setting_timeout}s):')
                amount = None
                while amount is None:
                    waiting_amount = None
                    try:
                        waiting_amount = await bot.wait_for('message', timeout=config.rain.setting_timeout, check=lambda msg: msg.author == ctx.author)
                    except asyncio.TimeoutError:
                        await ctx.send(f'{ctx.author.mention} too long. You can try again later.')
                        return
                    if waiting_amount:
                        amount = waiting_amount.content.strip()
                        amount = amount.replace(",", "")
                        try:
                            amount = float(amount)
                            if amount < 1 or amount > 100:
                                amount = None
                                await waiting_amount.add_reaction(EMOJI_ERROR)
                                await ctx.send(f'{ctx.author.mention} Amount can not be smaller than **1** or bigger than **100**.')
                            else:
                                await waiting_amount.add_reaction(EMOJI_OK_BOX)
                                # OK, set it to redis
                                try:
                                    openRedis()
                                    if redis_conn:
                                        redis_conn.set(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Amount', str(amount))
                                        await ctx.send(f'{ctx.author.mention} OK, we set a new amount to: **{amount}** for <#{ctx.message.channel.id}>')
                                except Exception as e:
                                    traceback.print_exc(file=sys.stdout)
                        except ValueError:
                            amount = None
                            await waiting_amount.add_reaction(EMOJI_ERROR)
                            await ctx.send(f'{ctx.author.mention} Invalid amount.')
            elif str(reaction.emoji) == EMOJI_ALARMCLOCK:
                await ctx.send(f'{ctx.author.mention} Please input duration in second (timeout: {config.rain.setting_timeout}s):')
                duration = None
                while duration is None:
                    waiting_duration = None
                    try:
                        waiting_duration = await bot.wait_for('message', timeout=config.rain.setting_timeout, check=lambda msg: msg.author == ctx.author)
                    except asyncio.TimeoutError:
                        await ctx.send(f'{ctx.author.mention} too long. You can try again later.')
                        return
                    if waiting_duration:
                        duration = waiting_duration.content.strip()
                        duration = duration.replace(",", "")
                        try:
                            duration = int(duration)
                            if duration < config.rain.duration_each:
                                duration = None
                                await waiting_duration.add_reaction(EMOJI_ERROR)
                                await ctx.send(f'{ctx.author.mention} Duration can not be smaller than **{config.rain.duration_each}s**.')
                            else:
                                await waiting_duration.add_reaction(EMOJI_OK_BOX)
                                # OK, set it to redis
                                try:
                                    openRedis()
                                    if redis_conn:
                                        redis_conn.set(f'{PREFIX_BOT_REDIS}:{ctx.message.channel.id}:Rain_Duration', str(int(duration)))
                                        await ctx.send(f'{ctx.author.mention} OK, we set a new duration to: **{seconds_str(duration)}** for <#{ctx.message.channel.id}>')
                                except Exception as e:
                                    traceback.print_exc(file=sys.stdout)
                        except ValueError:
                            duration = None
                            await waiting_duration.add_reaction(EMOJI_ERROR)
                            await ctx.send(f'{ctx.author.mention} Invalid duration.')
            elif str(reaction.emoji) == EMOJI_REFRESH:
                await ctx.message.add_reaction(EMOJI_REFRESH)
                await ctx.send(f'{ctx.author.mention} OK, I am going to restart in 5s.')
                await asyncio.sleep(5)
                await bot.logout()


async def add_msg_redis(msg: str, delete_temp: bool = False):
    try:
        openRedis()
        key = f"{PREFIX_BOT_REDIS}:MSG"
        if redis_conn:
            if delete_temp:
                redis_conn.delete(key)
            else:
                redis_conn.lpush(key, msg)
    except Exception as e:
        traceback.print_exc(file=sys.stdout)


async def store_message_list():
    while True:
        interval_action_list = 10
        try:
            openRedis()
            key = f"{PREFIX_BOT_REDIS}:MSG"
            if redis_conn and redis_conn.llen(key) > 0 :
                temp_msg_list = []
                for each in redis_conn.lrange(key, 0, -1):
                    temp_msg_list.append(tuple(json.loads(each)))
                num_add = sql_add_msg(temp_msg_list)
                if num_add > 0:
                    redis_conn.delete(key)
                else:
                    print(f"Failed delete {key}")
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
        await asyncio.sleep(interval_action_list)


def sql_add_msg(list_msg):
    if len(list_msg) == 0:
        return 0
    global conn
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ INSERT INTO `rain_msg` (`userid`, `message_id`, `message_content`, `guild_id`, `channel_id`, 
                      `message_date`, `len_emoji`, `len_custom_emoji`, `numb_url`, `numb_chars`)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) """
            cur.executemany(sql, list_msg)
            conn.commit()
            return cur.rowcount
    except Exception as e:
        traceback.print_exc(file=sys.stdout)


def sql_add_delete_msg(message_id: str, message_content: str, userid: str, channel_id: str):
    global conn
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ INSERT INTO `rain_msg_deleted` (`message_id`, `message_content`, `userid`, `deleted_date`, `channel_id`)
                      VALUES (%s, %s, %s, %s, %s) """
            cur.execute(sql, (message_id, message_content, userid, int(time.time()), channel_id))
            conn.commit()
            return True
    except Exception as e:
        traceback.print_exc(file=sys.stdout)


def select_msg_last_duration_chan_id(channel_id: str, lastDuration: int):
    global conn
    lapDuration = int(time.time()) - lastDuration
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ SELECT * FROM rain_msg WHERE `channel_id` = %s AND `message_date`>%s """
            cur.execute(sql, (channel_id, lapDuration))
            result = cur.fetchall()
            return result
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    return False


def select_delete_msg_last_duration(channel_id: str, lastDuration: int):
    global conn
    lapDuration = int(time.time()) - lastDuration
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ SELECT * FROM rain_msg_deleted WHERE `channel_id` = %s AND `deleted_date`>%s ORDER BY `deleted_date` DESC """
            cur.execute(sql, (channel_id, lapDuration))
            result = cur.fetchall()
            return result
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    return False


def select_get_last_tip_duration(channel_id: str, lastDuration: int):
    global conn
    lapDuration = int(time.time()) - lastDuration
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ SELECT * FROM rained WHERE `channel_id` = %s AND `rained_date`>%s ORDER BY `rained_date` DESC LIMIT 1 """
            cur.execute(sql, (channel_id, lapDuration))
            result = cur.fetchone()
            return result
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
    return False


def add_rain_to_db(guild_id: str, channel_id: str, rained_tip_text: str, rained_amount: float, rained_coin: str):
    global conn
    try:
        openConnection()
        with conn.cursor() as cur:
            sql = """ INSERT INTO `rained` (`guild_id`, `channel_id`, `rained_tip_text`, `rained_date`, `rained_amount`, `rained_coin`)
                      VALUES (%s, %s, %s, %s, %s, %s) """
            cur.execute(sql, (guild_id, channel_id, rained_tip_text, int(time.time()), rained_amount, rained_coin))
            conn.commit()
            return True
    except Exception as e:
        traceback.print_exc(file=sys.stdout)


async def get_rain():
    rain_amount = config.rain.default_rain_amount_total
    rain_duration = config.rain.duration_each
    await bot.wait_until_ready()
    while not bot.is_closed():
        # Sleep 60s before doing anything
        await asyncio.sleep(config.rain.interval_check)
        for each_chan in rain_channel:
            channel = bot.get_channel(id=each_chan)
            guild = channel.guild
            try:
                openRedis()
                if redis_conn and redis_conn.exists(f'{PREFIX_BOT_REDIS}:{each_chan}:Rain_Amount'):
                    rain_amount = float(redis_conn.get(f'{PREFIX_BOT_REDIS}:{each_chan}:Rain_Amount').decode())
                if redis_conn and redis_conn.exists(f'{PREFIX_BOT_REDIS}:{each_chan}:Rain_Duration'):
                    rain_duration = int(redis_conn.get(f'{PREFIX_BOT_REDIS}:{each_chan}:Rain_Duration').decode())
            except Exception as e:
                traceback.print_exc(file=sys.stdout)
            get_chan_lasttip = select_get_last_tip_duration(each_chan, rain_duration)
            if get_chan_lasttip and len(get_chan_lasttip) > 0:
                print('channel {} already tip recently. Skipped.'.format(each_chan))
            else:
                rain_collection = select_msg_last_duration_chan_id(str(each_chan), rain_duration)
                delete_collection = select_delete_msg_last_duration(str(each_chan), rain_duration)
                total_char = sum(item['numb_chars'] for item in rain_collection)
                total_len_emoji = sum(item['len_emoji'] for item in rain_collection)
                total_len_custom_emoji = sum(item['len_custom_emoji'] for item in rain_collection)
                total_numb_url = sum(item['numb_url'] for item in rain_collection)
                member_ids = [m['userid'] for m in rain_collection]
                member_ids = np.unique(np.array(member_ids))
                member_delete_ids = [m['userid'] for m in delete_collection]
                member_ids = [item for item in member_ids if item not in member_delete_ids]
                if len(member_ids) > 0:
                    each_get = '{:,.2f}'.format(rain_amount / len(member_ids))
                    user_list = []
                    for each_member in member_ids:
                        try:
                            member = bot.get_user(id=int(each_member))
                            if member and member in guild.members:
                                user_list.append('<@{}>'.format(member.id))
                        except Exception as e:
                            traceback.print_exc(file=sys.stdout)
                    if len(user_list) > 0:
                        user_list_text = " ".join(user_list)
                        TipChan = bot.get_channel(id=each_chan)
                        if TipChan:
                            rained_text = f'{config.rain.command_tip} {each_get} {config.rain.coin_name} {user_list_text}\n'
                            rained_text += f'```There are {len(rain_collection)} message(s) in the last {seconds_str(rain_duration)} by {len(member_ids)} user(s).\n'
                            rained_text += f'Chars: {total_char}, url: {total_numb_url}, emoji: {total_len_emoji+total_len_custom_emoji}```'
                            msg = await TipChan.send(f'{rained_text}')
                            add_rain_to_db(str(msg.guild.id), str(msg.channel.id), rained_text, rain_amount, config.rain.coin_name)
        await asyncio.sleep(config.rain.interval_check)


@bot.command(pass_context=True, name='randmsg',  aliases=['random_message'])
async def randmsg(ctx, cmd: str, *, message: str=None):
    global redis_pool, redis_conn
    if str(ctx.message.author.id) not in config.discord.ownerID.split(","):
        await ctx.message.add_reaction(EMOJI_ERROR)
        await ctx.send(f'{ctx.author.mention} You have no permission.')
        return
    if redis_conn is None:
        try:
            redis_conn = redis.Redis(connection_pool=redis_pool)
        except Exception as e:
            traceback.print_exc(file=sys.stdout)

    cmd = cmd.upper()
    if cmd not in ["ADD", "DEL", "LIST", "LS"]:
        await ctx.send(f'{ctx.author.mention} Invalid cmd given. Available cmd **ADD | DEL | LIST**.')
        return

    if cmd == "ADD" and len(message) < 10:
        await ctx.send(f'{ctx.author.mention} Message is too short.')
        return

    if cmd == "ADD":
        rndStr = randomString(8).upper()
        key = f"{PREFIX_BOT_REDIS}:{COIN_NAME}:" + rndStr
        redis_conn.set(key, message)
        await ctx.send(f'{ctx.author.mention} Sucessfully added **{rndStr}** for message: {message}.')
        return
    elif cmd == "DEL":
        key = f"{PREFIX_BOT_REDIS}:{COIN_NAME}:" + message.upper()
        if redis_conn and redis_conn.exists(key):
            redis_conn.delete(key)
            await ctx.send(f'{ctx.author.mention} **{message.upper()}** message is deleted.')
            return
        else:
            await ctx.send(f'{ctx.author.mention} **{message.upper()}** doesn\'t exist.')
            return
    elif cmd == "LS" or cmd == "LIST":
        keys = redis_conn.keys(f"{PREFIX_BOT_REDIS}:{COIN_NAME}:*")
        if len(keys) > 10:
            response_txt = ''
            i = 0
            for each in keys:
                response_txt += "**{}**: {}\n".format(each.decode('utf-8').replace(f'{PREFIX_BOT_REDIS}:{COIN_NAME}:', ''), redis_conn.get(each.decode('utf-8')).decode('utf-8'))
                i += 1
                j = 1
                if i % 10 == 0:
                    await ctx.send(f'{ctx.author.mention} List messages **[{j}]**:\n{response_txt}')
                    response_txt = ''
                    j += 1
            if len(response_txt) > 0:
                await ctx.send(f'{ctx.author.mention} List messages **[Last]**:\n{response_txt}')
            return
        elif len(keys) > 0:
            response_txt = ''
            for each in keys:
                response_txt += "**{}**: {}\n".format(each.decode('utf-8').replace(f'{PREFIX_BOT_REDIS}:{COIN_NAME}:', ''), redis_conn.get(each.decode('utf-8')).decode('utf-8'))
            await ctx.send(f'{ctx.author.mention} List messages:\n{response_txt}')
            return
        else:
            await ctx.send(f'{ctx.author.mention} There is no message added yet.')
            return


async def posting_tips():
    global redis_pool, redis_conn
    await bot.wait_until_ready()
    NewsChan = bot.get_channel(id=config.randomMsg.channelNews)
    while not bot.is_closed():
        if redis_conn is None:
            try:
                redis_conn = redis.Redis(connection_pool=redis_pool)
            except Exception as e:
                traceback.print_exc(file=sys.stdout)
        while NewsChan is None:
            NewsChan = bot.get_channel(id=config.randomMsg.channelNews)
            await asyncio.sleep(1000)
        keys = redis_conn.keys(f"{PREFIX_BOT_REDIS}:{COIN_NAME}:*")
        if len(keys) > 0:
            response_txt = ''
            key = random.choice(keys)
            response_txt += "{}".format(redis_conn.get(key.decode('utf-8')).decode('utf-8'))
            await NewsChan.send(response_txt)
        print("Waiting for another {}".format(config.randomMsg.duration_each))
        await asyncio.sleep(config.randomMsg.duration_each)
        print("Completed waiting...")    


def seconds_str(time: float):
    # day = time // (24 * 3600)
    # time = time % (24 * 3600)
    hour = time // 3600
    time %= 3600
    minutes = time // 60
    time %= 60
    seconds = time
    return "{:02d}:{:02d}:{:02d}".format(hour, minutes, seconds)


def randomString(stringLength=8):
    letters = string.ascii_lowercase
    return ''.join(random.choice(letters) for i in range(stringLength))


@click.command()
def main():
    bot.loop.create_task(store_message_list())
    bot.loop.create_task(get_rain())
    bot.loop.create_task(posting_tips())
    bot.run(config.discord.token, reconnect=True)


if __name__ == '__main__':
    main()