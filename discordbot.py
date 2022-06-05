# -*- coding: utf-8 -*-
import asyncio
import random
import typing
from asyncio import sleep
from os import getenv

import discord
import requests
import tweepy
import yt_dlp
from discord.ext import commands
from googleapiclient.discovery import build
from niconico import NicoNico

# DiscordBot
# 環境変数を設定する
DISCORD_BOT_TOKEN = getenv("DISCORD_BOT_TOKEN")
# Botの接頭辞を ! にする
bot = commands.Bot(command_prefix="!")

# yt_dlp
YTDL_FORMAT_OPTIONS = {
    "format": "bestaudio/best*[acodec=aac]",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0"  # bind to ipv4 since ipv6 addresses cause issues sometimes
}

FFMPEG_OPTIONS = {
    "options": "-vn"
}

# https://qiita.com/sizumita/items/cafd00fe3e114d834ce3
# Suppress noise about console usage from errors
yt_dlp.utils.bug_reports_message = lambda: ""

ytdl = yt_dlp.YoutubeDL(YTDL_FORMAT_OPTIONS)

client = discord.Client()


# NicoNicoDLSourceのためにちゃんと閉じる必要があるので、Sourceのあと voice_client.play の最後にこれを実行してやってください
def after_play_niconico(source, e, guild, f):
    if type(source) == NicoNicoDLSource:
        source.close_connection()

    if e:
        print(f"has error: {e}")
    else:
        f(guild)


# Cog とは: コマンドとかの機能をひとまとめにできる
class Music(commands.Cog):
    def __init__(self, bot_arg):
        self.bot = bot_arg
        self.player: typing.Union[YTDLSource, NicoNicoDLSource, None] = None
        self.queue: typing.List[typing.Union[YTDLSource, NicoNicoDLSource]] = []

    def after_play(self, guild):
        if len(self.queue) <= 0:
            return

        self.player = self.queue.pop(0)
        guild.voice_client.play(self.player, after=lambda e: after_play_niconico(self.player, e, guild, self.after_play))

    @commands.command()
    async def join(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # ボイスチャンネルに接続する
        await ctx.author.voice.channel.connect()
        await ctx.channel.send("接続したぴょ。はよ指示だせぴょ。")

    @commands.command()
    async def leave(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続してねぇぴょ。")
            return

        # 切断する
        await ctx.guild.voice_client.disconnect()
        await ctx.channel.send("切断したぴょ。")

    @commands.command(aliases=["np"])
    async def nowplaying(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続してねぇぴょ。")
            return

        # 再生中ではない場合は実行しない
        if not ctx.guild.voice_client.is_playing():
            await ctx.channel.send("再生してねぇぴょよ。")
            return

        embed = discord.Embed(colour=0xff00ff, title=self.player.title, url=self.player.original_url)
        embed.set_author(name="現在再生中")

        # YouTube再生時にサムネイルも一緒に表示できるであろう構文
        # if "youtube.com" in self.player.original_url or "youtu.be" in self.player.original_url:
        #     np_youtube_video = youtube.videos().list(part="snippet", id=id).execute()
        #     np_thumbnail = np_youtube_video["items"][0]["snippet"]["thumbnails"]
        #     np_highres_thumbnail = list(np_thumbnail.keys())[-1]
        # 
        #     embed.set_image(url=np_thumbnail[np_highres_thumbnail]["url"])

        await ctx.channel.send(embed=embed)

    @commands.command(aliases=["p"])
    async def play(self, ctx, *, url):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # ボイスチャンネルにBotが未接続の場合はボイスチャンネルに接続する
        if ctx.guild.voice_client is None:
            await ctx.author.voice.channel.connect()

        embed = discord.Embed(colour=0xff00ff)
        embed.set_author(name="処理中です...")
        play_msg: discord.Message = await ctx.channel.send(embed=embed)

        # niconico.py は短縮URLも取り扱えるっぽいので信じてみる
        # https://github.com/tasuren/niconico.py/blob/b4d9fcb1d0b80e83f2d8635dd85987d1fa2d84fc/niconico/video.py#L367
        is_niconico = url.startswith("https://www.nicovideo.jp/") or url.startswith("https://nico.ms/")
        if is_niconico:
            source = await NicoNicoDLSource.from_url(url)
        else:
            source = await YTDLSource.from_url(url, loop=client.loop, stream=True)

        if ctx.guild.voice_client.is_playing():  # 他の曲を再生中の場合
            # self.playerに追加すると再生中の曲と衝突する
            self.queue.append(source)
            embed = discord.Embed(colour=0xff00ff, title=source.title, url=source.original_url)
            embed.set_author(name="キューに追加しました")
            await play_msg.edit(embed=embed)

        else:  # 他の曲を再生していない場合
            # self.playerにURLを追加し再生する
            self.player = source
            ctx.guild.voice_client.play(self.player, after=lambda e: after_play_niconico(self.player, e, ctx.guild, self.after_play))
            embed = discord.Embed(colour=0xff00ff, title=self.player.title, url=self.player.original_url)
            embed.set_author(name="再生を開始します")
            await play_msg.edit(embed=embed)

    @commands.command(aliases=["q"])
    async def queue(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続してねぇぴょ。")
            return

        # 再生中ではない場合は実行しない
        if not ctx.guild.voice_client.is_playing():
            embed = discord.Embed(colour=0xff00ff, title="現在のキュー", description="再生されていません")
            await ctx.channel.send(embed=embed)
            return

        queue_embed = [f"__現在再生中__:\n[{self.player.title}]({self.player.original_url})"]

        if len(self.queue) > 0:
            for i in range(min(len(self.queue), 10)):
                if i == 0:
                    queue_embed.append(f"__次に再生__:\n`{i + 1}.` [{self.queue[i].title}]({self.queue[i].original_url})")
                else:
                    queue_embed.append(f"`{i + 1}.` [{self.queue[i].title}]({self.queue[i].original_url})")

        queue_embed.append(f"**残りのキュー: {len(self.queue) + 1} 個**")

        embed = discord.Embed(colour=0xff00ff, title="現在のキュー", description="\n\n".join(queue_embed))
        await ctx.channel.send(embed=embed)

    @commands.command(aliases=["s"])
    async def skip(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続してねぇぴょ。")
            return

        # 再生中ではない場合は実行しない
        if not ctx.guild.voice_client.is_playing():
            await ctx.channel.send("再生してねぇぴょ。")
            return

        ctx.guild.voice_client.stop()
        await ctx.channel.send("次の曲を再生するぴょ。")

    @commands.command()
    async def shuffle(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくれぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続してねぇぴょ。")
            return

        # 再生中ではない場合は実行しない
        if not ctx.guild.voice_client.is_playing():
            await ctx.channel.send("再生してないぴょよ。")
            return

        random.shuffle(self.queue)
        await ctx.channel.send("キューをシャッフルしたぴょ♥。")

    @commands.command()
    async def stop(self, ctx):
        # コマンドを送ったユーザーがボイスチャンネルに居ない場合
        if ctx.author.voice is None:
            await ctx.channel.send("操作する前にボイスチャンネルに接続してくださいぴょ。")
            return

        # Botがボイスチャンネルに居ない場合
        if ctx.guild.voice_client is None:
            await ctx.channel.send("Botがボイスチャンネルに接続していませんぴょ。")
            return

        # 再生中ではない場合は実行しない
        if not ctx.guild.voice_client.is_playing():
            await ctx.channel.send("再生してないぴょ。")
            return

        self.queue.clear()
        ctx.guild.voice_client.stop()
        await ctx.channel.send("再生を停止し、キューをリセットしたぴょ。")
# ウマ娘ガチャシミュレーター
    @bot.command()
    async def uma(ctx):
        results = []

        three_star = [
            "スペシャルウィーク", "サイレンススズカ", "トウカイテイオー", "マルゼンスキー", "オグリキャップ", "タイキシャトル", "メジロマックイーン", "シンボリルドルフ", "ライスシャワー", "テイエムオペラオー", "ミホノブルボン", "トウカイテイオー(新衣装)", "メジロマックイーン(新衣装)", "カレンチャン",
            "ナリタタイシン", "スマートファルコン", "ナリタブライアン", "マヤノトップガン(花嫁/新衣装)", "エアグルーヴ(花嫁/新衣装)", "セイウンスカイ", "ヒシアマゾン", "エルコンドルパサー(新衣装)", "グラスワンダー(新衣装)", "フジキセキ", "ゴールドシチー", "水着スペシャルウィーク", "水着マルゼンスキー",
            "メイショウドトウ", "エイシンフラッシュ", "マチカネフクキタル(新衣装)", "ヒシアケボノ", "アグネスデジタル", "ライスシャワー(ハロウィン)", "スーパークリーク(ハロウィン)", "カワカミプリンセス", "マンハッタンカフェ", "シンボリルドルフ(新衣装)", "ゴールドシチー(新衣装)", "トーセンジョーダン",
            "メジロドーベル", "ビワハヤヒデ(クリスマス)", "ファインモーション", "タマモクロス", "ハルウララ(新衣装)", "テイエムオペラオー(新衣装)", "サクラチヨノオー", "ミホノブルボン(新衣装)", "エイシンフラッシュ(新衣装)", "メジロアルダン", "アドマイヤベガ", "キタサンブラック", "サトノダイヤモンド",
            "メジロブライト", "セイウンスカイ(新衣装)", "フジキセキ(新衣装)", "ニシノフラワー", "ヤエノムテキ", "ナイスネイチャ(新衣装)", "キングヘイロー(新衣装)", "アイネスフウジン", "メジロパーマー", "カレンチャン(新衣装)", "ファインモーション(新衣装)"
           ]
        two_star = ["ゴールドシップ", "ウオッカ", "ダイワスカーレット", "グラスワンダー", "エルコンドルパサー", "エアグルーヴ", "マヤノトップガン", "スーパークリーク", "マチカネタンホイザ"]
        one_star = ["メジロライアン", "アグネスタキオン", "ウイニングチケット", "サクラバクシンオー", "ハルウララ", "マチカネフクキタル", "ナイスネイチャ", "キングヘイロー"]
        for i in range(10):
            items = [f"☆3 {random.choice(three_star)}", f"☆2 {random.choice(two_star)}", f"☆1 {random.choice(one_star)}"]  # 内容
            prob = [0.03, 0.18, 0.79]  # 確率

            result_random = random.choices(items, weights=prob)
            results.append(result_random[0])

        result_str = "\n".join(results)
        await ctx.send(result_str)


class NicoNicoDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, url, original_url, video, volume=0.5):
        super().__init__(source, volume)

        self.url = url
        self.original_url = original_url
        self.video = video
        self.title = video.video.title

    @classmethod
    async def from_url(cls, url):
        # とりあえず毎回clientを作っておくぴょ
        niconico_client = NicoNico()
        video = niconico_client.video.get_video(url)
        # 必ずあとでコネクションを切る
        video.connect()

        source = discord.FFmpegPCMAudio(video.download_link, **FFMPEG_OPTIONS)
        return cls(source, video.download_link, url, video)

    def close_connection(self):
        self.video.close()


# もしniconicoDLをいれるなら参考になるかも
# https://github.com/akomekagome/SmileMusic/blob/dd94c342fed5301c790ce64360ad33f7c0d46208/python/smile_music.py
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)

        self.data = data
        self.id = data.get("id")
        self.original_url = data.get("original_url")
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if "entries" in data:
            # take first item from a playlist
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)

        source = discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS)
        return cls(source, data=data)


# ピンポン
@bot.command()
async def ping(ctx):
    latency = bot.latency
    latency_milli = round(latency * 1000)
    await ctx.send(f"Pong!: {latency_milli}ms")


bot.add_cog(Music(bot_arg=bot))
bot.run(DISCORD_BOT_TOKEN)

